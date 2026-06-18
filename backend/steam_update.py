"""Steam batch update runner.

This module keeps the FastAPI route thin: routes own SSE plumbing, while the
runner owns discovery, update scope, quote validation, history persistence, and
progress events.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable

from database import (
    compute_daily_summary,
    get_db,
    get_monitored_items,
    get_or_create_item,
    get_steam_history,
    update_all_chinese_names,
    update_item_market_metadata,
    upsert_price,
)
from display import _pad_display, _price_label
from engine import engine
from price_semantics import QUOTE_SNAPSHOT, validate_quote_price
from scrapers import SteamScraper

EventSink = Callable[[dict], Awaitable[None]]
LogSink = Callable[[str, str], None]

@dataclass(slots=True)
class SteamUpdateOptions:
    limit: int = 300
    discover: bool = True
    delay: float = 3.0
    min_score: int = 0
    item_ids: set[int] | None = None


def _noop_log(section: str, message: str) -> None:
    return None


async def _noop_event(data: dict) -> None:
    return None


async def save_steam_history(db, scraper: SteamScraper, item_id: int, market_hash_name: str) -> dict:
    """Fetch and persist Steam listing trade history for one item."""
    listing = await scraper.get_listing_data(market_hash_name, days=90)
    history = listing.get("history") or []
    for point in history:
        await upsert_price(
            db,
            item_id,
            "steam",
            point.get("buy_price"),
            point.get("sell_price"),
            point.get("volume_24h", 0),
            point.get("updated_at"),
        )
    await compute_daily_summary(db, item_id)
    market_updated_at = history[-1].get("updated_at") if history else None
    return {
        "history_count": len(history),
        "market_updated_at": market_updated_at,
        "orderbook": listing.get("orderbook"),
        "rate_limited": bool(listing.get("rate_limited")),
    }


class SteamUpdateRunner:
    def __init__(
        self,
        *,
        db_factory=get_db,
        scraper_factory=SteamScraper,
        history_saver=save_steam_history,
        trend_engine=engine,
    ):
        self.db_factory = db_factory
        self.scraper_factory = scraper_factory
        self.history_saver = history_saver
        self.engine = trend_engine

    async def run(
        self,
        options: SteamUpdateOptions,
        *,
        event_sink: EventSink = _noop_event,
        log_sink: LogSink = _noop_log,
    ) -> dict:
        db = await self.db_factory()
        results = {"steam": 0, "history": 0, "discovered": 0, "errors": []}
        discovered_item_ids: set[int] = set()
        try:
            async with self.scraper_factory(delay=options.delay) as scraper:
                if options.discover:
                    discovered_item_ids = await self._discover_items(db, event_sink, log_sink)
                    results["discovered"] = len(discovered_item_ids)
                await db.commit()

                db_items = await self._select_update_items(db, options, discovered_item_ids)
                total = len(db_items)
                scope = "当前显示 + 本轮新增" if options.item_ids is not None else "全部监控"
                log_sink("更新", f"阶段 2/2 | 更新价格 | 范围 {scope} | 数量 {total}")
                await event_sink({"type": "phase", "platform": "steam", "status": "prices", "total": total})

                count, history_count = await self._update_prices(
                    db,
                    scraper,
                    db_items,
                    total,
                    event_sink,
                    log_sink,
                    results,
                )
                results["steam"] = count
                results["history"] = history_count
                await update_all_chinese_names(db)
                await db.commit()
        except Exception as exc:
            log_sink("更新", f"错误 | {exc}")
            await event_sink({"type": "error", "platform": "steam", "message": str(exc)})
        finally:
            await db.close()
            log_sink(
                "更新",
                f"完成 | 现价 {results['steam']} | 成交点 {results['history']} | "
                f"新增 {results['discovered']} | 错误 {len(results['errors'])}",
            )
            await event_sink({"type": "done", "results": results})
        return results

    async def _discover_items(self, db, event_sink: EventSink, log_sink: LogSink) -> set[int]:
        log_sink("更新", "阶段 1/2 | 搜索 Steam 热门饰品")
        await event_sink({"type": "phase", "platform": "steam", "status": "discover"})
        discovered_item_ids: set[int] = set()
        keywords = ["", "Treasure", "Immortal", "Arcana", "Set", "Courier", "Ward", "Taunt"]
        seen = set()
        async with self.scraper_factory(delay=1.5) as disc_scraper:
            for kw in keywords:
                try:
                    items = await disc_scraper.search_items(kw, limit=100 if kw == "" else 10)
                    label = kw or "热门"
                    log_sink(
                        "发现",
                        f"{_pad_display(label, 10)} | 搜索结果 {len(items):>3} | 本轮新增 {len(discovered_item_ids):>3}",
                    )
                    await event_sink({
                        "type": "phase",
                        "platform": "steam",
                        "status": "discover",
                        "keyword": kw,
                        "found": len(items),
                    })
                    for item in items:
                        mhn = item.get("market_hash_name", "")
                        if mhn in seen:
                            continue
                        seen.add(mhn)
                        existing_cur = await db.execute("SELECT id FROM items WHERE market_hash_name = ?", (mhn,))
                        existing = await existing_cur.fetchone()
                        item_id = await get_or_create_item(
                            db,
                            mhn,
                            name_cn=item.get("name_cn") or item.get("name") or "",
                            icon_url=item.get("icon_url") or "",
                            rarity=item.get("rarity") or "",
                        )
                        if not existing:
                            discovered_item_ids.add(int(item_id))
                        await event_sink({
                            "type": "item",
                            "platform": "steam",
                            "market_hash_name": mhn,
                            "name_cn": item.get("name_cn") or "",
                            "icon_url": item.get("icon_url") or "",
                        })
                except Exception as exc:
                    log_sink("发现", f"异常 | {kw or '热门'} | {exc}")
        return discovered_item_ids

    async def _select_update_items(self, db, options: SteamUpdateOptions, discovered_item_ids: set[int]) -> list[dict]:
        db_items = await get_monitored_items(db, limit=None if options.item_ids is not None else options.limit)
        if options.item_ids is not None:
            update_ids = set(options.item_ids) | discovered_item_ids
            return [it for it in db_items if int(it["id"]) in update_ids]
        if options.min_score > 0:
            self.engine.load_history(await get_steam_history(db, days=90))
            scored = {r["id"]: r["score"] for r in self.engine.recommendations(min_score=0)}
            return [it for it in db_items if scored.get(it["id"], 0) >= options.min_score]
        return db_items

    async def _update_prices(
        self,
        db,
        scraper: SteamScraper,
        db_items: list[dict],
        total: int,
        event_sink: EventSink,
        log_sink: LogSink,
        results: dict,
    ) -> tuple[int, int]:
        count = 0
        history_count = 0
        rate_limited = False
        consecutive_fails = 0
        for i, item in enumerate(db_items):
            if rate_limited:
                break
            try:
                await asyncio.sleep(0.1)
                await event_sink({
                    "type": "item",
                    "platform": "steam",
                    "index": i + 1,
                    "item_id": item["id"],
                    "market_hash_name": item["market_hash_name"],
                    "name_cn": item.get("name_cn") or "",
                    "icon_url": item.get("icon_url") or "",
                })
                name_display = item.get("name_cn") or item["market_hash_name"]
                now_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                price_data = await scraper.get_price(item["market_hash_name"])
                listing_result = {"history_count": 0, "market_updated_at": None, "orderbook": None, "rate_limited": False}
                h_count = 0
                try:
                    listing_result = await self.history_saver(db, scraper, item["id"], item["market_hash_name"])
                    h_count = listing_result["history_count"]
                    history_count += h_count
                except Exception:
                    pass
                checked_price, quote_status = validate_quote_price(price_data, listing_result.get("orderbook"))
                if checked_price and checked_price.get("sell_price"):
                    two_min_ago = (datetime.now(timezone.utc) - timedelta(minutes=2)).strftime("%Y-%m-%d %H:%M:%S")
                    cursor_b = await db.execute(
                        "SELECT COUNT(*) FROM price_snapshots WHERE item_id = ? AND platform = ? AND snapshot_type = ? AND updated_at >= ?",
                        (item["id"], "steam", QUOTE_SNAPSHOT, two_min_ago),
                    )
                    if (await cursor_b.fetchone())[0] == 0:
                        await upsert_price(
                            db,
                            item["id"],
                            "steam",
                            checked_price.get("buy_price"),
                            checked_price.get("sell_price"),
                            checked_price.get("volume_24h", 0),
                            now_ts,
                            snapshot_type=QUOTE_SNAPSHOT,
                        )
                    price_text = _price_label(checked_price.get("sell_price"))
                    count += 1
                    consecutive_fails = 0
                else:
                    consecutive_fails += 1
                    price_text = f"跳过 quote {quote_status}"
                await compute_daily_summary(db, item["id"])
                market_time = listing_result.get("market_updated_at")
                if not market_time and checked_price and checked_price.get("sell_price"):
                    market_time = now_ts
                await update_item_market_metadata(
                    db,
                    item["id"],
                    fetched_at=now_ts,
                    market_updated_at=market_time,
                    orderbook=listing_result.get("orderbook"),
                    orderbook_updated_at=now_ts,
                )

                if consecutive_fails >= 5:
                    rate_limited = True
                    await event_sink({
                        "type": "ratelimited",
                        "message": "Steam 限流中，已终止更新。请等半小时后再试。",
                        "current": i + 1,
                        "total": total,
                    })
                    break

                await db.commit()
                log_sink(
                    "更新",
                    f"{i+1:>3}/{total:<3} | "
                    f"{_pad_display(name_display, 34)} | "
                    f"{_pad_display(price_text, 18)} | 成交点 {h_count}",
                )
                await event_sink({
                    "type": "progress",
                    "platform": "steam",
                    "current": i + 1,
                    "updated": count,
                    "history": history_count,
                    "total": total,
                })
            except Exception as exc:
                results["errors"].append(f"{item['market_hash_name']}: {exc}")
        return count, history_count
