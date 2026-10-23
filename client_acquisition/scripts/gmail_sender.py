"""Gmail API email sender for approved client-acquisition proposals.

Dry-run by default. Requires an explicit --send flag for real submission.
Never stores or prints secrets. Never sends to suppressed recipients.
Never bulk-blasts or auto-follows up.

Credentials (read from environment only, never committed):
    GMAIL_CLIENT_ID     OAuth2 client ID
    GMAIL_CLIENT_SECRET OAuth2 client secret
    GMAIL_REFRESH_TOKEN OAuth2 refresh token (long-lived)
    GMAIL_FROM_EMAIL    sender address (must be the Gmail account or an alias)

CLI commands:
    python -m client_acquisition.scripts.gmail_sender check-config
    python -m client_acquisition.scripts.gmail_sender send-test --to RECIPIENT [--send]
    python -m client_acquisition.scripts.gmail_sender send-approved --lead-key KEY --to RECIPIENT [--send]

Data files:
    client_acquisition/data/sends.jsonl   -- send intent / history (append-only)
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone, date
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from client_acquisition.scripts.crm import CRM, utc_now

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

SEND_STATUSES = ("intent", "submitted", "delivered", "bounced", "failed", "send_status_unknown")

DEFAULT_GMAIL_CONFIG = {
    "dry_run_default": True,
    "per_run_limit": 5,
    "daily_limit": 10,
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def today_iso() -> str:
    return date.today().isoformat()


def stable_id(*parts: str) -> str:
    joined = "|".join(p or "" for p in parts)
    return "id_" + hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


def compute_idempotency_key(recipient: str, subject: str, body: str) -> str:
    """Stable idempotency key for a specific message payload.

    Same recipient + subject + body -> same key (safe to retry).
    Different payload -> different key (never reuse a key with different content).
    """
    joined = f"{recipient.strip().lower()}|{subject.strip()}|{body.strip()}"
    return "idem_" + hashlib.sha256(joined.encode("utf-8")).hexdigest()


def is_valid_email(value: Optional[str]) -> bool:
    if not value or not isinstance(value, str):
        return False
    return bool(EMAIL_RE.match(value.strip()))


class SendStore:
    """Append-only send-intent/history store backed by sends.jsonl with its own lock.

    Kept separate from the CRM so the CRM remains free of any external-send surface.
    """

    LOCK_FILE_NAME = ".sends.lock"

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.path = self.data_dir / "sends.jsonl"
        self.lock_path = self.data_dir / self.LOCK_FILE_NAME

    def _lock(self):
        import fcntl
        self.data_dir.mkdir(parents=True, exist_ok=True)
        fh = open(self.lock_path, "w", encoding="utf-8")
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        return fh

    def _unlock(self, fh):
        try:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        finally:
            fh.close()

    def _read_unlocked(self) -> List[Dict[str, Any]]:
        from client_acquisition.scripts.crm import _load_jsonl
        return _load_jsonl(self.path)

    def read_all(self) -> List[Dict[str, Any]]:
        fh = self._lock()
        try:
            return self._read_unlocked()
        finally:
            self._unlock(fh)

    def find_by_idempotency_key(self, idempotency_key: str) -> Optional[Dict[str, Any]]:
        fh = self._lock()
        try:
            for rec in self._read_unlocked():
                if rec.get("_malformed"):
                    continue
                if rec.get("idempotency_key") == idempotency_key:
                    return rec
        finally:
            self._unlock(fh)
        return None

    def find_for_lead(self, lead_key: str) -> List[Dict[str, Any]]:
        fh = self._lock()
        try:
            out = []
            for rec in self._read_unlocked():
                if rec.get("_malformed"):
                    continue
                if rec.get("lead_key") == lead_key:
                    out.append(rec)
            return out
        finally:
            self._unlock(fh)

    def record(self, record: Dict[str, Any]) -> str:
        """Append a new send record. Returns send_id."""
        import fcntl
        record = dict(record)
        record.setdefault("send_id", f"snd_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}")
        record.setdefault("created_at", utc_now())
        record["updated_at"] = utc_now()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        fh = open(self.lock_path, "w", encoding="utf-8")
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            from client_acquisition.scripts.crm import _atomic_write_jsonl, _load_jsonl
            records = _load_jsonl(self.path)
            records.append(record)
            _atomic_write_jsonl(self.path, records)
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            fh.close()
        return record["send_id"]

    def update(self, send_id: str, fields: Dict[str, Any]) -> bool:
        """Update fields on an existing send record. Returns False if not found."""
        import fcntl
        fields = dict(fields)
        fields["updated_at"] = utc_now()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        fh = open(self.lock_path, "w", encoding="utf-8")
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            from client_acquisition.scripts.crm import _atomic_write_jsonl, _load_jsonl
            records = _load_jsonl(self.path)
            changed = False
            for rec in records:
                if rec.get("_malformed"):
                    continue
                if rec.get("send_id") == send_id:
                    rec.update(fields)
                    changed = True
                    break
            if not changed:
                return False
            _atomic_write_jsonl(self.path, records)
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            fh.close()
        return True


class GmailSender:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.crm = CRM(root)
        self.config = self.crm.config
        self.gmail_config = dict(DEFAULT_GMAIL_CONFIG)
        self.gmail_config.update(self.config.get("gmail", {}))
        self.store = SendStore(self.crm.data_dir)
        self._run_sent_count = 0

    # ------------------------------------------------------------------ config
    def _env(self, name: str) -> Optional[str]:
        return os.environ.get(name)

    def check_config(self) -> Dict[str, Any]:
        """Validate configuration without exposing secrets.

        Returns a dict with ok boolean and details. Secret values are never included.
        """
        cid_env = str(self.gmail_config.get("client_id_env", "GMAIL_CLIENT_ID"))
        secret_env = str(self.gmail_config.get("client_secret_env", "GMAIL_CLIENT_SECRET"))
        refresh_env = str(self.gmail_config.get("refresh_token_env", "GMAIL_REFRESH_TOKEN"))
        from_env = str(self.gmail_config.get("from_email_env", "GMAIL_FROM_EMAIL"))

        client_id = self._env(cid_env)
        client_secret = self._env(secret_env)
        refresh_token = self._env(refresh_env)
        from_email = self._env(from_env)

        details: List[str] = []
        ok = True

        if not client_id:
            ok = False
            details.append(f"MISSING: {cid_env} environment variable is not set")
        else:
            details.append(f"OK: {cid_env} is set (value withheld)")

        if not client_secret:
            ok = False
            details.append(f"MISSING: {secret_env} environment variable is not set")
        else:
            details.append(f"OK: {secret_env} is set (value withheld)")

        if not refresh_token:
            ok = False
            details.append(f"MISSING: {refresh_env} environment variable is not set")
        else:
            details.append(f"OK: {refresh_env} is set (value withheld)")

        if not from_email:
            ok = False
            details.append(f"MISSING: {from_env} environment variable is not set")
        elif not is_valid_email(from_email):
            ok = False
            details.append(f"INVALID: {from_env} is not a valid email address")
        else:
            details.append(f"OK: {from_env} is set (value withheld)")

        dry_run = bool(self.gmail_config.get("dry_run_default", True))
        details.append(f"dry_run_default={dry_run}")
        details.append(f"per_run_limit={self.gmail_config.get('per_run_limit')}")
        details.append(f"daily_limit={self.gmail_config.get('daily_limit')}")

        return {"ok": ok, "details": details}

    # ------------------------------------------------------------------ gmail client
    def _get_gmail_service(self):
        """Build an authenticated Gmail API service from env credentials.

        Uses client_id + client_secret + refresh_token so the access token is
        refreshed automatically by google-auth. No interactive browser flow.
        """
        client_id = self._env(str(self.gmail_config.get("client_id_env", "GMAIL_CLIENT_ID")))
        client_secret = self._env(str(self.gmail_config.get("client_secret_env", "GMAIL_CLIENT_SECRET")))
        refresh_token = self._env(str(self.gmail_config.get("refresh_token_env", "GMAIL_REFRESH_TOKEN")))

        if not client_id or not client_secret or not refresh_token:
            raise RuntimeError(
                "GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET and GMAIL_REFRESH_TOKEN "
                "must all be set. Obtain them via the Google Cloud Console OAuth "
                "flow (Desktop app) and store them in environment variables / "
                "Colab Secrets."
            )

        creds = Credentials(
            token=None,
            refresh_token=refresh_token,
            client_id=client_id,
            client_secret=client_secret,
            token_uri="https://oauth2.googleapis.com/token",
        )
        return build("gmail", "v1", credentials=creds, cache_discovery=False)

    def _raw_message(self, from_email: str, recipient: str, subject: str, body: str) -> str:
        message = MIMEText(body, "plain", "utf-8")
        message["To"] = recipient
        message["From"] = from_email
        message["Subject"] = subject
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
        return raw

    # ------------------------------------------------------------------ suppression / history
    def is_recipient_suppressed(self, recipient: str) -> Tuple[bool, Optional[str]]:
        """Check suppression list by recipient email and domain."""
        suppressed, reason = self.crm.is_suppressed(
            lead_key="email:" + recipient.strip().lower(),
            business_name=None,
            domain=recipient.split("@", 1)[1].lower() if "@" in recipient else None,
        )
        if suppressed:
            return True, reason
        for rec in self.crm.read_suppression():
            if rec.get("_malformed"):
                continue
            if rec.get("email") == recipient.strip().lower():
                return True, rec.get("reason", "suppressed by email")
            if rec.get("domain") and "@" in recipient:
                if rec.get("domain") == recipient.split("@", 1)[1].lower():
                    return True, rec.get("reason", "suppressed by domain")
        return False, None

    def find_send_by_idempotency_key(self, idempotency_key: str):
        return self.store.find_by_idempotency_key(idempotency_key)

    def count_sends_today(self) -> int:
        today = today_iso()
        count = 0
        for rec in self.store.read_all():
            if rec.get("_malformed"):
                continue
            created = rec.get("created_at", "")
            if created.startswith(today):
                if rec.get("status") in ("submitted", "delivered", "bounced", "failed", "send_status_unknown"):
                    count += 1
        return count

    def run_limit_remaining(self) -> int:
        limit = int(self.gmail_config.get("per_run_limit", 5))
        return max(0, limit - self._run_sent_count)

    def daily_limit_remaining(self) -> int:
        limit = int(self.gmail_config.get("daily_limit", 10))
        return max(0, limit - self.count_sends_today())

    # ------------------------------------------------------------------ send core
    def _build_send_record(
        self,
        lead_key: Optional[str],
        recipient: str,
        subject: str,
        body: str,
        idempotency_key: str,
        dry_run: bool,
        status: str,
        message_id: Optional[str] = None,
        error: Optional[str] = None,
        attempt: int = 1,
    ) -> Dict[str, Any]:
        return {
            "lead_key": lead_key,
            "recipient": recipient.strip().lower(),
            "subject": subject,
            "body_hash": hashlib.sha256(body.encode("utf-8")).hexdigest()[:16],
            "idempotency_key": idempotency_key,
            "status": status,
            "dry_run": bool(dry_run),
            "message_id": message_id,
            "error": error,
            "attempt": attempt,
            "provider": "gmail",
        }

    def _record_intent(
        self,
        lead_key: Optional[str],
        recipient: str,
        subject: str,
        body: str,
        idempotency_key: str,
        dry_run: bool,
    ) -> str:
        """Persist send intent BEFORE calling the API. Returns the send_id."""
        record = self._build_send_record(
            lead_key, recipient, subject, body, idempotency_key, dry_run, "intent",
        )
        return self.store.record(record)

    def _update_send(self, send_id: str, **fields) -> None:
        self.store.update(send_id, fields)

    def _call_gmail(
        self,
        from_email: str,
        recipient: str,
        subject: str,
        body: str,
        idempotency_key: str,
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """Call Gmail API. Returns (success, message_id, error).

        On success -> (True, gmail_message_id, None).
        On uncertain / HTTP error -> (False, None, error_message). Never blindly resend.
        """
        service = self._get_gmail_service()
        try:
            raw = self._raw_message(from_email, recipient, subject, body)
            response = service.users().messages().send(
                userId="me", body={"raw": raw}
            ).execute()
        except HttpError as exc:
            return False, None, f"gmail_http_error: {exc.resp.status} {exc}"
        except Exception as exc:  # network / auth error
            return False, None, f"gmail_exception: {type(exc).__name__}: {exc}"

        if not isinstance(response, dict):
            return False, None, f"uncertain_response: unexpected type {type(response).__name__}"
        message_id = response.get("id")
        if message_id:
            return True, str(message_id), None
        return False, None, "uncertain_response: no message id in response"

    # ------------------------------------------------------------------ commands
    def cmd_check_config(self) -> int:
        result = self.check_config()
        for line in result["details"]:
            print(line)
        print(f"CONFIG_OK={result['ok']}")
        return 0 if result["ok"] else 1

    def _validate_send_preconditions(
        self,
        recipient: str,
        idempotency_key: str,
        dry_run: bool,
    ) -> Tuple[bool, str]:
        """Return (ok, reason). Checks suppression, history, limits."""
        if not is_valid_email(recipient):
            return False, "invalid recipient email address"

        suppressed, reason = self.is_recipient_suppressed(recipient)
        if suppressed:
            return False, f"recipient suppressed: {reason}"

        existing = self.find_send_by_idempotency_key(idempotency_key)
        if existing is not None:
            st = existing.get("status")
            if st in ("submitted", "delivered"):
                return False, f"already sent: status={st}, message_id={existing.get('message_id')}"
            if st == "send_status_unknown":
                return False, f"previous send uncertain (status={st}); investigate before retrying"
            if st == "failed":
                return False, f"previous send failed ({existing.get('error')}); investigate before retrying"
            if st == "intent" and existing.get("dry_run") == dry_run:
                return False, f"send intent already exists (status={st}); not resubmitting"

        if self.daily_limit_remaining() <= 0:
            return False, f"daily limit reached ({self.gmail_config.get('daily_limit')})"
        if self.run_limit_remaining() <= 0:
            return False, f"per-run limit reached ({self.gmail_config.get('per_run_limit')})"

        return True, "ok"

    def cmd_send_test(self, to: str, send: bool) -> int:
        """Send one explicitly authorized test email. Dry-run unless --send."""
        dry_run = not send
        from_env = str(self.gmail_config.get("from_email_env", "GMAIL_FROM_EMAIL"))
        from_email = self._env(from_env)

        print(f"send-test: recipient={to}")
        print(f"send-test: dry_run={dry_run}")

        if not dry_run and not from_email:
            print(f"ERROR: {from_env} is required for real sends.", file=sys.stderr)
            return 1

        subject = "Test email from Client Acquisition system"
        body = (
            "This is a one-off test email from the client acquisition system.\n"
            "No business proposal is included. This address was explicitly supplied.\n"
        )
        idempotency_key = compute_idempotency_key(to, subject, body)

        ok, reason = self._validate_send_preconditions(to, idempotency_key, dry_run)
        if not ok:
            print(f"BLOCKED: {reason}")
            return 1

        send_id = self._record_intent(
            lead_key=None, recipient=to, subject=subject, body=body,
            idempotency_key=idempotency_key, dry_run=dry_run,
        )
        print(f"Intent persisted: {send_id}")

        if dry_run:
            self._update_send(send_id, status="submitted", message_id=None,
                              error="dry_run: no API call made")
            self._run_sent_count += 1
            print("DRY-RUN: no email submitted to Gmail. Intent recorded as submitted (dry-run).")
            return 0

        success, message_id, error = self._call_gmail(
            from_email, to, subject, body, idempotency_key
        )
        if success:
            self._update_send(send_id, status="submitted", message_id=message_id, error=None)
            self._run_sent_count += 1
            print(f"SENT: message_id={message_id}")
            print("NOTE: 'submitted' means Gmail accepted the message, not that it was delivered.")
            return 0
        if error and "uncertain" in (error or ""):
            self._update_send(send_id, status="send_status_unknown", message_id=None, error=error)
            print(f"UNCERTAIN: {error}")
            print("Investigate in Gmail / Google Cloud before retrying. Do not blindly resend.")
            return 1
        self._update_send(send_id, status="failed", message_id=None, error=error)
        print(f"FAILED: {error}", file=sys.stderr)
        return 1

    def cmd_send_approved(self, lead_key: str, to: str, send: bool) -> int:
        """Send an approved proposal draft. Requires proposal status == 'approved'. Dry-run unless --send."""
        dry_run = not send
        from_env = str(self.gmail_config.get("from_email_env", "GMAIL_FROM_EMAIL"))
        from_email = self._env(from_env)

        print(f"send-approved: lead_key={lead_key} recipient={to} dry_run={dry_run}")

        if not dry_run and not from_email:
            print(f"ERROR: {from_env} is required for real sends.", file=sys.stderr)
            return 1

        # Load proposal from CRM
        proposal = None
        for rec in self.crm.read_proposals():
            if rec.get("_malformed"):
                continue
            if rec.get("lead_key") == lead_key:
                proposal = rec
                break
        if proposal is None:
            print(f"ERROR: no proposal found for lead_key={lead_key}", file=sys.stderr)
            return 1
        if proposal.get("status") != "approved":
            print(f"BLOCKED: proposal status is '{proposal.get('status')}', not 'approved'. "
                  "Explicit human approval required before sending.", file=sys.stderr)
            return 1

        subject = proposal.get("subject") or "(no subject)"
        body = proposal.get("body") or ""
        if not body:
            print("ERROR: proposal body is empty.", file=sys.stderr)
            return 1
        if not is_valid_email(to):
            print("ERROR: invalid recipient email address.", file=sys.stderr)
            return 1

        idempotency_key = compute_idempotency_key(to, subject, body)

        ok, reason = self._validate_send_preconditions(to, idempotency_key, dry_run)
        if not ok:
            print(f"BLOCKED: {reason}")
            return 1

        send_id = self._record_intent(
            lead_key=lead_key, recipient=to, subject=subject, body=body,
            idempotency_key=idempotency_key, dry_run=dry_run,
        )
        print(f"Intent persisted: {send_id}")

        if dry_run:
            self._update_send(send_id, status="submitted", message_id=None,
                              error="dry_run: no API call made")
            self._run_sent_count += 1
            print("DRY-RUN: no email submitted to Gmail. Intent recorded as submitted (dry-run).")
            return 0

        success, message_id, error = self._call_gmail(
            from_email, to, subject, body, idempotency_key
        )
        if success:
            self._update_send(send_id, status="submitted", message_id=message_id, error=None)
            self._run_sent_count += 1
            print(f"SENT: message_id={message_id}")
            print("NOTE: 'submitted' means Gmail accepted the message, not that it was delivered.")
            return 0
        if error and "uncertain" in (error or ""):
            self._update_send(send_id, status="send_status_unknown", message_id=None, error=error)
            print(f"UNCERTAIN: {error}")
            print("Investigate in Gmail / Google Cloud before retrying. Do not blindly resend.")
            return 1
        self._update_send(send_id, status="failed", message_id=None, error=error)
        print(f"FAILED: {error}", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gmail_sender", description="Gmail API email sender (dry-run by default)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_check = sub.add_parser("check-config", help="Validate Gmail configuration without exposing secrets")
    p_check.set_defaults(func=lambda a, s: s.cmd_check_config())

    p_test = sub.add_parser("send-test", help="Send one explicitly authorized test email (dry-run unless --send)")
    p_test.add_argument("--to", required=True, help="Recipient email address")
    p_test.add_argument("--send", action="store_true", help="Really send via Gmail API (default: dry-run)")
    p_test.set_defaults(func=lambda a, s: s.cmd_send_test(a.to, a.send))

    p_approved = sub.add_parser("send-approved", help="Send an approved proposal draft (dry-run unless --send)")
    p_approved.add_argument("--lead-key", required=True, help="CRM lead key of the approved proposal")
    p_approved.add_argument("--to", required=True, help="Recipient email address")
    p_approved.add_argument("--send", action="store_true", help="Really send via Gmail API (default: dry-run)")
    p_approved.set_defaults(func=lambda a, s: s.cmd_send_approved(a.lead_key, a.to, a.send))

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    sender = GmailSender(Path.cwd())
    return args.func(args, sender)


if __name__ == "__main__":
    sys.exit(main())
