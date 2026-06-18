import asyncio
import tempfile
import os
import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import database
from price_semantics import QUOTE_SNAPSHOT


def run(coro):
    return asyncio.run(coro)


async def with_temp_db(tmp_path, fn):
    original = database.DB_PATH
    tmp_path.mkdir(parents=True, exist_ok=True)
    db_file = tmp_path / "test.db"
    if db_file.exists():
        db_file.unlink()
    database.DB_PATH = str(db_file)
    try:
        await database.init_db()
        return await fn()
    finally:
        database.DB_PATH = original


def temp_test_dir(name):
    return Path(tempfile.gettempdir()) / "饰品监测-tests" / name


class DatabaseTests(unittest.TestCase):
    def test_compute_daily_summary_upserts_per_item_day(self):
        async def scenario():
            db = await database.get_db()
            try:
                item_id = await database.get_or_create_item(db, "Sample Item", name_cn="样例饰品")
                await database.upsert_price(db, item_id, "steam", 1.0, 1.0, 2, "2026-01-01 01:00:00")
                await database.upsert_price(db, item_id, "steam", 3.0, 3.0, 4, "2026-01-01 12:00:00")
                await database.upsert_price(db, item_id, "steam", 5.0, 5.0, 8, "2026-01-02 01:00:00")
                await database.compute_daily_summary(db, item_id)
                await db.commit()

                rows = await database.get_daily_summary(db, item_id, days=3650)
            finally:
                await db.close()
            return rows

        rows = run(with_temp_db(temp_test_dir(self._testMethodName), scenario))

        self.assertEqual(rows, [
            {"date": "2026-01-01", "avg_price": 2.0, "min_price": 1.0, "max_price": 3.0, "volume_total": 6, "snapshot_count": 2},
            {"date": "2026-01-02", "avg_price": 5.0, "min_price": 5.0, "max_price": 5.0, "volume_total": 8, "snapshot_count": 1},
        ])

    def test_history_and_daily_summary_ignore_quote_snapshots(self):
        async def scenario():
            db = await database.get_db()
            try:
                item_id = await database.get_or_create_item(db, "History Item", name_cn="History Item")
                await database.upsert_price(db, item_id, "steam", 1.0, 1.0, 2, "2026-01-01 01:00:00")
                await database.upsert_price(db, item_id, "steam", 3.0, 3.0, 4, "2026-01-01 12:00:00", snapshot_type=QUOTE_SNAPSHOT)
                await database.compute_daily_summary(db, item_id)
                await db.commit()

                history = await database.get_item_history(db, item_id, days=3650)
                steam_history = await database.get_steam_history(db, days=3650)
                backtest_history = await database.get_backtest_history(db, days=3650)
                summary = await database.get_daily_summary(db, item_id, days=3650)
            finally:
                await db.close()
            return history, steam_history, backtest_history, summary

        history, steam_history, backtest_history, summary = run(with_temp_db(temp_test_dir(self._testMethodName), scenario))

        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["sell_price"], 1.0)
        self.assertEqual(len(steam_history), 1)
        self.assertEqual(steam_history[0]["sell_price"], 1.0)
        self.assertEqual(steam_history[0]["latest_quote_price"], 3.0)
        self.assertEqual(len(backtest_history), 1)
        self.assertEqual(backtest_history[0]["sell_price"], 1.0)
        self.assertEqual(summary[0]["avg_price"], 1.0)
        self.assertEqual(summary[0]["snapshot_count"], 1)

    def test_triggered_alerts_compare_latest_price_to_target(self):
        async def scenario():
            db = await database.get_db()
            try:
                item_id = await database.get_or_create_item(db, "Alert Item", name_cn="预警饰品")
                await database.upsert_price(db, item_id, "steam", 1.2, 1.2, 3, "2026-01-01 01:00:00")
                await database.upsert_price(db, item_id, "steam", 0.8, 0.8, 3, "2026-01-02 01:00:00", snapshot_type=QUOTE_SNAPSHOT)
                await database.set_alert(db, item_id, 1.0)
                rows = await database.get_triggered_alerts(db)
            finally:
                await db.close()
            return rows

        rows = run(with_temp_db(temp_test_dir(self._testMethodName), scenario))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name_cn"], "预警饰品")
        self.assertEqual(rows[0]["current_price"], 0.8)

    def test_clear_all_data_removes_items_and_related_rows(self):
        async def scenario():
            db = await database.get_db()
            try:
                item_id = await database.get_or_create_item(db, "Clear Item", name_cn="Clear Item")
                await database.upsert_price(db, item_id, "steam", 1.0, 1.0, 2, "2026-01-01 01:00:00")
                await database.compute_daily_summary(db, item_id)
                await database.set_alert(db, item_id, 0.8)
                await database.add_purchase(db, item_id, 1.0, 1, "2026-01-02", "test")
                await database.log_fetch(db, "steam", "ok", 1)
                result = await database.clear_all_data(db)
                counts = {}
                for table in ("items", "price_snapshots", "daily_summary", "price_alerts", "purchase_records", "fetch_log"):
                    cur = await db.execute(f"SELECT COUNT(*) FROM {table}")
                    counts[table] = (await cur.fetchone())[0]
            finally:
                await db.close()
            return result, counts

        result, counts = run(with_temp_db(temp_test_dir(self._testMethodName), scenario))

        self.assertGreaterEqual(result["total_deleted"], 6)
        self.assertTrue(all(value == 0 for value in counts.values()))


if __name__ == "__main__":

    unittest.main()
