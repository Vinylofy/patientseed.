from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from collector.adapters.shopify_new_vinyl import ShopifyNewVinylAdapter
from collector.manual_run import run
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
        queue = ["1234gorecords.shop", "14arecords.com", "10000hzrecords.com"]
        with patch.dict("os.environ", {}, clear=True):
            result = run(queue, 0, 3, transport_factory=FakeTransport)
        self.assertEqual([r["status"] for r in result["results"]],
                         ["LISTING_SAMPLE", "SOURCE_PROFILE_NEEDED", "SOURCE_BLOCKED"])
        self.assertEqual(FakeTransport.calls, ["1234gorecords.shop", "10000hzrecords.com"])
        self.assertFalse(result["results"][0]["pagination_complete"])
        self.assertEqual(result["next_start_index"], 3)

    def test_cursor_resumes_and_queue_change_fails_closed(self):
        queue = ["1234gorecords.shop", "14arecords.com"]
        state = {"schema_version": 1, "queue_sha256": run(queue, 0, 1, transport_factory=FakeTransport)["queue_sha256"],
                 "next_start_index": 1}
        self.assertEqual(next_index(state, queue), 1)
        with self.assertRaisesRegex(ValueError, "queue changed"):
            next_index(state, list(reversed(queue)))

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
