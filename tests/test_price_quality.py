import unittest

from collector.price_quality import assess


class PriceQualityTests(unittest.TestCase):
    @staticmethod
    def row(price, title="Album"):
        return {"price": price, "currency": "USD", "title": title,
                "artist": "Artist", "source_fragment": "product listing"}

    def test_shipping_identity_is_flagged(self):
        result = assess([self.row("4.99", "Shipping and handling")])
        self.assertEqual(result["status"], "review")
        self.assertIn("shipping_term_in_product_identity", result["flags"])

    def test_uniform_prices_are_flagged(self):
        result = assess([self.row("19.99", str(index)) for index in range(20)])
        self.assertEqual(result["status"], "review")
        self.assertIn("uniform_price_suspicious", result["flags"])

    def test_small_uniform_sample_is_not_flagged(self):
        result = assess([self.row("19.99", str(index)) for index in range(3)])
        self.assertEqual(result["status"], "pass")

    def test_varied_product_prices_pass(self):
        result = assess([self.row("19.99", "A"), self.row("24.99", "B"), self.row("29.99", "C")])
        self.assertEqual(result["status"], "pass")


if __name__ == "__main__":
    unittest.main()
