"""Mocked unit tests for the Resend email sender.

Tests never send real emails. The Resend SDK and API calls are mocked.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from client_acquisition.scripts.resend_sender import (
    ResendSender,
    compute_idempotency_key,
    is_valid_email,
)


def make_root() -> Path:
    tmp = Path(tempfile.mkdtemp())
    (tmp / "client_acquisition" / "data").mkdir(parents=True)
    (tmp / "client_acquisition" / "schemas").mkdir(parents=True)
    config = {
        "email": {
            "dry_run_default": True,
            "per_run_limit": 5,
            "daily_limit": 10,
            "api_key_env": "RESEND_API_KEY",
            "from_email_env": "RESEND_FROM_EMAIL",
        },
        "data": {"files": {}},
    }
    (tmp / "client_acquisition" / "config.json").write_text(json.dumps(config))
    for fname in ("leads.jsonl", "proposals.jsonl", "events.jsonl",
                  "suppression.jsonl", "sends.jsonl"):
        (tmp / "client_acquisition" / "data" / fname).touch()
    return tmp


class TestHelpers(unittest.TestCase):
    def test_is_valid_email(self):
        self.assertTrue(is_valid_email("a@b.com"))
        self.assertFalse(is_valid_email(""))
        self.assertFalse(is_valid_email("not-an-email"))
        self.assertFalse(is_valid_email(None))

    def test_idempotency_key_stable(self):
        k1 = compute_idempotency_key("a@b.com", "Subject", "Body")
        k2 = compute_idempotency_key("a@b.com", "Subject", "Body")
        self.assertEqual(k1, k2)

    def test_idempotency_key_changes_with_payload(self):
        k1 = compute_idempotency_key("a@b.com", "Subject", "Body A")
        k2 = compute_idempotency_key("a@b.com", "Subject", "Body B")
        self.assertNotEqual(k1, k2)

    def test_idempotency_key_case_insensitive_recipient(self):
        k1 = compute_idempotency_key("A@B.com", "Subject", "Body")
        k2 = compute_idempotency_key("a@b.com", "Subject", "Body")
        self.assertEqual(k1, k2)


class TestConfig(unittest.TestCase):
    def setUp(self):
        self.root = make_root()
        self.sender = ResendSender(self.root)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.root, ignore_errors=True)

    @patch.dict(os.environ, {}, clear=True)
    def test_check_config_missing_keys(self):
        with patch.dict(os.environ, {}, clear=True):
            result = self.sender.check_config()
        self.assertFalse(result["ok"])
        joined = "\n".join(result["details"])
        self.assertIn("RESEND_API_KEY", joined)
        self.assertIn("RESEND_FROM_EMAIL", joined)

    @patch.dict(os.environ, {
        "RESEND_API_KEY": "re_test_1234567890abcdef",
        "RESEND_FROM_EMAIL": "sender@example.com",
    }, clear=True)
    def test_check_config_ok(self):
        sender = ResendSender(self.root)
        result = sender.check_config()
        self.assertTrue(result["ok"])
        # Secrets must never appear in details
        joined = "\n".join(result["details"])
        self.assertNotIn("re_test_1234567890abcdef", joined)
        self.assertNotIn("sender@example.com", joined)


class TestSendTest(unittest.TestCase):
    def setUp(self):
        self.root = make_root()
        self.sender = ResendSender(self.root)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.root, ignore_errors=True)

    @patch.dict(os.environ, {
        "RESEND_API_KEY": "re_test_1234567890abcdef",
        "RESEND_FROM_EMAIL": "sender@example.com",
    }, clear=True)
    def test_send_test_dry_run_does_not_call_api(self):
        with patch.object(self.sender, "_call_resend") as mock_call:
            rc = self.sender.cmd_send_test(to="friend@example.com", send=False)
        self.assertEqual(rc, 0)
        mock_call.assert_not_called()
        # Intent should be recorded
        sends = self.sender.store.read_all()
        self.assertEqual(len(sends), 1)
        self.assertEqual(sends[0]["status"], "submitted")
        self.assertTrue(sends[0]["dry_run"])
        self.assertIsNone(sends[0]["message_id"])

    @patch.dict(os.environ, {
        "RESEND_API_KEY": "re_test_1234567890abcdef",
        "RESEND_FROM_EMAIL": "sender@example.com",
    }, clear=True)
    def test_send_test_blocked_when_suppressed(self):
        # Add suppression entry for the recipient
        self.sender.crm.add_suppression({
            "email": "blocked@example.com",
            "reason": "opted out",
        })
        with patch.object(self.sender, "_call_resend") as mock_call:
            rc = self.sender.cmd_send_test(to="blocked@example.com", send=True)
        self.assertEqual(rc, 1)
        mock_call.assert_not_called()

    @patch.dict(os.environ, {
        "RESEND_API_KEY": "re_test_1234567890abcdef",
        "RESEND_FROM_EMAIL": "sender@example.com",
    }, clear=True)
    def test_send_test_invalid_recipient(self):
        with patch.object(self.sender, "_call_resend") as mock_call:
            rc = self.sender.cmd_send_test(to="not-an-email", send=False)
        self.assertEqual(rc, 1)
        mock_call.assert_not_called()


class TestSendApproved(unittest.TestCase):
    def setUp(self):
        self.root = make_root()
        self.sender = ResendSender(self.root)
        self.lead_key = "domain:example.am"
        # Insert an approved proposal
        self.sender.crm.add_proposal({
            "lead_key": self.lead_key,
            "subject": "Proposal for Example",
            "body": "Hello, here is a specific verified observation and one realistic improvement.",
            "language": "English",
            "status": "approved",
            "facts_used": ["observation: site is old"],
            "approved_for_sending": True,
        })

    def tearDown(self):
        import shutil
        shutil.rmtree(self.root, ignore_errors=True)

    @patch.dict(os.environ, {
        "RESEND_API_KEY": "re_test_1234567890abcdef",
        "RESEND_FROM_EMAIL": "sender@example.com",
    }, clear=True)
    def test_send_approved_blocked_when_not_approved(self):
        # Change status to draft
        self.sender.crm.add_proposal({
            "lead_key": "domain:draft.am",
            "subject": "Draft",
            "body": "Draft body",
            "language": "English",
            "status": "draft",
            "facts_used": [],
        })
        with patch.object(self.sender, "_call_resend") as mock_call:
            rc = self.sender.cmd_send_approved(lead_key="domain:draft.am", to="a@b.com", send=False)
        self.assertEqual(rc, 1)
        mock_call.assert_not_called()

    @patch.dict(os.environ, {
        "RESEND_API_KEY": "re_test_1234567890abcdef",
        "RESEND_FROM_EMAIL": "sender@example.com",
    }, clear=True)
    def test_send_approved_dry_run_records_intent(self):
        with patch.object(self.sender, "_call_resend") as mock_call:
            rc = self.sender.cmd_send_approved(lead_key=self.lead_key, to="client@example.com", send=False)
        self.assertEqual(rc, 0)
        mock_call.assert_not_called()
        sends = self.sender.store.find_for_lead(self.lead_key)
        self.assertEqual(len(sends), 1)
        self.assertEqual(sends[0]["status"], "submitted")
        self.assertTrue(sends[0]["dry_run"])

    @patch.dict(os.environ, {
        "RESEND_API_KEY": "re_test_1234567890abcdef",
        "RESEND_FROM_EMAIL": "sender@example.com",
    }, clear=True)
    def test_send_approved_idempotency_blocks_duplicate(self):
        # First dry-run send
        self.sender.cmd_send_approved(lead_key=self.lead_key, to="client@example.com", send=False)
        # Same lead + recipient + body -> same idempotency key -> blocked
        with patch.object(self.sender, "_call_resend") as mock_call:
            rc = self.sender.cmd_send_approved(lead_key=self.lead_key, to="client@example.com", send=False)
        self.assertEqual(rc, 1)
        mock_call.assert_not_called()

    @patch.dict(os.environ, {
        "RESEND_API_KEY": "re_test_1234567890abcdef",
        "RESEND_FROM_EMAIL": "sender@example.com",
    }, clear=True)
    def test_send_approved_real_send_marks_submitted(self):
        def fake_call(api_key, from_email, recipient, subject, body, idempotency_key):
            return True, "resend_msg_123", None

        with patch.object(self.sender, "_call_resend", side_effect=fake_call):
            rc = self.sender.cmd_send_approved(lead_key=self.lead_key, to="client@example.com", send=True)
        self.assertEqual(rc, 0)
        sends = self.sender.store.find_for_lead(self.lead_key)
        self.assertEqual(sends[0]["status"], "submitted")
        self.assertEqual(sends[0]["message_id"], "resend_msg_123")
        self.assertFalse(sends[0]["dry_run"])

    @patch.dict(os.environ, {
        "RESEND_API_KEY": "re_test_1234567890abcdef",
        "RESEND_FROM_EMAIL": "sender@example.com",
    }, clear=True)
    def test_send_approved_uncertain_response_marks_unknown(self):
        def fake_call(api_key, from_email, recipient, subject, body, idempotency_key):
            return False, None, "uncertain_response: no message id in response"

        with patch.object(self.sender, "_call_resend", side_effect=fake_call):
            rc = self.sender.cmd_send_approved(lead_key=self.lead_key, to="client@example.com", send=True)
        self.assertEqual(rc, 1)
        sends = self.sender.store.find_for_lead(self.lead_key)
        self.assertEqual(sends[0]["status"], "send_status_unknown")

    @patch.dict(os.environ, {
        "RESEND_API_KEY": "re_test_1234567890abcdef",
        "RESEND_FROM_EMAIL": "sender@example.com",
    }, clear=True)
    def test_send_approved_proposal_not_found(self):
        with patch.object(self.sender, "_call_resend") as mock_call:
            rc = self.sender.cmd_send_approved(lead_key="domain:nonexistent.am", to="a@b.com", send=False)
        self.assertEqual(rc, 1)
        mock_call.assert_not_called()


class TestLimits(unittest.TestCase):
    def setUp(self):
        self.root = make_root()
        self.sender = ResendSender(self.root)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.root, ignore_errors=True)

    @patch.dict(os.environ, {
        "RESEND_API_KEY": "re_test_1234567890abcdef",
        "RESEND_FROM_EMAIL": "sender@example.com",
    }, clear=True)
    def test_per_run_limit(self):
        self.sender.email_config["per_run_limit"] = 2
        for i in range(2):
            rc = self.sender.cmd_send_test(to=f"t{i}@example.com", send=False)
            self.assertEqual(rc, 0)
        # Third should be blocked by per-run limit
        rc = self.sender.cmd_send_test(to="t3@example.com", send=False)
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
