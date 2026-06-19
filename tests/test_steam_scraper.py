import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(__file__))
BACKEND = os.path.join(ROOT, "backend")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from scrapers.steam import SteamScraper


class SteamScraperTests(unittest.TestCase):
    def test_extract_orderbook_from_escaped_listing_payload(self):
        html = r'...\"cSellOrders\":928,\"rgCompactSellOrders\":[3700,7,3800,334,3900,70]...'

        orderbook = SteamScraper._extract_orderbook(html, rate=0.0465)

        self.assertIsNotNone(orderbook)
        self.assertEqual(orderbook["source"], "steam_listing")
        self.assertEqual(orderbook["total_sell_orders"], 928)
        self.assertEqual(orderbook["levels"][0], {
            "price": 1.72,
            "quantity": 7,
            "price_jpy": 37.0,
            "price_minor": 3700,
        })
        self.assertEqual(orderbook["levels"][1]["quantity"], 334)


if __name__ == "__main__":
    unittest.main()
