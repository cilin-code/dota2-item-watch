import asyncio
import json
import os
import sys
from datetime import datetime, timedelta
import unittest

ROOT = os.path.dirname(os.path.dirname(__file__))
BACKEND = os.path.join(ROOT, "backend")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from engine import TrendEngine


def make_rows(prices, *, item_id=1, volume=20, start="2026-01-01 00:00:00"):
    base = datetime.strptime(start, "%Y-%m-%d %H:%M:%S")
    rows = []
    for index, price in enumerate(prices):
        rows.append({
            "id": item_id,
            "market_hash_name": "Sample Item",
            "name_cn": "样例饰品",
            "icon_url": "",
            "rarity": "",
            "sell_price": price,
            "buy_price": price,
            "volume_24h": volume,
            "updated_at": (base + timedelta(days=index)).strftime("%Y-%m-%d %H:%M:%S"),
        })
    return rows


class TrendEngineTests(unittest.TestCase):
    def test_tax_helpers_cover_nominal_and_minimum_fee_prices(self):
        engine = TrendEngine

        self.assertEqual(round(engine.breakeven_multiplier(2.0), 6), round(1 / 0.87, 6))
        self.assertEqual(engine.effective_tax_rate(2.0), 0.13)
        self.assertEqual(engine.breakeven_multiplier(0.2), 999.0)
        self.assertEqual(engine.effective_tax_rate(1.04), 0.2)

    def test_engine_rejects_zero_recent_volume(self):
        engine = TrendEngine()
        engine.load_history(make_rows([1.0, 1.01, 1.0, 1.02, 1.01, 1.0], volume=0))

        item = engine.recommendations(min_score=0)[0]

        self.assertIs(item["analysis"]["recommend"], False)
        self.assertEqual(item["analysis"]["reject_reasons"], ["无近期成交量"])
        self.assertLess(item["score"], 55)

    def test_engine_produces_complete_analysis_for_stable_liquid_item(self):
        engine = TrendEngine()
        prices = [1.01, 1.02, 1.03, 1.02, 1.01, 1.02, 1.03, 1.02, 1.01, 1.02, 1.03, 1.02, 1.01, 1.02, 1.01, 1.01]
        rows = make_rows(prices, volume=25)
        rows[-1]["latest_quote_price"] = 1.01
        engine.load_history(rows)

        item = engine.recommendations(min_score=0)[0]

        self.assertEqual(item["current_price"], 1.01)
        self.assertEqual(item["volume_24h"], 25)
        self.assertEqual(item["analysis"]["volume_class"], "LIQUID")
        self.assertEqual(item["analysis"]["confidence"], "HIGH")
        self.assertTrue({"3", "7", "15"}.issubset(item["trend"]))

    def test_engine_current_price_is_unknown_without_quote(self):
        engine = TrendEngine()
        rows = make_rows([1.0, 1.01, 1.0, 1.02, 1.01, 1.0], volume=10)
        engine.load_history(rows)

        item = engine.recommendations(min_score=0)[0]

        self.assertIsNone(item["current_price"])

    def test_engine_uses_latest_quote_as_current_price(self):
        engine = TrendEngine()
        prices = [1.0, 1.01, 1.0, 1.02, 1.01, 1.0]
        rows = make_rows(prices, volume=10)
        rows[-1]["latest_quote_price"] = 1.25
        engine.load_history(rows)

        item = engine.recommendations(min_score=0)[0]

        self.assertEqual(item["current_price"], 1.25)

    def test_engine_prefers_real_orderbook_for_pressure(self):
        engine = TrendEngine()
        prices = [1.01, 1.02, 1.03, 1.02, 1.01, 1.02, 1.03, 1.02, 1.01, 1.02, 1.03, 1.02, 1.01, 1.02, 1.01, 1.01]
        rows = make_rows(prices, volume=50)
        rows[-1]["orderbook_json"] = json.dumps({
            "levels": [
                {"price": 1.02, "quantity": 1},
                {"price": 1.03, "quantity": 1},
                {"price": 1.04, "quantity": 1},
                {"price": 1.05, "quantity": 1},
                {"price": 1.06, "quantity": 1},
            ]
        })
        engine.load_history(rows)

        item = engine.recommendations(min_score=0)[0]

        self.assertEqual(item["analysis"]["pressure_source"], "real")
        self.assertEqual(item["analysis"]["orderbook_count"], 5)
        self.assertLess(item["analysis"]["pressure"], 0.1)

    def test_engine_exposes_structured_reasons_and_price_anomalies(self):
        engine = TrendEngine()
        prices = [1.0, 1.01, 1.02, 1.01, 1.0, 1.01, 1.02, 6.5, 1.01, 1.0, 1.01, 1.02, 1.01, 1.0, 1.01, 1.0]
        rows = make_rows(prices, volume=30)
        rows[-1]["latest_quote_price"] = 1.0
        engine.load_history(rows)

        item = engine.recommendations(min_score=0)[0]

        self.assertGreater(item["analysis"]["outlier_count"], 0)
        self.assertTrue(item["analysis"]["anomaly_detected"])
        self.assertTrue(item["analysis"]["reason_details"])
        self.assertTrue(all("text" in part and "level" in part for part in item["analysis"]["reason_details"]))

    def test_low_price_reason_includes_historical_percentile(self):
        engine = TrendEngine()
        prices = [1.40, 1.38, 1.36, 1.34, 1.32, 1.30, 1.28, 1.26, 1.24, 1.22, 1.20, 1.18, 1.16, 1.14, 1.12, 1.10]
        rows = make_rows(prices, volume=30)
        rows[-1]["latest_quote_price"] = 1.10
        engine.load_history(rows)

        item = engine.recommendations(min_score=0)[0]

        self.assertRegex(item["reason"], r"历史低位 \d+%")

    def test_recommendation_grade_thresholds_match_current_scale(self):
        engine = TrendEngine()

        self.assertEqual(engine._score_simple(market_price=1.0, trend={}, volume_24h=0, reject=True)[1], "E")
        self.assertEqual(engine._score_simple(market_price=1.0, trend={}, volume_24h=20)[1], "D")
        self.assertEqual(engine._score_simple(market_price=1.0, trend={}, volume_24h=50, status="STABLE")[1], "C")
        self.assertEqual(engine._score_simple(market_price=1.0, trend={}, volume_24h=50, status="STABLE", price_percentile=0.3, recent_percentile=0.1)[1], "B")
        self.assertEqual(engine._score_simple(market_price=1.0, trend={}, volume_24h=50, status="STABLE", price_percentile=0.1, recent_percentile=0.1)[1], "A")

    def test_backtest_returns_signal_summary(self):
        engine = TrendEngine()
        prices = [1.20, 1.18, 1.16, 1.14, 1.12, 1.10, 1.08, 1.06, 1.05, 1.04, 1.05, 1.07, 1.09, 1.12, 1.15, 1.18, 1.20, 1.22]
        rows = make_rows(prices, volume=60)

        result = engine.backtest(rows, horizon_days=3, min_score=0)

        self.assertGreater(result["signals"], 0)
        self.assertIn("win_rate", result)
        self.assertIn("samples", result)
        self.assertTrue(result["samples"])


if __name__ == "__main__":
    unittest.main()
