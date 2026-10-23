"""Client Acquisition CRM layer.

Persistent lead/proposal/event/suppression store backed by JSONL files with
file locking, atomic writes, deduplication, and validation.

CLI commands:
    python -m client_acquisition.scripts.crm stats
    python -m client_acquisition.scripts.crm list
    python -m client_acquisition.scripts.crm validate
    python -m client_acquisition.scripts.crm export-report
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    from jsonschema import Draft7Validator
    _HAS_JSONSCHEMA = True
except Exception:  # pragma: no cover - jsonschema optional
    _HAS_JSONSCHEMA = False


DATA_FILE_NAMES = ("leads.jsonl", "proposals.jsonl", "events.jsonl", "suppression.jsonl")
LOCK_FILE_NAME = ".crm.lock"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_domain(url: Optional[str]) -> Optional[str]:
    """Normalize a website URL to a bare domain identity key.

    Removes scheme, www., paths, query strings, fragments, and trailing slashes.
    Returns None for empty/missing input.
    """
    if not url or not isinstance(url, str):
        return None
    value = url.strip().lower()
    if not value:
        return None
    value = re.sub(r"^https?://", "", value)
    value = re.sub(r"^[^@]+@", "", value)
    value = re.sub(r"^www\.", "", value)
    for sep in ("/", "?", "#"):
        idx = value.find(sep)
        if idx != -1:
            value = value[:idx]
    value = value.rstrip("/.")
    value = value.strip()
    return value or None


def normalize_name(name: Optional[str]) -> str:
    if not name:
        return ""
    return re.sub(r"\s+", " ", name.strip().lower())


def location_key(city: Optional[str], country: Optional[str]) -> str:
    parts = []
    if city:
        parts.append(city.strip().lower())
    if country:
        parts.append(country.strip().lower())
    return "|".join(parts)


def make_lead_key(website_url: Optional[str], business_name: Optional[str],
                  city: Optional[str], country: Optional[str]) -> str:
    """Build a stable unique lead key.

    Primary: normalized domain. Fallback: normalized name + location.
    """
    domain = normalize_domain(website_url)
    if domain:
        return f"domain:{domain}"
    name = normalize_name(business_name)
    loc = location_key(city, country)
    return f"name:{name}|{loc}" if loc else f"name:{name}"


def _data_dir(root: Path) -> Path:
    return root / "client_acquisition" / "data"


def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    """Read JSONL records without locking. Malformed lines are reported, not dropped."""
    records: List[Dict[str, Any]] = []
    if not path.exists():
        return records
    with path.open("r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                records.append({
                    "_malformed": True,
                    "_file": str(path),
                    "_line": line_no,
                    "_error": str(exc),
                    "_raw": line[:2000],
                })
    return records


def _atomic_write_jsonl(path: Path, records: Iterable[Dict[str, Any]]) -> None:
    """Atomically write JSONL records via temp file + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp_", suffix=".jsonl")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tmp:
            for rec in records:
                tmp.write(json.dumps(rec, ensure_ascii=False, sort_keys=True))
                tmp.write("\n")
        os.replace(tmp_name, str(path))
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


class CRMLock:
    """Process-wide exclusive file lock for the CRM data directory."""

    def __init__(self, data_dir: Path):
        self._lock_path = data_dir / LOCK_FILE_NAME
        self._fh: Optional[Any] = None

    def __enter__(self) -> "CRMLock":
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self._lock_path, "w", encoding="utf-8")
        fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._fh is not None:
            try:
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
            finally:
                self._fh.close()
                self._fh = None


