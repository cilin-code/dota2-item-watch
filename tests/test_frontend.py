from pathlib import Path
import re
import unittest


class FrontendBehaviorTests(unittest.TestCase):
    def test_update_fetch_uses_visible_item_ids(self):
        index_html = Path(__file__).resolve().parents[1] / "frontend" / "index.html"
        source = index_html.read_text(encoding="utf-8")

        fetch_calls = re.findall(r"new EventSource\(([^;]+)\);", source)
        fetch_calls = [call for call in fetch_calls if "/api/fetch?" in call]

        self.assertGreaterEqual(len(fetch_calls), 2)
        for call in fetch_calls:
            self.assertIn("min_score=0", call)
            self.assertIn("item_ids=", call)
            self.assertIn("discover=true", call)
            self.assertNotIn("_minScore", call)

        self.assertIn("getVisibleItems().map", source)
        self.assertIn("if (!_dataLoaded)", source)

    def test_update_done_text_uses_trade_points_label(self):
        index_html = Path(__file__).resolve().parents[1] / "frontend" / "index.html"
        source = index_html.read_text(encoding="utf-8")

        self.assertIn("成交点", source)
        self.assertNotIn("历史: \" + (data.results.history", source)

    def test_initial_items_load_is_paginated_then_background_fills(self):
        index_html = Path(__file__).resolve().parents[1] / "frontend" / "index.html"
        source = index_html.read_text(encoding="utf-8")

        self.assertIn('/api/items?min_score=0&limit=" + firstPage + "&offset=0', source)
        self.assertIn("loadRemainingItems(token, nextOffset", source)
        self.assertIn("mergeItems(batch)", source)

    def test_purchase_profit_percent_is_formatted_to_two_decimals(self):
        index_html = Path(__file__).resolve().parents[1] / "frontend" / "index.html"
        source = index_html.read_text(encoding="utf-8")

        self.assertIn("num(r.pnl_pct) + '%", source)
        self.assertIn("r.net_sell_price", source)

    def test_detail_periodic_panel_shows_cycle_and_intraday_signals(self):
        detail_html = Path(__file__).resolve().parents[1] / "frontend" / "detail.html"
        source = detail_html.read_text(encoding="utf-8")

        self.assertIn("波动间隔", source)
        self.assertIn("波峰周期", source)
        self.assertIn("买入时间", source)
        self.assertIn("p.intraday", source)


if __name__ == "__main__":
    unittest.main()
