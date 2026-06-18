import asyncio
import os
import sys
import unittest
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(__file__))
BACKEND = os.path.join(ROOT, "backend")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from main import _parse_item_ids, _queue_update_event


class SseQueueTests(unittest.TestCase):
    def test_run_fetch_updates_visible_and_hot_items(self):
        source = (Path(ROOT) / "backend" / "steam_update.py").read_text(encoding="utf-8")

        self.assertIn("hot_item_ids.add", source)
        self.assertIn("mark_item_hot_seen", source)
        self.assertIn("update_ids = set(options.item_ids) | hot_item_ids", source)

    def test_parse_item_ids_ignores_invalid_values(self):
        self.assertEqual(_parse_item_ids("1, 2, bad, -3, 0, 4"), {1, 2, 4})
        self.assertEqual(_parse_item_ids(""), set())
        self.assertIsNone(_parse_item_ids(None))

    def test_queue_update_event_drops_oldest_when_full(self):
        queue = asyncio.Queue(maxsize=2)
        queue.put_nowait({"type": "old"})
        queue.put_nowait({"type": "middle"})

        _queue_update_event(queue, {"type": "new"})

        self.assertEqual(queue.get_nowait()["type"], "middle")
        self.assertEqual(queue.get_nowait()["type"], "new")


if __name__ == "__main__":
    unittest.main()
