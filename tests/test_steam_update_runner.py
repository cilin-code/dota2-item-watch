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


class FakeDiscoverScraper:
    def __init__(self, delay=0):
        self.delay = delay

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def search_items(self, keyword, limit=10):
        if keyword == "":
            return [
                {"market_hash_name": "popular-a", "name_cn": "热门A"},
                {"market_hash_name": "popular-b", "name_cn": "热门B"},
            ]
        if keyword == "Treasure":
            return [
                {"market_hash_name": "popular-b", "name_cn": "热门B"},
                {"market_hash_name": "treasure-c", "name_cn": "宝箱C"},
            ]
        return []


class SteamUpdateRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_discovery_log_reports_after_processing_counts(self):
        runner = SteamUpdateRunner(scraper_factory=FakeDiscoverScraper, trend_engine=FakeTrendEngine())
        logs = []
        ids = {"popular-a": 1, "popular-b": 2, "treasure-c": 3}

        async def fake_get_or_create(_db, market_hash_name, **_kwargs):
            return ids[market_hash_name]

        with (
            patch("steam_update.get_or_create_item", new=AsyncMock(side_effect=fake_get_or_create)),
            patch("steam_update.mark_item_hot_seen", new=AsyncMock()),
        ):
            hot_ids = await runner._discover_items(
                None,
                event_sink=AsyncMock(),
                log_sink=lambda section, message: logs.append((section, message)),
            )

        self.assertEqual(hot_ids, {1, 2, 3})
        self.assertIn("热门", logs[1][1])
        self.assertIn("本次新增   2", logs[1][1])
        self.assertIn("累计命中   2", logs[1][1])
        self.assertIn("Treasure", logs[2][1])
        self.assertIn("本次新增   1", logs[2][1])
        self.assertIn("重复   1", logs[2][1])
        self.assertIn("累计命中   3", logs[2][1])

    async def test_visible_scope_includes_hot_items(self):
        items = [
            {"id": 1, "market_hash_name": "visible", "favorite": 0, "update_after": None},
            {"id": 2, "market_hash_name": "hidden", "favorite": 0, "update_after": None},
            {"id": 3, "market_hash_name": "new", "favorite": 0, "update_after": None},
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
                SteamUpdateOptions(item_ids={1}),
                hot_item_ids={3},
            )

        self.assertEqual([item["id"] for item in selected], [1, 3])
        self.assertEqual(stats["skipped"], 0)

    async def test_visible_scope_still_applies_low_score_cooldown(self):
        items = [
            {"id": 1, "market_hash_name": "visible-low", "favorite": 0, "update_after": "2999-01-01 00:00:00"},
            {"id": 2, "market_hash_name": "visible-high", "favorite": 0, "update_after": None},
            {"id": 3, "market_hash_name": "outside", "favorite": 0, "update_after": None},
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
                SteamUpdateOptions(item_ids={1, 2}),
                hot_item_ids=set(),
            )

        self.assertEqual([item["id"] for item in selected], [2])
        self.assertEqual(stats["skipped"], 1)

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
