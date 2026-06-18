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
        return [{"id": 1, "score": 10}, {"id": 2, "score": 75}, {"id": 3, "score": 55}, {"id": 4, "score": 8}]


class SteamUpdateRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_visible_scope_includes_hot_items(self):
        items = [
            {"id": 1, "market_hash_name": "visible"},
            {"id": 2, "market_hash_name": "hidden"},
            {"id": 3, "market_hash_name": "new"},
        ]
        runner = SteamUpdateRunner(trend_engine=FakeTrendEngine())

        with patch("steam_update.get_monitored_items", new=AsyncMock(return_value=items)):
            selected, stats = await runner._select_update_items(
                None,
                SteamUpdateOptions(item_ids={1}),
                hot_item_ids={3},
            )

        self.assertEqual([item["id"] for item in selected], [1, 3])
        self.assertEqual(stats["skipped"], 0)

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
            patch("steam_update.get_update_protected_item_ids", new=AsyncMock(return_value=set())),
            patch("steam_update.update_item_update_policy", new=AsyncMock()),
        ):
            selected, stats = await runner._select_update_items(
                None,
                SteamUpdateOptions(item_ids=None, min_score=60),
                hot_item_ids=set(),
            )

        self.assertEqual([item["id"] for item in selected], [2])
        self.assertEqual(stats["skipped"], 0)

    async def test_low_score_items_are_cooled_down_but_hot_items_bypass(self):
        items = [
            {"id": 1, "market_hash_name": "low", "favorite": 0, "update_after": "2999-01-01 00:00:00"},
            {"id": 2, "market_hash_name": "high", "favorite": 0, "update_after": None},
            {"id": 4, "market_hash_name": "hot-low", "favorite": 0, "update_after": "2999-01-01 00:00:00"},
        ]
        runner = SteamUpdateRunner(trend_engine=FakeTrendEngine())

        with (
            patch("steam_update.get_monitored_items", new=AsyncMock(return_value=items)),
            patch("steam_update.get_steam_history", new=AsyncMock(return_value=[])),
            patch("steam_update.get_update_protected_item_ids", new=AsyncMock(return_value=set())),
            patch("steam_update.update_item_update_policy", new=AsyncMock()),
        ):
            selected, stats = await runner._select_update_items(
                None,
                SteamUpdateOptions(item_ids=None, min_score=0),
                hot_item_ids={4},
            )

        self.assertEqual([item["id"] for item in selected], [2, 4])
        self.assertEqual(stats["skipped"], 1)
        self.assertEqual(stats["hot_bypass"], 1)

    async def test_hot_discovery_loads_all_items_beyond_batch_limit(self):
        items = [
            {"id": 5, "market_hash_name": "hot-outside-limit", "favorite": 0, "update_after": None},
        ]
        runner = SteamUpdateRunner(trend_engine=FakeTrendEngine())
        mocked_get_items = AsyncMock(return_value=items)

        with (
            patch("steam_update.get_monitored_items", new=mocked_get_items),
            patch("steam_update.get_steam_history", new=AsyncMock(return_value=[])),
            patch("steam_update.get_update_protected_item_ids", new=AsyncMock(return_value=set())),
            patch("steam_update.update_item_update_policy", new=AsyncMock()),
        ):
            selected, stats = await runner._select_update_items(
                None,
                SteamUpdateOptions(item_ids=None, min_score=0, limit=1),
                hot_item_ids={5},
            )

        self.assertEqual(mocked_get_items.await_args.kwargs["limit"], None)
        self.assertEqual([item["id"] for item in selected], [5])
        self.assertEqual(stats["hot_bypass"], 1)


if __name__ == "__main__":
    unittest.main()
