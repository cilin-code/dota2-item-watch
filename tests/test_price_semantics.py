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
    net_steam_sale_price,
    orderbook_lowest_price,
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

    def test_orderbook_lowest_price_uses_valid_positive_levels(self):
        self.assertEqual(orderbook_lowest_price({
            "levels": [
                {"price": "bad", "quantity": 5},
                {"price": 0, "quantity": 5},
                {"price": 8.14, "quantity": 2},
                {"price": 8.10, "quantity": 1},
            ]
        }), 8.10)

    def test_net_steam_sale_price_applies_tax_rules(self):
        self.assertEqual(net_steam_sale_price(2.0), 1.74)
        self.assertEqual(net_steam_sale_price(1.0), 0.79)
        self.assertIsNone(net_steam_sale_price(None))


if __name__ == "__main__":
    unittest.main()
