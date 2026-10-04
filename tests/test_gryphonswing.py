import json
import unittest

from collector.adapters.gryphonswing import FIRST_LISTING, GryphonsWingAdapter
from collector.contracts import CollectionBlocked, merge_detail


class AdapterTests(unittest.TestCase):
    def product(self):
        return {"handle": "fixture-album-lp", "title": "Artist | Album LP", "product_type": "Vinyl", "tags": ["New"], "body_html": "",
                "variants": [{"id": 123, "price": "19.95", "compare_at_price": "24.95", "available": True, "barcode": "602577427664"}]}

    def parse(self, product):
        return GryphonsWingAdapter().parse_listing(json.dumps({"products": [product]}), source_url=FIRST_LISTING, observed_at="2026-10-04T12:00:00Z")

    def test_sale_variant_listing_and_raw_barcode(self):
        page = self.parse(self.product())
        row = page.listings[0]
        self.assertEqual(row["price"], "19.95")
        self.assertEqual(row["base_price"], "24.95")
        self.assertEqual(row["identifier_raw"], "602577427664")
        self.assertIn("variant=123", row["url"])
        self.assertIn("page=2", page.next_url)
        self.assertEqual(merge_detail(row, {"price": "0.01", "availability": "out_of_stock"}), row)

    def test_used_unknown_and_cd_are_not_collected(self):
        for changes in ({"tags": ["Used"]}, {"tags": []}, {"product_type": "CD"}, {"body_html": "Pre-owned VG+ vinyl"}):
            with self.subTest(changes=changes):
                page = self.parse({**self.product(), **changes})
                self.assertFalse(page.listings)
                self.assertEqual(set(page.exclusions[0]), {"url", "signal", "at"})

    def test_barcode_never_derived_from_sku_or_handle(self):
        product = self.product()
        product["variants"][0].pop("barcode")
        product["variants"][0]["sku"] = "602577427664"
        row = self.parse(product).listings[0]
        self.assertIsNone(row["identifier_raw"])
        self.assertEqual(row["identifier_type"], "unknown")

    def test_missing_availability_requires_review(self):
        product = self.product()
        product["variants"][0].pop("available")
        self.assertFalse(self.parse(product).listings)

    def test_live_condition_field_and_new_arrival_are_distinct(self):
        product = {**self.product(), "product_type": "New", "tags": ["New Arrival"]}
        self.assertEqual(len(self.parse(product).listings), 1)
        for condition in ("Preowned", "Unknown"):
            with self.subTest(condition=condition):
                self.assertFalse(self.parse({**product, "product_type": condition}).listings)

    def test_new_condition_does_not_admit_other_formats(self):
        for title in ("Artist | Album CD", "Artist | Album Cassette", "Phono Preamp"):
            with self.subTest(title=title):
                self.assertFalse(self.parse({**self.product(), "title": title, "product_type": "New", "tags": ["New Arrival"]}).listings)

    def test_empty_feed_has_explicit_stop(self):
        page = GryphonsWingAdapter().parse_listing('{"products":[]}', source_url=FIRST_LISTING, observed_at="2026-10-04T12:00:00Z")
        self.assertIsNone(page.next_url)

    def test_detail_identifier_requires_exact_product_and_variant(self):
        row = self.parse(self.product()).listings[0]
        url = row["url"].split("?")[0]
        node = {"@type": "Product", "url": url, "gtin": "602577427664", "offers": {"url": row["url"], "price": "0.01"}}
        def html(data):
            return '<script type="application/ld+json">' + json.dumps(data) + '</script>'
        adapter = GryphonsWingAdapter()
        detail = adapter.parse_detail(html(node), source_url=url, listing=row)
        self.assertEqual(detail["identifier_raw"], "602577427664")
        self.assertEqual(merge_detail(row, detail)["price"], "19.95")
        self.assertEqual(adapter.parse_detail(html({**node, "offers": {"url": url + "?variant=999"}}), source_url=url, listing=row), {})
        self.assertEqual(adapter.parse_detail(html({**node, "gtin13": "0602577427664"}), source_url=url, listing=row), {})

    def test_schema_change_is_not_silently_accepted(self):
        with self.assertRaises(CollectionBlocked):
            GryphonsWingAdapter().parse_listing('{"items":[]}', source_url=FIRST_LISTING, observed_at="2026-10-04T12:00:00Z")
