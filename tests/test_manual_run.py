from __future__ import annotations

import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from collector.adapters.shopify_new_vinyl import ShopifyNewVinylAdapter
from collector.adapters.woocommerce_new_vinyl import WooCommerceNewVinylAdapter
from collector.build_queue import source_domain
from collector.manual_run import load_queue, queue_digest, run
from collector.progress import next_index, pack_state, publish, unpack_state
from collector.recon import platform_hint, valid_gtin
from collector.status import render


class FakeTransport:
    calls = []

    def __init__(self, domain, limits):
        self.domain = domain
        self.calls.append(domain)

    def get(self, url):
        self.calls.append(url)
        if self.domain == "10000hzrecords.com" and url.endswith("/"):
            raise OSError("offline")
        if self.domain == "14arecords.com":
            return "<html>woocommerce</html>" if url.endswith("/") else json.dumps([{"id": 1, "name": "Album"}])
        if url.endswith("/"):
            return "<html><script src='https://cdn.shopify.com/shop.js'></script></html>"
        if "/products/test-record" in url:
            return '<script type="application/ld+json">{"@type":"Product","gtin12":"012345678905"}</script>'
        return json.dumps({"products": [{"handle": "test-record", "title": "Artist - New Vinyl",
                                         "product_type": "New Vinyl", "tags": [],
                                         "variants": [{"id": 1, "available": True, "price": "20.00",
                                                       "barcode": "012345678905"}]}]})


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
                         ["LISTING_SAMPLE", "CATALOG_ROUTE_VERIFIED", "SOURCE_BLOCKED", "SOURCE_REVIEW"])
        self.assertEqual({call for call in FakeTransport.calls if not call.startswith("https://")},
                         {"1234gorecords.shop", "14arecords.com", "10000hzrecords.com"})
        self.assertFalse(result["results"][0]["pagination_complete"])
        self.assertEqual(result["results"][0]["detail_checked"], 1)
        self.assertEqual(result["results"][0]["detail_gtin_valid"], 1)
        self.assertEqual(result["next_start_index"], 4)
        self.assertEqual(result["results"][-1]["reason"], "SHARED_PLATFORM")

    def test_gtin_checksum_fails_closed(self):
        self.assertTrue(valid_gtin("012345678905"))
        self.assertFalse(valid_gtin("012345678906"))
        self.assertFalse(valid_gtin("123-456-789"))

    def test_route_hints_do_not_claim_an_adapter(self):
        self.assertEqual(platform_hint("<script src='https://static1.squarespace.com/x'>"), "squarespace")
        self.assertEqual(platform_hint("<html>Records for sale</html>"), "unknown")

    def test_woocommerce_requires_explicit_new_vinyl_and_currency(self):
        adapter = WooCommerceNewVinylAdapter("example.com")
        product = {"id": 7, "name": "Artist - Album", "permalink": "https://example.com/product/album",
                   "is_in_stock": True, "prices": {"price": "1995", "currency_code": "USD",
                                                  "currency_minor_unit": 2},
                   "attributes": [{"name": "Condition", "terms": [{"name": "New"}]},
                                  {"name": "Format", "terms": [{"name": "Vinyl"}]}]}
        route = "https://example.com/wp-json/wc/store/v1/products?per_page=20&page=1"
        page = adapter.parse_listing(json.dumps([product]), source_url=route, observed_at="2026-10-05T00:00:00Z")
        self.assertEqual(page.listings[0]["price"], "19.95")
        self.assertEqual(page.listings[0]["availability"], "in_stock")
        without_condition = {**product, "attributes": product["attributes"][1:]}
        rejected = adapter.parse_listing(json.dumps([without_condition]), source_url=route,
                                         observed_at="2026-10-05T00:00:00Z")
        self.assertEqual(rejected.listings, ())
        detail = adapter.parse_detail(
            '<script type="application/ld+json">{"@type":"Product","gtin12":"012345678905"}</script>',
            source_url=product["permalink"], listing=page.listings[0])
        self.assertEqual(detail["identifier_raw"], "012345678905")

    def test_published_progress_renders_all_rows_with_open_work(self):
        queue = [self.item(9, "1234gorecords.shop"), self.item(23, "14arecords.com")]
        with patch.dict("os.environ", {}, clear=True):
            result = run(queue, 0, 1, transport_factory=FakeTransport)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            queue_file, result_file = root / "queue.json", root / "result.json"
            queue_file.write_text(json.dumps(queue))
            result_file.write_text(json.dumps(result))
            with (patch("collector.progress.read_remote", return_value=(None, None)),
                  patch("collector.progress.request") as send,
                  patch.dict("os.environ", {"GITHUB_SHA": "a" * 40, "GITHUB_RUN_ID": "42"})):
                publish(queue_file, result_file)
            self.assertEqual(send.call_count, 2)
            state = unpack_state(json.loads(base64.b64decode(send.call_args.args[2]["content"])))
            self.assertEqual(state["next_start_index"], 1)
            self.assertEqual(state["history"][0]["batch"], 1)
            self.assertEqual(unpack_state(pack_state(state))["history"], state["history"])
            document = render(queue, state)
            self.assertIn("Behandeld voor broncontrole: 1", document)
            self.assertIn("| 1 |  | 23 |", document)

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
