import asyncio
import os
import sys
import unittest
from unittest.mock import AsyncMock, patch

ROOT = os.path.dirname(os.path.dirname(__file__))
BACKEND = os.path.join(ROOT, "backend")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

import main


def run(coro):
    return asyncio.run(coro)


class FakeCursor:
    async def fetchall(self):
        return []


class FakeDb:
    async def execute(self, *args, **kwargs):
        return FakeCursor()

    async def close(self):
        pass


class FakeEngine:
    def __init__(self):
        self.loaded = []

    def load_history(self, rows):
        self.loaded = rows

    def recommendations(self, min_score=0, recommend_only=False):
        rows = [
            {"id": 1, "market_hash_name": "Low", "name_cn": "Low", "score": 10, "volume_24h": 1, "analysis": {}, "trend": {}},
            {"id": 2, "market_hash_name": "High", "name_cn": "High", "score": 95, "volume_24h": 2, "analysis": {}, "trend": {}},
            {"id": 3, "market_hash_name": "Mid", "name_cn": "Mid", "score": 60, "volume_24h": 3, "analysis": {}, "trend": {}},
        ]
        if min_score:
            rows = [row for row in rows if row["score"] >= min_score]
        return sorted(rows, key=lambda row: (row["score"], row["volume_24h"]), reverse=True)


class ItemsApiTests(unittest.TestCase):
    def test_get_items_supports_score_ordered_pagination(self):
        main._cache.clear()
        main._cache_version += 1
        monitored = [
            {"id": 1, "latest_quote_price": 1.0},
            {"id": 2, "latest_quote_price": 2.0},
            {"id": 3, "latest_quote_price": 3.0},
        ]
        with (
            patch.object(main, "get_db", new=AsyncMock(return_value=FakeDb())),
            patch.object(main, "get_steam_history", new=AsyncMock(return_value=[])),
            patch.object(main, "get_monitored_items", new=AsyncMock(return_value=monitored)),
            patch.object(main, "engine", new=FakeEngine()),
        ):
            result = run(main.get_items(min_score=0, q="", limit=2, offset=0))

        self.assertEqual(result["total"], 3)
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["offset"], 0)
        self.assertEqual(result["limit"], 2)
        self.assertEqual([item["id"] for item in result["data"]], [2, 3])


if __name__ == "__main__":
    unittest.main()
