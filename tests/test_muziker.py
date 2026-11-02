from __future__ import annotations

import unittest

from collector.adapters.muziker import MuzikerAdapter


LISTING = '''<a class="load-next-products" href="https://www.muziker.nl/vinyl-lps?page=2">Meer</a>
<div class="product-tile" data-product-code="349912" data-item-name="Black Sabbath Paranoid (Vinyl LP)">
 <a class="link-overlay" href="/black-sabbath-paranoid-vinyl-lp"><h4 class="product-tile-header">Black Sabbath - Paranoid (Vinyl LP)</h4>
 <p class="product-tile-sub-header">LP</p><div class="tile-price"><div class="price">€ 26,99</div></div>
 <div title="Op voorraad" class="stock-status green">Op voorraad</div></a></div>'''


class MuzikerTests(unittest.TestCase):
    def test_listing_extracts_artist_title_price_and_pagination(self):
        page = MuzikerAdapter().parse_listing(LISTING, source_url="https://www.muziker.nl/vinyl-lps", observed_at="now")
        self.assertEqual(len(page.listings), 1)
        row = page.listings[0]
        self.assertEqual((row["artist"], row["title"], row["price"], row["currency"]),
                         ("Black Sabbath", "Paranoid (Vinyl LP)", "26.99", "EUR"))
        self.assertIsNone(row["identifier_raw"])
        self.assertEqual(page.next_url, "https://www.muziker.nl/vinyl-lps?page=2")

    def test_detail_keeps_artist_title_and_no_ean(self):
        listing = MuzikerAdapter().parse_listing(LISTING, source_url="https://www.muziker.nl/vinyl-lps", observed_at="now").listings[0]
        self.assertEqual(MuzikerAdapter().parse_detail("<html></html>", source_url=listing["url"], listing=listing),
                         {"artist": "Black Sabbath", "title": "Paranoid (Vinyl LP)"})

    def test_wrong_detail_is_rejected(self):
        listing = MuzikerAdapter().parse_listing(LISTING, source_url="https://www.muziker.nl/vinyl-lps", observed_at="now").listings[0]
        with self.assertRaises(ValueError):
            MuzikerAdapter().parse_detail("", source_url="https://www.muziker.nl/other", listing=listing)


if __name__ == "__main__":
    unittest.main()
