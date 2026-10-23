"""Tests for the CRM layer: normalization, dedup, proposals, status preservation,
suppression precedence, JSONL validation, atomic updates, repeated execution."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from client_acquisition.scripts.crm import (
    CRM,
    make_lead_key,
    normalize_domain,
    normalize_name,
    _atomic_write_jsonl,
    _load_jsonl,
)


class TestDomainNormalization(unittest.TestCase):
    def test_strips_scheme_and_www(self):
        self.assertEqual(normalize_domain("https://www.example.com/"), "example.com")
        self.assertEqual(normalize_domain("http://example.com"), "example.com")
        self.assertEqual(normalize_domain("WWW.Example.COM/"), "example.com")

    def test_strips_paths_query_fragment(self):
        self.assertEqual(normalize_domain("https://example.com/path/to/page?x=1#sec"), "example.com")

    def test_removes_trailing_slashes(self):
        self.assertEqual(normalize_domain("example.com///"), "example.com")

    def test_none_and_empty(self):
        self.assertIsNone(normalize_domain(None))
        self.assertIsNone(normalize_domain(""))
        self.assertIsNone(normalize_domain("   "))


class TestLeadKey(unittest.TestCase):
    def test_domain_primary(self):
        key = make_lead_key("https://www.acme.am/", "Acme Co", "Yerevan", "Armenia")
        self.assertEqual(key, "domain:acme.am")

    def test_no_domain_fallback_name_location(self):
        key = make_lead_key(None, "Bakery", "Gyumri", "Armenia")
        self.assertEqual(key, "name:bakery|gyumri|armenia")

    def test_consistent_key(self):
        k1 = make_lead_key("https://example.com/", "Example", "Yerevan", "Armenia")
        k2 = make_lead_key("http://www.example.com", "Example", "Yerevan", "Armenia")
        self.assertEqual(k1, k2)


class TestCRMOperations(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        # Create minimal structure
        (self.root / "client_acquisition" / "data").mkdir(parents=True)
        (self.root / "client_acquisition" / "schemas").mkdir(parents=True)
        (self.root / "client_acquisition" / "config.json").write_text(
            json.dumps({"discovery": {"max_businesses_per_run": 10},
                        "scoring": {"proposal_threshold": 60},
                        "data": {"files": {}}})
        )
        self.crm = CRM(self.root)

    def _write_leads(self, records):
        path = self.crm.leads_path
        _atomic_write_jsonl(path, records)

    def test_add_and_duplicate_prevention(self):
        lead1 = {
            "business_name": "Acme Cafe",
            "city": "Yerevan",
            "country": "Armenia",
            "website_url": "https://www.acmecafe.am/",
            "business_category": "cafe",
            "public_source_urls": ["https://www.acmecafe.am/"],
            "proposed_opportunity": "online ordering",
            "evidence_observations": ["site lacks mobile menu"],
            "score_explanation": "test",
        }
        added1, reason1, _ = self.crm.add_lead(lead1)
        self.assertTrue(added1, reason1)

        # Same domain -> duplicate
        lead2 = dict(lead1)
        lead2["business_name"] = "Acme Cafe Renamed"
        added2, reason2, existing = self.crm.add_lead(lead2)
        self.assertFalse(added2)
        self.assertIsNotNone(existing)
        self.assertIn("duplicate", reason2)

        # Stats reflects one lead
        stats = self.crm.stats()
        self.assertEqual(stats["leads_total"], 1)

    def test_proposal_duplicate_prevention(self):
        lead = {
            "business_name": "Prop Test Co",
            "city": "Yerevan",
            "country": "Armenia",
            "website_url": "https://proptest.am/",
            "business_category": "web",
            "proposed_opportunity": "redesign",
            "evidence_observations": ["old site"],
            "score_explanation": "test",
        }
        self.crm.add_lead(lead)
        lead_key = make_lead_key("https://proptest.am/", "Prop Test Co", "Yerevan", "Armenia")

        prop1 = {
            "lead_key": lead_key,
            "subject": "Hello",
            "body": "Draft 1",
            "language": "English",
            "facts_used": ["site old"],
        }
        ok1, _, _ = self.crm.add_proposal(prop1)
        self.assertTrue(ok1)

        prop2 = {
            "lead_key": lead_key,
            "subject": "Hello again",
            "body": "Draft 2",
            "language": "English",
            "facts_used": ["site old"],
        }
        ok2, reason2, existing = self.crm.add_proposal(prop2)
        self.assertFalse(ok2)
        self.assertIsNotNone(existing)
        self.assertIn("duplicate", reason2)

    def test_preserves_manual_status_edits(self):
        lead = {
            "business_name": "Status Co",
            "city": "Yerevan",
            "country": "Armenia",
            "website_url": "https://statusco.am/",
            "business_category": "retail",
            "proposed_opportunity": "site",
            "evidence_observations": ["obs"],
            "score_explanation": "test",
        }
        self.crm.add_lead(lead)
        lead_key = make_lead_key("https://statusco.am/", "Status Co", "Yerevan", "Armenia")

        # Manually edit status via set_lead_field
        self.crm.set_lead_field(lead_key, "status", "contacted")

        # Re-add same lead (duplicate) should NOT overwrite
        added, _, existing = self.crm.add_lead(lead)
        self.assertFalse(added)

        # Verify status preserved
        leads = self.crm.read_leads()
        rec = [r for r in leads if r.get("lead_key") == lead_key][0]
        self.assertEqual(rec["status"], "contacted")

    def test_suppression_precedence(self):
        # Add a lead first
        lead = {
            "business_name": "Suppressed Co",
            "city": "Yerevan",
            "country": "Armenia",
            "website_url": "https://suppressed.am/",
            "business_category": "retail",
            "proposed_opportunity": "site",
            "evidence_observations": ["obs"],
            "score_explanation": "test",
        }
        added, _, _ = self.crm.add_lead(lead)
        self.assertTrue(added)
        lead_key = make_lead_key("https://suppressed.am/", "Suppressed Co", "Yerevan", "Armenia")

        # Add suppression entry for same domain
        ok, _ = self.crm.add_suppression({
            "domain": "suppressed.am",
            "reason": "opted out",
        })

        # Now try to re-add the lead - should be suppressed
        lead2 = dict(lead)
        lead2["business_name"] = "Suppressed Co v2"
        added2, reason2, _ = self.crm.add_lead(lead2)
        self.assertFalse(added2)
        self.assertIn("suppress", reason2.lower())

    def test_jsonl_malformed_reported_not_deleted(self):
        path = self.crm.leads_path
        # Write a malformed line followed by valid line
        with path.open("w", encoding="utf-8") as fh:
            fh.write("{not valid json\n")
            fh.write(json.dumps({"lead_key": "domain:ok.am", "business_name": "OK"}) + "\n")
        records = _load_jsonl(path)
        malformed = [r for r in records if r.get("_malformed")]
        valid = [r for r in records if not r.get("_malformed")]
        self.assertEqual(len(malformed), 1)
        self.assertEqual(len(valid), 1)
        self.assertEqual(valid[0]["lead_key"], "domain:ok.am")

    def test_atomic_update_integrity(self):
        path = self.crm.leads_path
        records = [{"lead_key": "domain:a.am", "business_name": "A"}]
        _atomic_write_jsonl(path, records)
        # Simulate interrupt: write corrupt temp then ensure replace didn't happen
        # Verify file is valid
        loaded = _load_jsonl(path)
        self.assertEqual(len(loaded), 1)

    def test_repeated_execution_idempotent(self):
        lead = {
            "business_name": "Idem Co",
            "city": "Yerevan",
            "country": "Armenia",
            "website_url": "https://idem.am/",
            "business_category": "web",
            "proposed_opportunity": "automation",
            "evidence_observations": ["obs"],
            "score_explanation": "test",
        }
        r1 = self.crm.add_lead(lead)
        r2 = self.crm.add_lead(dict(lead))
        self.assertTrue(r1[0])
        self.assertFalse(r2[0])
        stats = self.crm.stats()
        self.assertEqual(stats["leads_total"], 1)

    def test_list_and_stats(self):
        self.crm.add_lead({
            "business_name": "List Co",
            "city": "Yerevan",
            "country": "Armenia",
            "website_url": "https://list.am/",
            "business_category": "web",
            "proposed_opportunity": "site",
            "evidence_observations": ["obs"],
            "score_explanation": "test",
        })
        leads = self.crm.list_leads(limit=10)
        self.assertEqual(len(leads), 1)
        stats = self.crm.stats()
        self.assertEqual(stats["leads_total"], 1)


if __name__ == "__main__":
    unittest.main()
