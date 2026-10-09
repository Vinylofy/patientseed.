from __future__ import annotations

import json
import unittest

from collector.adapters.rockinoutrecords import RockinOutRecordsAdapter


LISTING = '''<link rel="next" href="https://rockinoutrecords.nl/product-category/vinyl-lp-nieuw/page/2/">
<ul class="products"><li class="product type-product instock"><a class="ast-loop-product__link" href="https://rockinoutrecords.nl/artikelen/test-lp/"><h2 class="woocommerce-loop-product__title">Artist | Test LP</h2></a><span class="price"><span class="woocommerce-Price-amount"><bdi><span>€</span>&nbsp;24,95</bdi></span></span><span class="ast-woo-product-category">Vinyl Album (LP) Nieuw</span></li></ul>'''
DETAIL = '<script type="application/ld+json">' + json.dumps({"@type": "Product", "gtin": "5060516098880"}) + '</script>'


class RockinOutRecordsTests(unittest.TestCase):
    def test_listing_pagination_and_new_vinyl(self):
        adapter = RockinOutRecordsAdapter()
        page = adapter.parse_listing(LISTING, source_url="https://rockinoutrecords.nl/product-category/vinyl-lp-nieuw/", observed_at="2026-10-09T00:00:00Z")
        self.assertEqual(len(page.listings), 1)
        self.assertEqual(page.next_url, "https://rockinoutrecords.nl/product-category/vinyl-lp-nieuw/page/2/")
        self.assertEqual(page.listings[0]["currency"], "EUR")

    def test_ean_is_read_from_detail_jsonld(self):
        adapter = RockinOutRecordsAdapter()
        listing = adapter.parse_listing(LISTING, source_url="https://rockinoutrecords.nl/product-category/vinyl-lp-nieuw/", observed_at="now").listings[0]
        detail = adapter.parse_detail(DETAIL, source_url=listing["url"], listing=listing)
        self.assertEqual(detail["identifier_raw"], "5060516098880")
        self.assertIsNone(listing["identifier_raw"])


if __name__ == "__main__":
    unittest.main()
