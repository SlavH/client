"""Tests for duplicate detection across domains and name+location keys."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from client_acquisition.scripts.crm import CRM, make_lead_key, normalize_domain


class TestDeduplication(unittest.TestCase):
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

    def _base_lead(self, **overrides):
        lead = {
            "business_name": "Cafe",
            "city": "Yerevan",
            "country": "Armenia",
            "website_url": "https://www.cafe.am/",
            "business_category": "cafe",
            "proposed_opportunity": "site",
            "evidence_observations": ["obs"],
            "score_explanation": "test",
        }
        lead.update(overrides)
        return lead

    def test_same_domain_different_url_paths_duplicate(self):
        self.crm.add_lead(self._base_lead(website_url="https://www.cafe.am/"))
        r2 = self.crm.add_lead(self._base_lead(
            business_name="Cafe Renamed",
            website_url="https://cafe.am/menu?x=1#section",
        ))
        self.assertFalse(r2[0])
        self.assertIn("duplicate", r2[1])

    def test_same_domain_with_and_without_www_duplicate(self):
        self.crm.add_lead(self._base_lead(website_url="https://www.cafe.am/"))
        r2 = self.crm.add_lead(self._base_lead(
            business_name="Cafe",
            website_url="http://cafe.am",
        ))
        self.assertFalse(r2[0])

    def test_no_domain_name_location_key(self):
        self.crm.add_lead(self._base_lead(website_url=None,
                                          business_name="Gyumri Bakery",
                                          city="Gyumri",
                                          country="Armenia"))
        key = make_lead_key(None, "Gyumri Bakery", "Gyumri", "Armenia")
        self.assertEqual(key, "name:gyumri bakery|gyumri|armenia")
        r2 = self.crm.add_lead(self._base_lead(
            website_url=None,
            business_name="gyumri bakery",  # different case
            city="Gyumri",
            country="Armenia",
        ))
        self.assertFalse(r2[0])

    def test_different_businesses_not_duplicates(self):
        self.crm.add_lead(self._base_lead(business_name="Cafe A",
                                          website_url="https://cafe-a.am/"))
        r2 = self.crm.add_lead(self._base_lead(business_name="Cafe B",
                                               website_url="https://cafe-b.am/"))
        self.assertTrue(r2[0])
        stats = self.crm.stats()
        self.assertEqual(stats["leads_total"], 2)

    def test_duplicate_records_why_skipped(self):
        self.crm.add_lead(self._base_lead())
        r2 = self.crm.add_lead(self._base_lead())
        self.assertFalse(r2[0])
        self.assertTrue("duplicate" in r2[1] or "already exists" in r2[1])


if __name__ == "__main__":
    unittest.main()
