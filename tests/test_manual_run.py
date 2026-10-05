from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import patch

from collector.adapters.shopify_new_vinyl import ShopifyNewVinylAdapter
from collector.build_queue import source_domain
from collector.manual_run import load_queue, queue_digest, run
from collector.progress import next_index


class FakeTransport:
    calls = []

    def __init__(self, domain, limits):
        self.domain = domain
        self.calls.append(domain)

    def get(self, url):
        if self.domain == "10000hzrecords.com":
            raise OSError("offline")
        return json.dumps({"products": [{"handle": "test-record", "title": "Artist - New Vinyl",
                                         "product_type": "New Vinyl", "tags": [],
                                         "variants": [{"id": 1, "available": True, "price": "20.00",
                                                       "barcode": "123456789012"}]}]})


class ManualRunTests(unittest.TestCase):
    def setUp(self):
        FakeTransport.calls = []

    def test_bounded_run_continues_and_keeps_platforms_unproven(self):
        queue = [self.item(9, "1234gorecords.shop"), self.item(23, "14arecords.com"),
                 self.item(20, "10000hzrecords.com"),
                 self.item(7, "facebook.com", "SHARED_PLATFORM")]
        with patch.dict("os.environ", {}, clear=True):
            result = run(queue, 0, 4, transport_factory=FakeTransport)
        self.assertEqual([r["status"] for r in result["results"]],
                         ["LISTING_SAMPLE", "SOURCE_PROFILE_NEEDED", "SOURCE_BLOCKED", "SOURCE_REVIEW"])
        self.assertEqual(FakeTransport.calls, ["1234gorecords.shop", "10000hzrecords.com"])
        self.assertFalse(result["results"][0]["pagination_complete"])
        self.assertEqual(result["next_start_index"], 4)
        self.assertEqual(result["results"][-1]["reason"], "SHARED_PLATFORM")

    @staticmethod
    def item(row, domain, source_status="READY"):
        return {"row": row, "name": f"Shop {row}", "domain": domain, "source_status": source_status}

    def test_cursor_allows_append_only_growth(self):
        queue = [self.item(9, "1234gorecords.shop"), self.item(23, "14arecords.com")]
        state = {"schema_version": 1, "queue_sha256": queue_digest(queue),
                 "queue_size": len(queue), "next_start_index": 1}
        self.assertEqual(next_index(state, queue), 1)
        self.assertEqual(next_index(state, queue + [self.item(24, "example.com")]), 1)
        with self.assertRaisesRegex(ValueError, "prefix changed"):
            next_index(state, list(reversed(queue)))

    def test_workbook_queue_has_every_shop_row_and_preserves_first_domains(self):
        root = Path(__file__).parents[1]
        queue = load_queue(root / "collector/public-queue.json")
        bootstrap = json.loads((root / "collector/bootstrap-domains.json").read_text())
        self.assertEqual(len(queue), 3303)
        self.assertEqual(len({item["row"] for item in queue}), 3303)
        self.assertEqual([item["domain"] for item in queue[:23]], bootstrap)
        self.assertEqual({item["row"] for item in queue}, set(range(7, 3310)))

    def test_shared_and_missing_sources_are_not_fetch_candidates(self):
        self.assertEqual(source_domain(None), ("", "MISSING_SOURCE"))
        self.assertEqual(source_domain("https://m.facebook.com/shop"), ("m.facebook.com", "SHARED_PLATFORM"))
        self.assertEqual(source_domain("https://shop.example.com/vinyl"), ("shop.example.com", "READY"))

    def test_new_arrivals_and_vinyl_type_do_not_prove_new_condition(self):
        product = {"handle": "record", "title": "Artist - Album", "product_type": "Vinyl",
                   "tags": ["New Arrivals"], "variants": [{"id": 1, "available": True, "price": "20.00"}]}
        page = ShopifyNewVinylAdapter("example.com").parse_listing(
            json.dumps({"products": [product]}), source_url="https://example.com/products.json?limit=20&page=1",
            observed_at="2026-10-04T00:00:00Z")
        self.assertEqual(page.listings, ())
        self.assertEqual(page.exclusions[0]["signal"], "new_vinyl_not_proven")


if __name__ == "__main__":
    unittest.main()
