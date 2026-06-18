import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(__file__))
BACKEND = os.path.join(ROOT, "backend")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from price_semantics import (
    QUOTE_SNAPSHOT,
    TRADE_SNAPSHOT,
    current_price_from_quote,
    is_quote_snapshot,
    is_trade_snapshot,
    normalize_snapshot_type,
)


class PriceSemanticsTests(unittest.TestCase):
    def test_missing_snapshot_type_is_legacy_trade(self):
        self.assertEqual(normalize_snapshot_type(None), TRADE_SNAPSHOT)
        self.assertTrue(is_trade_snapshot(None))
        self.assertFalse(is_quote_snapshot(None))

    def test_quote_price_is_the_only_current_price_source(self):
        self.assertEqual(current_price_from_quote({"latest_quote_price": "8.14", "sell_price": 7.89}), 8.14)
        self.assertIsNone(current_price_from_quote({"sell_price": 7.89}))
        self.assertIsNone(current_price_from_quote({"latest_quote_price": 0}))
        self.assertTrue(is_quote_snapshot(QUOTE_SNAPSHOT))


if __name__ == "__main__":
    unittest.main()
