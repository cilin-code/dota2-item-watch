import os
import sys
from datetime import datetime, timedelta, timezone
import unittest

ROOT = os.path.dirname(os.path.dirname(__file__))
BACKEND = os.path.join(ROOT, "backend")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from update_policy import cooldown_hours_for_score, decide_update, format_db_time


class UpdatePolicyTests(unittest.TestCase):
    def test_only_scores_below_twenty_get_cooldown(self):
        self.assertIsNone(cooldown_hours_for_score(20))
        self.assertEqual(cooldown_hours_for_score(19.9), 12)
        self.assertEqual(cooldown_hours_for_score(12), 24)
        self.assertEqual(cooldown_hours_for_score(7), 72)
        self.assertEqual(cooldown_hours_for_score(2), 168)

    def test_low_score_item_is_skipped_until_update_after(self):
        now = datetime(2026, 6, 19, 12, 0, tzinfo=timezone.utc)
        item = {"id": 1, "favorite": 0, "update_after": format_db_time(now + timedelta(hours=6))}

        decision = decide_update(item, score=8, now=now)

        self.assertFalse(decision.allow)
        self.assertEqual(decision.cooldown_hours, 72)
        self.assertGreater(decision.remaining_seconds, 0)

    def test_hot_and_protected_items_bypass_low_score_cooldown(self):
        now = datetime(2026, 6, 19, 12, 0, tzinfo=timezone.utc)
        item = {"id": 1, "favorite": 0, "update_after": format_db_time(now + timedelta(days=6))}

        hot = decide_update(item, score=3, now=now, hot_item_ids={1})
        protected = decide_update(item, score=3, now=now, protected_item_ids={1})

        self.assertTrue(hot.allow)
        self.assertTrue(hot.bypass)
        self.assertEqual(hot.reason, "Steam 热门命中")
        self.assertTrue(protected.allow)
        self.assertEqual(protected.reason, "买入或预警保护")


if __name__ == "__main__":
    unittest.main()
