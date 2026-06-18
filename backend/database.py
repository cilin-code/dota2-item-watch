"""SQLite persistence helpers for the Steam item monitor."""
from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

import aiosqlite
from price_semantics import QUOTE_SNAPSHOT, TRADE_SNAPSHOT, normalize_snapshot_type, snapshot_type_sql

ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
DB_PATH = os.path.join(ROOT_DIR, "data.db")


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _row(row: aiosqlite.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


async def get_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA foreign_keys = ON")
    return db


async def init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    db = await get_db()
    try:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                market_hash_name TEXT NOT NULL UNIQUE,
                name_cn TEXT,
                icon_url TEXT,
                rarity TEXT,
                hero TEXT,
                slot TEXT,
                quality TEXT,
                favorite INTEGER DEFAULT 0,
                updated_at TIMESTAMP,
                fetched_at TIMESTAMP,
                market_updated_at TIMESTAMP,
                orderbook_json TEXT,
                orderbook_updated_at TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS price_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id INTEGER NOT NULL,
                platform TEXT NOT NULL CHECK(platform IN ('steam')),
                buy_price REAL,
                sell_price REAL,
                volume_24h INTEGER DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                snapshot_type TEXT DEFAULT 'trade',
                FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS daily_summary (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                avg_price REAL,
                min_price REAL,
                max_price REAL,
                volume_total INTEGER DEFAULT 0,
                snapshot_count INTEGER DEFAULT 0,
                FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE,
                UNIQUE(item_id, date)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS price_alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id INTEGER NOT NULL UNIQUE,
                target_price REAL NOT NULL,
                enabled INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS fetch_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                platform TEXT NOT NULL,
                status TEXT NOT NULL,
                items_fetched INTEGER DEFAULT 0,
                error_msg TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS purchase_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id INTEGER NOT NULL,
                buy_price REAL NOT NULL,
                quantity INTEGER DEFAULT 1,
                buy_date TEXT NOT NULL,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE
            )
        """)
        await _ensure_columns(db)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_snap_item_time ON price_snapshots(item_id, updated_at)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_snap_type_time ON price_snapshots(snapshot_type, updated_at)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_snap_item_type_time ON price_snapshots(item_id, snapshot_type, updated_at DESC, id DESC)")
        await db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_daily_item_date ON daily_summary(item_id, date)")
        await db.commit()
    finally:
        await db.close()


async def _ensure_columns(db: aiosqlite.Connection) -> None:
    async def cols(table: str) -> set[str]:
        cur = await db.execute(f"PRAGMA table_info({table})")
        return {r[1] for r in await cur.fetchall()}

    item_cols = await cols("items")
    for name, sql in {
        "hero": "ALTER TABLE items ADD COLUMN hero TEXT",
        "slot": "ALTER TABLE items ADD COLUMN slot TEXT",
        "quality": "ALTER TABLE items ADD COLUMN quality TEXT",
        "favorite": "ALTER TABLE items ADD COLUMN favorite INTEGER DEFAULT 0",
        "updated_at": "ALTER TABLE items ADD COLUMN updated_at TIMESTAMP",
        "fetched_at": "ALTER TABLE items ADD COLUMN fetched_at TIMESTAMP",
        "market_updated_at": "ALTER TABLE items ADD COLUMN market_updated_at TIMESTAMP",
        "orderbook_json": "ALTER TABLE items ADD COLUMN orderbook_json TEXT",
        "orderbook_updated_at": "ALTER TABLE items ADD COLUMN orderbook_updated_at TIMESTAMP",
    }.items():
        if name not in item_cols:
            await db.execute(sql)
    snap_cols = await cols("price_snapshots")
    if "snapshot_type" not in snap_cols:
        await db.execute(f"ALTER TABLE price_snapshots ADD COLUMN snapshot_type TEXT DEFAULT '{TRADE_SNAPSHOT}'")


async def get_or_create_item(db: aiosqlite.Connection, market_hash_name: str, *, name_cn: str = "", icon_url: str = "", rarity: str = "", hero: str = "", slot: str = "", quality: str = "") -> int:
    cur = await db.execute("SELECT id FROM items WHERE market_hash_name = ?", (market_hash_name,))
    found = await cur.fetchone()
    if found:
        item_id = int(found[0])
        await db.execute("""
            UPDATE items SET
                name_cn = COALESCE(NULLIF(?, ''), name_cn),
                icon_url = COALESCE(NULLIF(?, ''), icon_url),
                rarity = COALESCE(NULLIF(?, ''), rarity),
                hero = COALESCE(NULLIF(?, ''), hero),
                slot = COALESCE(NULLIF(?, ''), slot),
                quality = COALESCE(NULLIF(?, ''), quality)
            WHERE id = ?
        """, (name_cn, icon_url, rarity, hero, slot, quality, item_id))
        return item_id
    cur = await db.execute("""
        INSERT INTO items (market_hash_name, name_cn, icon_url, rarity, hero, slot, quality, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (market_hash_name, name_cn, icon_url, rarity, hero, slot, quality, _utc_now()))
    return int(cur.lastrowid)


async def upsert_price(db: aiosqlite.Connection, item_id: int, platform: str, buy_price: float | None, sell_price: float | None, volume_24h: int = 0, updated_at: str | None = None, *, snapshot_type: str = TRADE_SNAPSHOT) -> int:
    updated_at = updated_at or _utc_now()
    snapshot_type = normalize_snapshot_type(snapshot_type)
    cur = await db.execute(
        f"""
        SELECT id FROM price_snapshots
        WHERE item_id = ? AND platform = ? AND {snapshot_type_sql()} = ? AND updated_at = ?
        LIMIT 1
        """,
        (item_id, platform, snapshot_type, updated_at),
    )
    existing = await cur.fetchone()
    if existing:
        await db.execute(
            """
            UPDATE price_snapshots
            SET buy_price = ?, sell_price = ?, volume_24h = ?
            WHERE id = ?
            """,
            (buy_price, sell_price, int(volume_24h or 0), existing[0]),
        )
        row_id = int(existing[0])
    else:
        cur = await db.execute("""
            INSERT INTO price_snapshots (item_id, platform, buy_price, sell_price, volume_24h, updated_at, snapshot_type)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (item_id, platform, buy_price, sell_price, int(volume_24h or 0), updated_at, snapshot_type))
        row_id = int(cur.lastrowid)
    if snapshot_type == QUOTE_SNAPSHOT:
        await db.execute("UPDATE items SET updated_at = ?, fetched_at = ? WHERE id = ?", (updated_at, updated_at, item_id))
    return row_id


async def update_item_market_metadata(db: aiosqlite.Connection, item_id: int, *, fetched_at: str | None = None, market_updated_at: str | None = None, orderbook: dict | None = None, orderbook_updated_at: str | None = None) -> None:
    fetched_at = fetched_at or _utc_now()
    await db.execute("""
        UPDATE items SET fetched_at = ?, updated_at = ?, market_updated_at = COALESCE(?, market_updated_at),
            orderbook_json = COALESCE(?, orderbook_json), orderbook_updated_at = COALESCE(?, orderbook_updated_at)
        WHERE id = ?
    """, (fetched_at, fetched_at, market_updated_at, json.dumps(orderbook, ensure_ascii=False) if orderbook else None, orderbook_updated_at, item_id))


async def get_monitored_items(db: aiosqlite.Connection, limit: int | None = None) -> list[dict[str, Any]]:
    sql = f"""
        SELECT i.*, q.sell_price AS latest_quote_price, q.updated_at AS latest_quote_at
        FROM items i
        LEFT JOIN price_snapshots q ON q.id = (
            SELECT ps.id FROM price_snapshots ps
            WHERE ps.item_id = i.id AND ps.snapshot_type = '{QUOTE_SNAPSHOT}'
            ORDER BY ps.updated_at DESC, ps.id DESC LIMIT 1
        )
        ORDER BY i.favorite DESC, i.id ASC
    """
    params: tuple[Any, ...] = ()
    if limit is not None:
        sql += " LIMIT ?"
        params = (limit,)
    cur = await db.execute(sql, params)
    return [dict(r) for r in await cur.fetchall()]


async def get_item_by_id(db: aiosqlite.Connection, item_id: int) -> dict[str, Any] | None:
    cur = await db.execute(f"""
        SELECT i.*, q.sell_price AS latest_quote_price, q.updated_at AS latest_quote_at
        FROM items i
        LEFT JOIN price_snapshots q ON q.id = (
            SELECT ps.id FROM price_snapshots ps
            WHERE ps.item_id = i.id AND ps.snapshot_type = '{QUOTE_SNAPSHOT}'
            ORDER BY ps.updated_at DESC, ps.id DESC LIMIT 1
        )
        WHERE i.id = ?
    """, (item_id,))
    return _row(await cur.fetchone())


async def get_steam_history(db: aiosqlite.Connection, days: int = 90) -> list[dict[str, Any]]:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    cur = await db.execute(f"""
        SELECT i.id, i.market_hash_name, i.name_cn, i.icon_url, i.rarity, i.orderbook_json, i.orderbook_updated_at,
               q.sell_price AS latest_quote_price, q.updated_at AS latest_quote_at,
               ps.buy_price, ps.sell_price, ps.volume_24h, ps.updated_at
        FROM price_snapshots ps
        JOIN items i ON i.id = ps.item_id
        LEFT JOIN price_snapshots q ON q.id = (
            SELECT q2.id FROM price_snapshots q2
            WHERE q2.item_id = i.id AND q2.snapshot_type = '{QUOTE_SNAPSHOT}'
            ORDER BY q2.updated_at DESC, q2.id DESC LIMIT 1
        )
        WHERE ps.platform = 'steam' AND {snapshot_type_sql('ps.snapshot_type')} = '{TRADE_SNAPSHOT}' AND ps.updated_at >= ?
        ORDER BY i.id ASC, ps.updated_at ASC, ps.id ASC
    """, (since,))
    return [dict(r) for r in await cur.fetchall()]


async def get_backtest_history(db: aiosqlite.Connection, days: int = 360) -> list[dict[str, Any]]:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    cur = await db.execute(f"""
        SELECT i.id, i.market_hash_name, i.name_cn, i.icon_url, i.rarity,
               ps.buy_price, ps.sell_price, ps.volume_24h, ps.updated_at
        FROM price_snapshots ps
        JOIN items i ON i.id = ps.item_id
        WHERE ps.platform = 'steam' AND {snapshot_type_sql('ps.snapshot_type')} = '{TRADE_SNAPSHOT}' AND ps.updated_at >= ?
        ORDER BY i.id ASC, ps.updated_at ASC, ps.id ASC
    """, (since,))
    return [dict(r) for r in await cur.fetchall()]


async def get_item_history(db: aiosqlite.Connection, item_id: int, days: int = 90) -> list[dict[str, Any]]:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    cur = await db.execute(f"""
        SELECT id, item_id, platform, buy_price, sell_price, volume_24h, updated_at, snapshot_type
        FROM price_snapshots
        WHERE item_id = ? AND {snapshot_type_sql()} = '{TRADE_SNAPSHOT}' AND updated_at >= ?
        ORDER BY updated_at ASC, id ASC
    """, (item_id, since))
    return [dict(r) for r in await cur.fetchall()]


async def compute_daily_summary(db: aiosqlite.Connection, item_id: int) -> None:
    await db.execute("DELETE FROM daily_summary WHERE item_id = ?", (item_id,))
    cur = await db.execute(f"""
        SELECT substr(updated_at, 1, 10) AS day, AVG(sell_price) AS avg_price, MIN(sell_price) AS min_price,
               MAX(sell_price) AS max_price, SUM(COALESCE(volume_24h, 0)) AS volume_total, COUNT(*) AS snapshot_count
        FROM price_snapshots
        WHERE item_id = ? AND {snapshot_type_sql()} = '{TRADE_SNAPSHOT}' AND sell_price IS NOT NULL
        GROUP BY substr(updated_at, 1, 10)
        ORDER BY day ASC
    """, (item_id,))
    for r in await cur.fetchall():
        await db.execute("""
            INSERT INTO daily_summary (item_id, date, avg_price, min_price, max_price, volume_total, snapshot_count)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(item_id, date) DO UPDATE SET avg_price=excluded.avg_price, min_price=excluded.min_price,
                max_price=excluded.max_price, volume_total=excluded.volume_total, snapshot_count=excluded.snapshot_count
        """, (item_id, r["day"], r["avg_price"], r["min_price"], r["max_price"], r["volume_total"] or 0, r["snapshot_count"] or 0))


async def get_daily_summary(db: aiosqlite.Connection, item_id: int, days: int = 360) -> list[dict[str, Any]]:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    cur = await db.execute("SELECT date, avg_price, min_price, max_price, volume_total, snapshot_count FROM daily_summary WHERE item_id = ? AND date >= ? ORDER BY date ASC", (item_id, since))
    rows = [dict(r) for r in await cur.fetchall()]
    if rows:
        return rows
    await compute_daily_summary(db, item_id)
    cur = await db.execute("SELECT date, avg_price, min_price, max_price, volume_total, snapshot_count FROM daily_summary WHERE item_id = ? AND date >= ? ORDER BY date ASC", (item_id, since))
    return [dict(r) for r in await cur.fetchall()]


async def get_monitor_stats(db: aiosqlite.Connection) -> dict[str, Any]:
    total = (await (await db.execute("SELECT COUNT(*) FROM items")).fetchone())[0]
    favorites = (await (await db.execute("SELECT COUNT(*) FROM items WHERE favorite = 1")).fetchone())[0]
    alerts = (await (await db.execute("SELECT COUNT(*) FROM price_alerts WHERE enabled = 1")).fetchone())[0]
    latest = (await (await db.execute("SELECT MAX(updated_at) FROM items")).fetchone())[0]
    return {"total_items": total, "favorite_items": favorites, "alerts": alerts, "latest_update": latest, "last_update": latest}


async def set_alert(db: aiosqlite.Connection, item_id: int, target_price: float) -> None:
    await db.execute("INSERT INTO price_alerts (item_id, target_price, enabled) VALUES (?, ?, 1) ON CONFLICT(item_id) DO UPDATE SET target_price=excluded.target_price, enabled=1", (item_id, target_price))
    await db.commit()


async def get_alert(db: aiosqlite.Connection, item_id: int) -> dict[str, Any] | None:
    return _row(await (await db.execute("SELECT * FROM price_alerts WHERE item_id = ?", (item_id,))).fetchone())


async def delete_alert(db: aiosqlite.Connection, item_id: int) -> None:
    await db.execute("DELETE FROM price_alerts WHERE item_id = ?", (item_id,))
    await db.commit()


async def get_all_alerts(db: aiosqlite.Connection) -> list[dict[str, Any]]:
    cur = await db.execute("SELECT * FROM price_alerts WHERE enabled = 1 ORDER BY item_id")
    return [dict(r) for r in await cur.fetchall()]


async def get_triggered_alerts(db: aiosqlite.Connection) -> list[dict[str, Any]]:
    cur = await db.execute(f"""
        SELECT a.id, a.item_id, a.target_price, a.enabled, a.created_at, i.market_hash_name, i.name_cn, i.icon_url,
               q.sell_price AS current_price, q.updated_at AS price_updated_at
        FROM price_alerts a
        JOIN items i ON i.id = a.item_id
        JOIN price_snapshots q ON q.id = (
            SELECT q2.id FROM price_snapshots q2
            WHERE q2.item_id = i.id AND q2.snapshot_type = '{QUOTE_SNAPSHOT}'
            ORDER BY q2.updated_at DESC, q2.id DESC LIMIT 1
        )
        WHERE a.enabled = 1 AND q.sell_price <= a.target_price
        ORDER BY q.sell_price ASC
    """)
    return [dict(r) for r in await cur.fetchall()]


async def delete_item(db: aiosqlite.Connection, item_id: int) -> bool:
    if not await (await db.execute("SELECT id FROM items WHERE id = ?", (item_id,))).fetchone():
        return False
    for table in ("price_snapshots", "daily_summary", "price_alerts", "purchase_records"):
        await db.execute(f"DELETE FROM {table} WHERE item_id = ?", (item_id,))
    await db.execute("DELETE FROM items WHERE id = ?", (item_id,))
    await db.commit()
    return True


async def clear_all_data(db: aiosqlite.Connection) -> dict[str, Any]:
    tables = ["price_snapshots", "daily_summary", "price_alerts", "purchase_records", "items", "fetch_log"]
    before = {}
    for table in tables:
        before[table] = int((await (await db.execute(f"SELECT COUNT(*) FROM {table}")).fetchone())[0])
    for table in tables:
        await db.execute(f"DELETE FROM {table}")
    await db.execute("DELETE FROM sqlite_sequence WHERE name IN ('price_snapshots','daily_summary','price_alerts','purchase_records','items','fetch_log')")
    await db.commit()
    return {"deleted": before, "total_deleted": sum(before.values())}


async def toggle_favorite(db: aiosqlite.Connection, item_id: int) -> int | None:
    row = await (await db.execute("SELECT favorite FROM items WHERE id = ?", (item_id,))).fetchone()
    if not row:
        return None
    value = 0 if row[0] else 1
    await db.execute("UPDATE items SET favorite = ? WHERE id = ?", (value, item_id))
    await db.commit()
    return value


async def get_favorite_ids(db: aiosqlite.Connection) -> set[int]:
    cur = await db.execute("SELECT id FROM items WHERE favorite = 1")
    return {int(r[0]) for r in await cur.fetchall()}


async def log_fetch(db: aiosqlite.Connection, platform: str, status: str, items_fetched: int = 0, error_msg: str | None = None) -> None:
    await db.execute("INSERT INTO fetch_log (platform, status, items_fetched, error_msg) VALUES (?, ?, ?, ?)", (platform, status, items_fetched, error_msg))
    await db.commit()


async def update_all_chinese_names(db: aiosqlite.Connection) -> int:
    cur = await db.execute("SELECT id, market_hash_name, name_cn FROM items")
    updated = 0
    for r in await cur.fetchall():
        if r["name_cn"]:
            continue
        await db.execute("UPDATE items SET name_cn = ? WHERE id = ?", (r["market_hash_name"], r["id"]))
        updated += 1
    return updated


async def add_purchase(db: aiosqlite.Connection, item_id: int, buy_price: float, quantity: int = 1, buy_date: str | None = None, notes: str | None = None) -> int:
    cur = await db.execute("INSERT INTO purchase_records (item_id, buy_price, quantity, buy_date, notes) VALUES (?, ?, ?, ?, ?)", (item_id, buy_price, int(quantity or 1), buy_date or datetime.now().strftime("%Y-%m-%d"), notes))
    await db.commit()
    return int(cur.lastrowid)


async def get_purchases(db: aiosqlite.Connection) -> list[dict[str, Any]]:
    cur = await db.execute(f"""
        SELECT p.*, i.market_hash_name, i.name_cn, i.icon_url, q.sell_price AS current_price,
               CASE WHEN q.sell_price IS NOT NULL THEN (q.sell_price - p.buy_price) * p.quantity ELSE NULL END AS pnl,
               CASE WHEN q.sell_price IS NOT NULL AND p.buy_price > 0 THEN (q.sell_price - p.buy_price) / p.buy_price * 100 ELSE NULL END AS pnl_pct
        FROM purchase_records p
        JOIN items i ON i.id = p.item_id
        LEFT JOIN price_snapshots q ON q.id = (
            SELECT q2.id FROM price_snapshots q2
            WHERE q2.item_id = i.id AND q2.snapshot_type = '{QUOTE_SNAPSHOT}'
            ORDER BY q2.updated_at DESC, q2.id DESC LIMIT 1
        )
        ORDER BY p.buy_date DESC, p.id DESC
    """)
    return [dict(r) for r in await cur.fetchall()]


async def delete_purchase(db: aiosqlite.Connection, purchase_id: int) -> bool:
    cur = await db.execute("DELETE FROM purchase_records WHERE id = ?", (purchase_id,))
    await db.commit()
    return cur.rowcount > 0


async def get_periodic_analysis(db: aiosqlite.Connection, item_id: int, days: int = 180) -> dict[str, Any]:
    rows = await get_daily_summary(db, item_id, days=days)
    if len(rows) < 14:
        return {"has_cycle": False, "message": "样本不足", "days": days, "weekly": [], "monthly": []}
    by_weekday: dict[int, list[float]] = defaultdict(list)
    by_month_day: dict[int, list[float]] = defaultdict(list)
    vals = []
    for r in rows:
        if r.get("avg_price") is None:
            continue
        day = datetime.strptime(r["date"], "%Y-%m-%d")
        price = float(r["avg_price"])
        vals.append(price)
        by_weekday[day.weekday()].append(price)
        by_month_day[day.day].append(price)
    if not vals:
        return {"has_cycle": False, "days": days, "weekly": [], "monthly": []}
    overall = sum(vals) / len(vals)
    weekly = [{"weekday": k, "avg_price": round(sum(v) / len(v), 4), "diff_pct": round((sum(v) / len(v) - overall) / overall * 100, 2), "samples": len(v)} for k, v in sorted(by_weekday.items()) if v]
    monthly = [{"day": k, "avg_price": round(sum(v) / len(v), 4), "diff_pct": round((sum(v) / len(v) - overall) / overall * 100, 2), "samples": len(v)} for k, v in sorted(by_month_day.items()) if len(v) >= 2]
    strongest = max([abs(x["diff_pct"]) for x in weekly + monthly], default=0)
    return {"has_cycle": strongest >= 3, "days": days, "overall_avg": round(overall, 4), "weekly": weekly, "monthly": monthly, "strength_pct": round(strongest, 2)}
