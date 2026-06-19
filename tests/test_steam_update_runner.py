import os
import sys
import unittest
from unittest.mock import AsyncMock, patch

ROOT = os.path.dirname(os.path.dirname(__file__))
BACKEND = os.path.join(ROOT, "backend")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from steam_update import SteamUpdateOptions, SteamUpdateRunner


class FakeTrendEngine:
    def load_history(self, rows):
        self.rows = rows

    def recommendations(self, min_score=0):
        return [{"id": 2, "score": 75}, {"id": 3, "score": 55}]


class SteamUpdateRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_visible_scope_includes_newly_discovered_items_only(self):
        items = [
            {"id": 1, "market_hash_name": "visible"},
            {"id": 2, "market_hash_name": "hidden"},
            {"id": 3, "market_hash_name": "new"},
        ]
        runner = SteamUpdateRunner(trend_engine=FakeTrendEngine())

        with patch("steam_update.get_monitored_items", new=AsyncMock(return_value=items)):
            selected = await runner._select_update_items(
                None,
                SteamUpdateOptions(item_ids={1}),
                discovered_item_ids={3},
            )

        self.assertEqual([item["id"] for item in selected], [1, 3])

    async def test_score_scope_filters_existing_monitored_items(self):
        items = [
            {"id": 1, "market_hash_name": "low"},
            {"id": 2, "market_hash_name": "high"},
            {"id": 3, "market_hash_name": "mid"},
        ]
        runner = SteamUpdateRunner(trend_engine=FakeTrendEngine())

        with (
            patch("steam_update.get_monitored_items", new=AsyncMock(return_value=items)),
            patch("steam_update.get_steam_history", new=AsyncMock(return_value=[])),
        ):
            selected = await runner._select_update_items(
                None,
                SteamUpdateOptions(item_ids=None, min_score=60),
                discovered_item_ids={},
            )

        self.assertEqual([item["id"] for item in selected], [2])


if __name__ == "__main__":
    unittest.main()
