"""Safety tests: no external-send behavior, suppression precedence, proposal draft-only,
JSONL validation, git sync failure handling."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from client_acquisition.scripts.crm import CRM, make_lead_key
from client_acquisition.scripts.discovery import generate_proposal, process_discovered_lead
from client_acquisition.scripts.git_sync import sync, current_branch, working_tree_clean


class TestNoExternalSend(unittest.TestCase):
    def test_proposal_approved_for_sending_false(self):
        lead = {
            "lead_key": "domain:example.am",
            "business_name": "Example",
            "city": "Yerevan",
            "country": "Armenia",
            "website_url": "https://example.am/",
            "evidence_observations": ["no website"],
            "proposed_opportunity": "build site",
            "fit_score": 80,
        }
        prop = generate_proposal(lead, language="English")
        self.assertEqual(prop["status"], "draft")
        self.assertFalse(prop["approved_for_sending"])
        self.assertTrue(len(prop["facts_used"]) > 0)
        self.assertIsInstance(prop["facts_used"], list)

    def test_crm_has_no_send_methods(self):
        crm = CRM(Path(tempfile.mkdtemp()) / "root")
        (crm.root / "client_acquisition" / "data").mkdir(parents=True)
        (crm.root / "client_acquisition" / "schemas").mkdir(parents=True)
        (crm.root / "client_acquisition" / "config.json").write_text("{}")
        methods = [m for m in dir(crm) if "send" in m.lower() or "email" in m.lower()
                   or "telegram" in m.lower() or "message" in m.lower()]
        self.assertEqual(methods, [])

    def test_proposal_does_not_pretend_demo_exists(self):
        lead = {
            "lead_key": "domain:example.am",
            "business_name": "Example Co",
            "city": "Yerevan",
            "country": "Armenia",
            "evidence_observations": ["site is old"],
            "proposed_opportunity": "redesign",
        }
        prop = generate_proposal(lead, language="English")
        body_lower = prop["body"].lower()
        self.assertNotIn("demo already", body_lower)
        self.assertNotIn("audit already", body_lower)
        self.assertNotIn("implementation already", body_lower)
        self.assertNotIn("free demo", body_lower)


class TestSuppressionPrecedence(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        (self.root / "client_acquisition" / "data").mkdir(parents=True)
        (self.root / "client_acquisition" / "schemas").mkdir(parents=True)
        (self.root / "client_acquisition" / "config.json").write_text(
            json.dumps({"discovery": {"max_businesses_per_run": 10},
                        "scoring": {"proposal_threshold": 60},
                        "data": {"files": {}}})
        )
        self.crm = CRM(self.root)

    def test_suppression_overrides_high_score(self):
        lead = {
            "business_name": "High Score Co",
            "city": "Yerevan",
            "country": "Armenia",
            "website_url": "https://highscore.am/",
            "business_category": "web",
            "proposed_opportunity": "automation",
            "evidence_observations": ["obs"],
            "score_explanation": "test",
            "fit_score": 95,
        }
        self.crm.add_lead(lead)
        lead_key = make_lead_key("https://highscore.am/", "High Score Co", "Yerevan", "Armenia")
        self.crm.add_suppression({"lead_key": lead_key, "reason": "do not contact"})

        # Re-attempt with even higher score - still suppressed
        lead2 = dict(lead)
        lead2["fit_score"] = 100
        added, reason, _ = self.crm.add_lead(lead2)
        self.assertFalse(added)
        self.assertIn("suppress", reason.lower())


class TestGitSyncSafety(unittest.TestCase):
    def test_current_branch_and_clean_detection(self):
        tmp = tempfile.mkdtemp()
        root = Path(tmp)
        (root / ".git").mkdir()
        # Not a real git repo; current_branch should return None gracefully
        self.assertIsNone(current_branch(root))
        clean, out = working_tree_clean(root)
        self.assertFalse(clean)


if __name__ == "__main__":
    unittest.main()
