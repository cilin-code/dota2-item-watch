import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(__file__))
BACKEND = os.path.join(ROOT, "backend")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from main import _validate_quote_price


class QuoteValidationTests(unittest.TestCase):
    def test_keeps_priceoverview_when_lower_than_orderbook(self):
        price, status = _validate_quote_price(
            {"buy_price": 7.89, "sell_price": 7.89, "volume_24h": 10},
            {"levels": [{"price": 8.14, "quantity": 2}]},
        )

        self.assertEqual(price["sell_price"], 7.89)
        self.assertEqual(price["buy_price"], 7.89)
        self.assertEqual(price["quote_source"], "priceoverview")
        self.assertEqual(price["orderbook_lowest"], 8.14)
        self.assertIn("priceoverview_primary_low", status)

    def test_keeps_priceoverview_when_higher_than_orderbook(self):
        price, status = _validate_quote_price(
            {"buy_price": 8.50, "sell_price": 8.50, "volume_24h": 10},
            {"levels": [{"price": 8.14, "quantity": 2}]},
        )

        self.assertEqual(price["sell_price"], 8.50)
        self.assertEqual(price["buy_price"], 8.50)
        self.assertEqual(price["quote_source"], "priceoverview")
        self.assertEqual(price["orderbook_lowest"], 8.14)
        self.assertIn("priceoverview_primary_high", status)

    def test_keeps_quote_close_to_orderbook(self):
        price, status = _validate_quote_price(
            {"buy_price": 8.12, "sell_price": 8.12, "volume_24h": 10},
            {"levels": [{"price": 8.14, "quantity": 2}]},
        )

        self.assertEqual(price["sell_price"], 8.12)
        self.assertEqual(price["quote_source"], "priceoverview")
        self.assertEqual(status, "ok")


if __name__ == "__main__":
    unittest.main()