class CRM:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.data_dir = _data_dir(self.root)
        self.config_path = self.root / "client_acquisition" / "config.json"
        self.config: Dict[str, Any] = self._load_config()
        self.data_config = self.config.get("data", {})
        files_cfg = self.data_config.get("files", {})
        self.leads_path = self.data_dir / files_cfg.get("leads", "leads.jsonl")
        self.proposals_path = self.data_dir / files_cfg.get("proposals", "proposals.jsonl")
        self.events_path = self.data_dir / files_cfg.get("events", "events.jsonl")
        self.suppression_path = self.data_dir / files_cfg.get("suppression", "suppression.jsonl")

    def _load_config(self) -> Dict[str, Any]:
        if self.config_path.exists():
            try:
                with self.config_path.open("r", encoding="utf-8") as fh:
                    return json.load(fh)
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

    def _get_threshold(self) -> int:
        return int(self.config.get("scoring", {}).get("proposal_threshold", 60))

    def _max_per_run(self) -> int:
        return int(self.config.get("discovery", {}).get("max_businesses_per_run", 10))

    # ------------------------------------------------------------------ locked IO
    def _with_lock(self, data_dir: Optional[Path] = None) -> CRMLock:
        return CRMLock(data_dir or self.data_dir)

    # Internal (unlocked) readers - safe to call from within a locked context.
    def _read_leads_unlocked(self) -> List[Dict[str, Any]]:
        return _load_jsonl(self.leads_path)

    def _read_proposals_unlocked(self) -> List[Dict[str, Any]]:
        return _load_jsonl(self.proposals_path)

    def _read_events_unlocked(self) -> List[Dict[str, Any]]:
        return _load_jsonl(self.events_path)

    def _read_suppression_unlocked(self) -> List[Dict[str, Any]]:
        return _load_jsonl(self.suppression_path)

    # Public (locked) readers.
    def read_leads(self) -> List[Dict[str, Any]]:
        with self._with_lock():
            return self._read_leads_unlocked()

    def read_proposals(self) -> List[Dict[str, Any]]:
        with self._with_lock():
            return self._read_proposals_unlocked()

    def read_events(self) -> List[Dict[str, Any]]:
        with self._with_lock():
            return self._read_events_unlocked()

    def read_suppression(self) -> List[Dict[str, Any]]:
        with self._with_lock():
            return self._read_suppression_unlocked()

    def _append_event(self, event_type: str, payload: Dict[str, Any]) -> None:
        event = {
            "event_id": f"evt_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}",
            "type": event_type,
            "timestamp": utc_now(),
            "payload": payload,
        }
        # Acquire lock once for read+write.
        with self._with_lock():
            records = self._read_events_unlocked()
            records.append(event)
            _atomic_write_jsonl(self.events_path, records)

    # ----------------------------------------------------------- dedup/suppression
    def is_suppressed(self, lead_key: str, business_name: Optional[str] = None,
                      domain: Optional[str] = None) -> Tuple[bool, Optional[str]]:
        """Check suppression list. Returns (suppressed, reason)."""
        norm_domain = normalize_domain(domain) if domain else None
        norm_name = normalize_name(business_name) if business_name else None
        with self._with_lock():
            records = self._read_suppression_unlocked()
        for rec in records:
            if rec.get("_malformed"):
                continue
            if rec.get("lead_key") == lead_key:
                return True, rec.get("reason", "suppressed by lead_key")
            if norm_domain and rec.get("domain") == norm_domain:
                return True, rec.get("reason", "suppressed by domain")
            if norm_name and rec.get("business_name") == norm_name:
                return True, rec.get("reason", "suppressed by business_name")
        return False, None

    def find_existing_lead(self, lead_key: str) -> Optional[Dict[str, Any]]:
        with self._with_lock():
            records = self._read_leads_unlocked()
        for rec in records:
            if rec.get("_malformed"):
                continue
            if rec.get("lead_key") == lead_key:
                return rec
        return None

    # ----------------------------------------------------------- add lead
    def add_lead(self, lead: Dict[str, Any]) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Add a lead if not duplicate and not suppressed.

        Returns (added, reason, existing_record_or_None).
        Never overwrites an existing lead.
        """
        lead_key = lead.get("lead_key") or make_lead_key(
            lead.get("website_url"), lead.get("business_name"),
            lead.get("city"), lead.get("country"),
        )
        lead["lead_key"] = lead_key
        now = utc_now()
        lead.setdefault("discovered_at", now)
        lead["last_verified_at"] = lead.get("last_verified_at") or lead["discovered_at"]
        lead.setdefault("score", 0)
        lead.setdefault("score_explanation", "")
        lead.setdefault("status", "new")
        lead.setdefault("follow_up_eligible", True)
        lead.setdefault("suppressed", False)
        lead.setdefault("research_notes", "")
        lead.setdefault("evidence_observations", [])
        lead.setdefault("public_source_urls", [])
        lead.setdefault("public_contact_page", None)

        # Lock once for all checks + write.
        with self._with_lock():
            # Suppression check
            suppressed, reason = self._is_suppressed_unlocked(
                lead_key,
                business_name=lead.get("business_name"),
                domain=lead.get("normalized_domain") or normalize_domain(lead.get("website_url")),
            )
            if suppressed:
                lead["suppressed"] = True
                lead["status"] = "suppressed"
                lead["research_notes"] = (lead.get("research_notes") or "") + f" | Suppressed: {reason}"
                records = self._read_leads_unlocked()
                records.append(lead)
                _atomic_write_jsonl(self.leads_path, records)
                self._append_event_unlocked("lead_suppressed", {"lead_key": lead_key, "reason": reason})
                return False, f"suppressed: {reason}", None

            # Dedup check
            existing = self._find_existing_lead_unlocked(lead_key)
            if existing is not None:
                self._append_event_unlocked("lead_duplicate_skipped", {
                    "lead_key": lead_key,
                    "existing_lead_key": existing.get("lead_key"),
                    "reason": "lead_key_already_exists",
                })
                return False, "duplicate: lead_key already exists", existing

            # Append
            records = self._read_leads_unlocked()
            records.append(lead)
            _atomic_write_jsonl(self.leads_path, records)
        self._append_event("lead_added", {"lead_key": lead_key, "business_name": lead.get("business_name")})
        return True, "added", None

    def _is_suppressed_unlocked(self, lead_key: str, business_name: Optional[str] = None,
                                domain: Optional[str] = None) -> Tuple[bool, Optional[str]]:
        norm_domain = normalize_domain(domain) if domain else None
        norm_name = normalize_name(business_name) if business_name else None
        records = self._read_suppression_unlocked()
        for rec in records:
            if rec.get("_malformed"):
                continue
            if rec.get("lead_key") == lead_key:
                return True, rec.get("reason", "suppressed by lead_key")
            if norm_domain and rec.get("domain") == norm_domain:
                return True, rec.get("reason", "suppressed by domain")
            if norm_name and rec.get("business_name") == norm_name:
                return True, rec.get("reason", "suppressed by business_name")
        return False, None

    def _find_existing_lead_unlocked(self, lead_key: str) -> Optional[Dict[str, Any]]:
        for rec in self._read_leads_unlocked():
            if rec.get("_malformed"):
                continue
            if rec.get("lead_key") == lead_key:
                return rec
        return None

    def _append_event_unlocked(self, event_type: str, payload: Dict[str, Any]) -> None:
        event = {
            "event_id": f"evt_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}",
            "type": event_type,
            "timestamp": utc_now(),
            "payload": payload,
        }
        records = self._read_events_unlocked()
        records.append(event)
        _atomic_write_jsonl(self.events_path, records)

    def update_lead_score(self, lead_key: str, score: int, explanation: str,
                          status: Optional[str] = None) -> bool:
        """Update score/explanation/status for an existing lead without touching other fields."""
        with self._with_lock():
            records = self._read_leads_unlocked()
            changed = False
            for rec in records:
                if rec.get("_malformed"):
                    continue
                if rec.get("lead_key") == lead_key:
                    rec["fit_score"] = score
                    rec["score_explanation"] = explanation
                    rec["last_verified_at"] = utc_now()
                    if status is not None:
                        rec["status"] = status
                    changed = True
                    break
            if not changed:
                return False
            _atomic_write_jsonl(self.leads_path, records)
        self._append_event("lead_scored", {"lead_key": lead_key, "score": score})
        return True

    def set_lead_field(self, lead_key: str, field: str, value: Any) -> bool:
        """Set a single field on an existing lead (preserves all other fields)."""
        with self._with_lock():
            records = self._read_leads_unlocked()
            changed = False
            for rec in records:
                if rec.get("_malformed"):
                    continue
                if rec.get("lead_key") == lead_key:
                    rec[field] = value
                    changed = True
                    break
            if not changed:
                return False
            _atomic_write_jsonl(self.leads_path, records)
        return True

    # ----------------------------------------------------------- proposals
    def add_proposal(self, proposal: Dict[str, Any]) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Add a proposal draft. Never duplicates a proposal for an existing lead_key."""
        proposal.setdefault("proposal_id", f"prop_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}")
        proposal.setdefault("status", "approved")
        proposal.setdefault("created_at", utc_now())
        proposal.setdefault("approved_for_sending", False)
        proposal.setdefault("facts_used", [])
        lead_key = proposal["lead_key"]

        with self._with_lock():
            for rec in self._read_proposals_unlocked():
                if rec.get("_malformed"):
                    continue
                if rec.get("lead_key") == lead_key:
                    self._append_event_unlocked("proposal_duplicate_skipped", {
                        "proposal_id": proposal["proposal_id"],
                        "lead_key": lead_key,
                        "existing_proposal_id": rec.get("proposal_id"),
                    })
                    return False, f"duplicate: proposal already exists for lead {lead_key}", rec

            records = self._read_proposals_unlocked()
            records.append(proposal)
            _atomic_write_jsonl(self.proposals_path, records)
        self._append_event("proposal_added", {
            "proposal_id": proposal["proposal_id"], "lead_key": lead_key,
        })
        return True, "added", None

    def add_suppression(self, entry: Dict[str, Any]) -> Tuple[bool, str]:
        entry.setdefault("suppressed_at", utc_now())
        with self._with_lock():
            records = self._read_suppression_unlocked()
            records.append(entry)
            _atomic_write_jsonl(self.suppression_path, records)
        self._append_event("suppression_added", {"entry": entry})
        return True, "added"

    # ----------------------------------------------------------- stats / list / validate
    def stats(self) -> Dict[str, Any]:
        with self._with_lock():
            leads = [r for r in self._read_leads_unlocked() if not r.get("_malformed")]
            proposals = [r for r in self._read_proposals_unlocked() if not r.get("_malformed")]
            events = self._read_events_unlocked()
            suppression = [r for r in self._read_suppression_unlocked() if not r.get("_malformed")]
        malformed_leads = sum(1 for r in self._read_leads_unlocked() if r.get("_malformed"))
        malformed_props = sum(1 for r in self._read_proposals_unlocked() if r.get("_malformed"))
        status_counts: Dict[str, int] = {}
        for r in leads:
            st = r.get("status", "unknown")
            status_counts[st] = status_counts.get(st, 0) + 1
        suppressed_count = sum(1 for r in leads if r.get("suppressed"))
        return {
            "leads_total": len(leads),
            "leads_malformed": malformed_leads,
            "proposals_total": len(proposals),
            "proposals_malformed": malformed_props,
            "events_total": len(events),
            "suppression_total": len(suppression),
            "leads_suppressed": suppressed_count,
            "status_counts": status_counts,
        }

    def list_leads(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._with_lock():
            leads = [r for r in self._read_leads_unlocked() if not r.get("_malformed")]
        out = []
        for r in leads[:limit]:
            out.append({
                "lead_key": r.get("lead_key"),
                "business_name": r.get("business_name"),
                "city": r.get("city"),
                "country": r.get("country"),
                "normalized_domain": r.get("normalized_domain"),
                "fit_score": r.get("fit_score"),
                "status": r.get("status"),
                "suppressed": r.get("suppressed", False),
                "discovered_at": r.get("discovered_at"),
            })
        return out

    def validate(self) -> Dict[str, Any]:
        """Validate every JSONL record against schemas where possible."""
        result: Dict[str, Any] = {
            "leads": {"total": 0, "valid": 0, "malformed": 0, "schema_invalid": 0, "errors": []},
            "proposals": {"total": 0, "valid": 0, "malformed": 0, "schema_invalid": 0, "errors": []},
            "suppression": {"total": 0, "valid": 0, "malformed": 0, "schema_invalid": 0, "errors": []},
        }

        def check(path: Path, key: str, schema_path: Optional[Path]) -> None:
            records = _load_jsonl(path)
            result[key]["total"] = len(records)
            validator = None
            if _HAS_JSONSCHEMA and schema_path and schema_path.exists():
                try:
                    with schema_path.open("r", encoding="utf-8") as fh:
                        schema = json.load(fh)
                    validator = Draft7Validator(schema)
                except Exception:
                    validator = None
            for idx, rec in enumerate(records):
                if rec.get("_malformed"):
                    result[key]["malformed"] += 1
                    result[key]["errors"].append({
                        "line": rec.get("_line"),
                        "error": rec.get("_error"),
                        "file": rec.get("_file"),
                    })
                    continue
                if validator is not None:
                    errors = sorted(validator.iter_errors(rec), key=lambda e: list(e.path))
                    if errors:
                        result[key]["schema_invalid"] += 1
                        result[key]["errors"].append({
                            "record_index": idx,
                            "lead_key": rec.get("lead_key") or rec.get("proposal_id"),
                            "errors": [e.message for e in errors[:5]],
                        })
                    else:
                        result[key]["valid"] += 1
                else:
                    result[key]["valid"] += 1

        check(self.leads_path, "leads", self.root / "client_acquisition" / "schemas" / "lead.schema.json")
        check(self.proposals_path, "proposals", self.root / "client_acquisition" / "schemas" / "proposal.schema.json")
        check(self.suppression_path, "suppression", None)
        return result

    def export_report(self, out_path: Optional[Path] = None) -> Path:
        if out_path is None:
            out_path = self.root / "client_acquisition" / "reports" / f"crm_report_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        report = {
            "generated_at": utc_now(),
            "stats": self.stats(),
            "leads": self.list_leads(limit=1000),
            "validation": self.validate(),
        }
        with self._with_lock():
            _atomic_write_jsonl(out_path, [report])
        return out_path


