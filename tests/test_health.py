from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from collector.health import update


class HealthTests(unittest.TestCase):
    def test_one_failure_is_incident_and_two_queue_repair(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profiles = root / "profiles"
            profiles.mkdir()
            (profiles / "shop.json").write_text(json.dumps({"domain": "shop.example", "listing_sample": 2}))
            state = root / "health.json"
            result = root / "result.json"
            payload = {"schema_version": 1, "mode": "price", "profiles": [{
                "profile": "shop.json", "status": "success", "records": 0,
                "truncated": False, "errors": [], "detail_errors": 0}]}
            result.write_text(json.dumps(payload))
            self.assertEqual(update(result, state, profiles)["repair_queue"], [])
            updated = update(result, state, profiles)
            self.assertEqual(updated["modes"]["price"]["shop.example"]["status"], "REPAIR_REQUIRED")
            self.assertEqual(updated["repair_queue"], [{"mode": "price", "domain": "shop.example"}])

    def test_good_result_resets_consecutive_failures(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profiles = root / "profiles"
            profiles.mkdir()
            (profiles / "shop.json").write_text(json.dumps({"domain": "shop.example", "listing_sample": 2}))
            state = root / "health.json"
            bad = root / "bad.json"
            good = root / "good.json"
            bad.write_text(json.dumps({"schema_version": 1, "mode": "price", "profiles": [{
                "profile": "shop.json", "status": "failure", "records": 0,
                "truncated": False, "errors": [{"reason": "HTTP_429"}], "detail_errors": 0}]}))
            good.write_text(json.dumps({"schema_version": 1, "mode": "price", "profiles": [{
                "profile": "shop.json", "status": "success", "records": 2,
                "truncated": False, "errors": [], "detail_errors": 0}]}))
            update(bad, state, profiles)
            updated = update(good, state, profiles)
            record = updated["modes"]["price"]["shop.example"]
            self.assertEqual(record["status"], "ACTIVE")
            self.assertEqual(record["consecutive_failures"], 0)


if __name__ == "__main__":
    unittest.main()
