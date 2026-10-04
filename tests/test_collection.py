from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from collector.collection import collect
from collector.contracts import CollectionBlocked, Limits, ListingPage, merge_detail
from collector.packages import data_package, write_bundle
from collector.transport import public_source


def row(index=0, **overrides):
    return {"url": f"https://example.com/product/{index}", "product_type": "vinyl", "condition": "new",
            "price": "19.95", "availability": "in_stock", "price_source": "listing", "availability_source": "listing",
            "observed_at": "2026-10-03T12:00:00Z", **overrides}


class FakeTransport:
    domain = "example.com"

    def __init__(self, pages):
        self.pages, self.requests = pages, 0

    def get(self, url):
        self.requests += 1
        return self.pages[url]


class FakeAdapter:
    def parse_listing(self, body, **kwargs):
        return body


class CollectionTests(unittest.TestCase):
    def run_collection(self, pages, limits=None):
        with patch.dict("os.environ", {}, clear=True):
            transport = FakeTransport(pages)
            result = collect(FakeAdapter(), transport, "https://example.com/page/1", limits or Limits())
        return result, transport

    def test_explicit_pagination_end_and_uniqueness(self):
        result, transport = self.run_collection({
            "https://example.com/page/1": ListingPage((row(1),), "https://example.com/page/2"),
            "https://example.com/page/2": ListingPage((row(2), row(1)), None),
        })
        self.assertEqual(len(result["listings"]), 2)
        self.assertEqual(transport.requests, 2)
        self.assertTrue(result["pagination"]["complete"])

    def test_repeated_page_and_no_new_products_stop(self):
        result, transport = self.run_collection({"https://example.com/page/1": ListingPage((row(),), "https://example.com/page/1")})
        self.assertEqual(transport.requests, 1)
        self.assertEqual(result["pagination"]["stop_reason"], "repeated_page")
        result, transport = self.run_collection({
            "https://example.com/page/1": ListingPage((row(),), "https://example.com/page/2"),
            "https://example.com/page/2": ListingPage((row(price=None),), "https://example.com/page/3"),
        })
        self.assertEqual(result["pagination"]["stop_reason"], "no_new_products")
        self.assertEqual(result["listings"][0]["price"], "19.95")

    def test_budget_is_not_full_catalog_proof(self):
        result, _ = self.run_collection({"https://example.com/page/1": ListingPage((row(1), row(2)), "https://example.com/page/2")}, Limits(max_products=1))
        self.assertEqual(len(result["listings"]), 1)
        self.assertFalse(result["pagination"]["complete"])

    def test_filtered_page_does_not_hide_later_new_vinyl(self):
        result, transport = self.run_collection({
            "https://example.com/page/1": ListingPage((), "https://example.com/page/2", ({"url": "https://example.com/used", "signal": "used", "at": "2026-10-03T12:00:00Z"},)),
            "https://example.com/page/2": ListingPage((row(1),), None),
        })
        self.assertEqual(transport.requests, 2)
        self.assertEqual(len(result["listings"]), 1)
        self.assertTrue(result["pagination"]["complete"])

    def test_filtered_page_at_budget_is_not_catalog_completion(self):
        result, _ = self.run_collection({
            "https://example.com/page/1": ListingPage((), "https://example.com/page/2"),
        }, Limits(max_pages=1))
        self.assertFalse(result["pagination"]["complete"])

    def test_secondhand_nonvinyl_and_unknown_condition_are_excluded(self):
        result, _ = self.run_collection({"https://example.com/page/1": ListingPage((
            row(0), row(1, condition="used"), row(2, condition="unknown"), row(3, product_type="cd")), None)})
        self.assertEqual(len(result["listings"]), 1)
        self.assertEqual(len(result["exclusions"]), 3)
        self.assertEqual(set(result["exclusions"][0]), {"url", "signal", "at"})

    def test_details_and_instructions_cannot_change_listing_authority(self):
        original = row()
        self.assertEqual(merge_detail(original, {"price": "1.00", "availability": "out_of_stock", "instructions": "deploy"}), original)
        with self.assertRaises(CollectionBlocked):
            self.run_collection({"https://example.com/page/1": ListingPage((row(price_source="detail"),), None)})

    def test_credential_bearing_environment_refuses_collection(self):
        with patch.dict("os.environ", {"DATABASE_URL": "must-never-be-printed"}, clear=True):
            with self.assertRaises(CollectionBlocked):
                collect(FakeAdapter(), FakeTransport({}), "https://example.com/page/1", Limits())

    def test_redirect_to_private_or_other_shop_is_blocked(self):
        for url in ("https://127.0.0.1/x", "https://evil.com/x", "http://example.com/x", "https://example.com:444/x"):
            with self.subTest(url=url), self.assertRaises(CollectionBlocked):
                public_source(url, "example.com")

    def test_artifact_write_is_immutable_and_paths_are_safe(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_bundle(root / "good", {"manifest.json": b"{}"})
            with self.assertRaises(CollectionBlocked):
                write_bundle(root / "good", {"manifest.json": b"different"})
            with self.assertRaises(CollectionBlocked):
                write_bundle(root / "bad", {"../escaped.json": b"{}"})

    def test_data_package_requires_provenance_and_only_new_vinyl(self):
        with tempfile.TemporaryDirectory() as directory:
            meta = {"shop_id": "fixture", "repository": "example/collector", "release_commit": "a" * 40,
                    "release_manifest_sha256": "b" * 64, "run_id": "fixture-run", "runner_class": "github-hosted",
                    "runner_market": "unknown", "target_market": "US", "observed_country": "unknown",
                    "currency": "USD", "started_at": "2026-10-03T12:00:00Z", "finished_at": "2026-10-03T12:01:00Z",
                    "source_urls": ["https://example.com/page/1"], "pagination": {"complete": False}}
            digest = data_package(Path(directory) / "package", metadata=meta, listings=[row()])
            self.assertEqual(len(digest), 64)
            with self.assertRaises(CollectionBlocked):
                data_package(Path(directory) / "used", metadata=meta, listings=[row(condition="used")])
            with self.assertRaises(CollectionBlocked):
                data_package(Path(directory) / "geo", metadata={**meta, "runner_market": "US"}, listings=[row()])