# --------------------------------------------------------------------------- CLI
def _cmd_stats(args: argparse.Namespace, crm: CRM) -> int:
    print(json.dumps(crm.stats(), indent=2, ensure_ascii=False))
    return 0


def _cmd_list(args: argparse.Namespace, crm: CRM) -> int:
    leads = crm.list_leads(limit=args.limit)
    if not leads:
        print("No leads found.")
        return 0
    for r in leads:
        print(f"{r['lead_key']} | {r['business_name']} | {r['city']}, {r['country']} | score={r['fit_score']} | status={r['status']} | suppressed={r['suppressed']}")
    return 0


def _cmd_validate(args: argparse.Namespace, crm: CRM) -> int:
    result = crm.validate()
    print(json.dumps(result, indent=2, ensure_ascii=False))
    total_invalid = sum(v["malformed"] + v["schema_invalid"] for v in result.values())
    return 1 if total_invalid > 0 else 0


def _cmd_export_report(args: argparse.Namespace, crm: CRM) -> int:
    out = crm.export_report(Path(args.out) if args.out else None)
    print(f"Report exported to {out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="crm", description="Client Acquisition CRM")
    sub = parser.add_subparsers(dest="command", required=True)

    p_stats = sub.add_parser("stats", help="Show CRM statistics")
    p_stats.set_defaults(func=_cmd_stats)

    p_list = sub.add_parser("list", help="List leads")
    p_list.add_argument("--limit", type=int, default=50)
    p_list.set_defaults(func=_cmd_list)

    p_validate = sub.add_parser("validate", help="Validate JSONL records")
    p_validate.set_defaults(func=_cmd_validate)

    p_export = sub.add_parser("export-report", help="Export a CRM report JSON")
    p_export.add_argument("--out", type=str, default=None, help="Output path")
    p_export.set_defaults(func=_cmd_export_report)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    crm = CRM(Path.cwd())
    return args.func(args, crm)


if __name__ == "__main__":
    sys.exit(main())
