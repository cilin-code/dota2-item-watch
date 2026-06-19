"""饰品监测 - Steam 趋势监测 API"""
import json
import os
import asyncio
import time as _time
from datetime import datetime, timedelta, timezone
from contextlib import asynccontextmanager

from fastapi import Body, FastAPI, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from database import (
    clear_all_data,
    get_periodic_analysis,
    add_purchase,
    get_purchases,
    delete_purchase,
    set_alert,
    get_alert,
    delete_alert,
    get_all_alerts,
    get_triggered_alerts,
    delete_item,
    get_favorite_ids,
    compute_daily_summary,
    get_daily_summary,
    toggle_favorite,
    get_db,
    get_item_by_id,
    get_item_history,
    get_backtest_history,
    get_monitor_stats,
    get_monitored_items,
    get_or_create_item,
    get_steam_history,
    init_db,
    log_fetch,
    update_all_chinese_names,
    update_item_market_metadata,
    upsert_price,
)
from display import _display_width, _pad_display, _price_label, _short_name, _truncate_display
from engine import engine
from scrapers import SteamScraper
from steam_update import SteamUpdateOptions, SteamUpdateRunner, _validate_quote_price, save_steam_history

_cache = {}
_cache_version = 0
_cache_ttl = 600
_backtest_cache = {}
_update_running = False
_update_task: asyncio.Task | None = None
_update_subscribers: set[asyncio.Queue] = set()
_update_events: list[dict] = []
_update_event_limit = 500

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")


def _log(section: str, message: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {_pad_display(section, 4)} | {message}", flush=True)


# ------------------------------------------------------------------
# 应用
# ------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="饰品监测", lifespan=lifespan)


@app.get("/api/update-status")
async def update_status():
    return {"running": _update_running}


# ------------------------------------------------------------------
# 页面路由
# ------------------------------------------------------------------

@app.get("/")
async def index():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))


@app.get("/item/{item_id}")
async def item_page(item_id: int):
    return FileResponse(os.path.join(FRONTEND_DIR, "detail.html"))


# ------------------------------------------------------------------
# API: 饰品数据
# ------------------------------------------------------------------

@app.get("/api/items")
async def get_items(min_score: int = Query(0), q: str = Query("")):
    """获取所有饰品的分析结果。"""
    cache_key = f"items:{min_score}:{q}"
    now = _time.time()
    if cache_key in _cache and now - _cache[cache_key][0] < _cache_ttl:
        # verify no new data since cache
        cache_ver = _cache[cache_key][2] if len(_cache[cache_key]) > 2 else 0
        if cache_ver == _cache_version:
            return _cache[cache_key][1]
    db = await get_db()
    try:
        rows = await get_steam_history(db, days=90)
        engine.load_history(rows)
        results = engine.recommendations(min_score=min_score)

        # 用 items.updated_at 覆盖（记录真实抓取时间）
        cursor = await db.execute("SELECT id, updated_at FROM items WHERE updated_at IS NOT NULL")
        fetch_times = {row[0]: row[1] for row in await cursor.fetchall()}
        for r in results:
            if r["id"] in fetch_times:
                r["updated_at"] = fetch_times[r["id"]]

        # 补充没有价格数据的新饰品
        existing_ids = {r["id"] for r in results}
        all_items = await get_monitored_items(db)
        item_meta = {item["id"]: item for item in all_items}
        for r in results:
            meta = item_meta.get(r["id"], {})
            r["current_price"] = meta.get("latest_quote_price")
        for item in all_items:
            if item["id"] not in existing_ids:
                results.append({
                    "id": item["id"],
                    "market_hash_name": item["market_hash_name"],
                    "name_cn": item.get("name_cn") or item["market_hash_name"],
                    "icon_url": item.get("icon_url") or "",
                    "rarity": item.get("rarity") or "",
                    "current_price": item.get("latest_quote_price"),
                    "volume_24h": 0,
                    "updated_at": item.get("latest_quote_at") or item.get("updated_at"),
                    "trend": {},
                    "score": 0,
                    "recommendation": "-",
                    "reason": "暂无价格数据",
                    "analysis": {},
                })

        if q:
            q_lower = q.lower()
            results = [
                r for r in results
                if q_lower in (r.get("name_cn") or "").lower()
                or q_lower in (r.get("market_hash_name") or "").lower()
            ]
        resp = {"code": 0, "data": results, "total": len(results)}
        _cache[cache_key] = (now, resp, _cache_version)
        return resp
    finally:
        await db.close()


@app.get("/api/items/search")
async def search_steam_items(q: str = Query(""), limit: int = Query(20)):
    """搜索 Steam 市场饰品。"""
    async with SteamScraper(delay=1.0) as scraper:
        results = await scraper.search_items(q, limit=limit)
    return {"code": 0, "data": results}


@app.get("/api/items/favorites")
async def fav_list():
    db = await get_db()
    try:
        ids = await get_favorite_ids(db)
        return {"code": 0, "data": list(ids)}
    finally:
        await db.close()


@app.get("/api/items/{item_id}")
async def get_item_detail(item_id: int):
    """获取单个饰品的详细分析。"""
    db = await get_db()
    try:
        item = await get_item_by_id(db, item_id)
        if not item:
            return {"code": 1, "message": "饰品不存在"}
        history_rows = await get_item_history(db, item_id, days=360)
        target = engine.analyze_one(history_rows, dict(item))
        try:
            daily_rows = await get_daily_summary(db, item_id, days=360)
        except Exception:
            daily_rows = []
        if not target:
            target = {
                "id": item["id"],
                "market_hash_name": item["market_hash_name"],
                "name_cn": item.get("name_cn") or item["market_hash_name"],
                "icon_url": item.get("icon_url") or "",
                "rarity": item.get("rarity") or "",
                "current_price": item.get("latest_quote_price"),
                "volume_24h": 0,
                "updated_at": item.get("latest_quote_at") or item.get("updated_at"),
                "trend": {},
                "score": 0,
                "recommendation": "-",
                "reason": "暂无数据",
                "analysis": {},
            }
        target["daily"] = daily_rows
        target["current_price"] = item.get("latest_quote_price")
        cursor2 = await db.execute("SELECT updated_at FROM items WHERE id = ?", (item_id,))
        row2 = await cursor2.fetchone()
        if row2 and row2[0]:
            target["updated_at"] = row2[0]
        
        return {"code": 0, "data": target}
    finally:
        await db.close()


@app.get("/api/items/{item_id}/history")
async def item_history(item_id: int, days: int = Query(90)):
    """获取单个饰品的历史价格数据。"""
    db = await get_db()
    try:
        rows = await get_item_history(db, item_id, days=days)
        return {"code": 0, "data": rows, "total": len(rows)}
    finally:
        await db.close()



## ------------------------------------------------------------------
# API: 推荐
# ------------------------------------------------------------------

@app.get("/api/recommendations")
async def get_recommendations(min_score: int = Query(0), recommend_only: bool = Query(True)):
    """获取推荐购买列表。"""
    db = await get_db()
    try:
        rows = await get_steam_history(db, days=90)
        engine.load_history(rows)
        results = engine.recommendations(min_score=min_score, recommend_only=recommend_only)
        return {"code": 0, "data": results, "total": len(results)}
    finally:
        await db.close()


@app.get("/api/backtest")
async def get_backtest(
    horizon_days: int = Query(7, ge=1, le=60),
    min_score: int = Query(75, ge=0, le=500),
    days: int = Query(360, ge=30, le=720),
):
    """Run a simple forward-return backtest for historical scoring signals."""
    db = await get_db()
    try:
        rows = await get_backtest_history(db, days=days)
        cache_key = f"backtest:{horizon_days}:{min_score}:{days}:{_cache_version}"
        now = _time.time()
        if cache_key in _backtest_cache and now - _backtest_cache[cache_key][0] < _cache_ttl:
            return {"code": 0, "data": _backtest_cache[cache_key][1]}
        result = engine.backtest(rows, horizon_days=horizon_days, min_score=min_score)
        _backtest_cache[cache_key] = (now, result)
        return {"code": 0, "data": result}
    finally:
        await db.close()


# ------------------------------------------------------------------
# API: 数据抓取
# ------------------------------------------------------------------



@app.get("/api/fetch/{item_id}")
async def fetch_single(item_id: int):
    """单独更新一个饰品的数据。"""
    global _cache_version
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT market_hash_name, name_cn FROM items WHERE id = ?", (item_id,)
        )
        row = await cursor.fetchone()
        if not row:
            return {"code": 1, "message": "饰品不存在"}

        name_cn = row[1] or row[0]
        _log("单刷", f"开始 | {_short_name(name_cn)}")
        async with SteamScraper(delay=2.0) as scraper:
            price = await scraper.get_price(row[0])
            listing_result = await save_steam_history(db, scraper, item_id, row[0])
            history_count = listing_result["history_count"]
            checked_price, quote_status = _validate_quote_price(price, listing_result.get("orderbook"))
            if checked_price and checked_price.get("sell_price"):
                now_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                two_min_ago = (datetime.now(timezone.utc) - timedelta(minutes=2)).strftime("%Y-%m-%d %H:%M:%S")
                cursor2 = await db.execute(
                    "SELECT COUNT(*) FROM price_snapshots WHERE item_id = ? AND platform = ? AND snapshot_type = 'quote' AND updated_at >= ?",
                    (item_id, "steam", two_min_ago),
                )
                if (await cursor2.fetchone())[0] == 0:
                    await upsert_price(
                        db, item_id, "steam",
                        checked_price.get("buy_price"),
                        checked_price.get("sell_price"),
                        checked_price.get("volume_24h", 0),
                        now_ts,
                        snapshot_type="quote",
                    )
                _log("单刷", f"现价 | {_short_name(name_cn)} | {_price_label(checked_price.get('sell_price'))} | {quote_status}")
            else:
                _log("单刷", f"跳过 | {_short_name(name_cn)} | quote {quote_status}")
        now_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        market_time = listing_result.get("market_updated_at") or (now_ts if checked_price and checked_price.get("sell_price") else None)
        await update_item_market_metadata(
            db,
            item_id,
            fetched_at=now_ts,
            market_updated_at=market_time,
            orderbook=listing_result.get("orderbook"),
            orderbook_updated_at=now_ts,
        )
        await db.commit()
        await log_fetch(db, "steam", "ok", history_count)
        _cache.clear()
        _cache_version += 1
        _log("单刷", f"完成 | {_short_name(name_cn)} | 现价 {_price_label(checked_price.get('sell_price') if checked_price else None)} | 成交点 {history_count}")
        return {"code": 0, "message": "更新完成", "history": history_count}
    finally:
        await db.close()
@app.get("/api/fetch")
async def trigger_fetch(
    limit: int = Query(300),
    discover: bool = Query(True),
    delay: float = Query(3.0),
    min_score: int = Query(0),
    item_ids: str = Query(""),
):
    """批量更新所有饰品数据 (SSE 流，后台任务)。"""
    global _update_running, _update_task, _update_events

    queue = asyncio.Queue(maxsize=1000)
    _update_subscribers.add(queue)
    selected_item_ids = _parse_item_ids(item_ids)

    if _update_task is None or _update_task.done():
        _update_events = []
        _update_task = asyncio.create_task(_run_fetch(limit, discover, delay, min_score, selected_item_ids))
    else:
        for event in list(_update_events):
            _queue_update_event(queue, event)

    async def event_stream():
        try:
            while True:
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=30)
                    yield _sse(msg)
                    if msg.get("type") in ("done", "error"):
                        break
                except asyncio.TimeoutError:
                    if _update_task.done():
                        break
                    yield _sse({"type": "ping"})
        except asyncio.CancelledError:
            pass
        finally:
            _update_subscribers.discard(queue)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


def _parse_item_ids(value: str | None) -> set[int] | None:
    if value is None:
        return None
    ids = set()
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            item_id = int(part)
        except ValueError:
            continue
        if item_id > 0:
            ids.add(item_id)
    return ids


def _queue_update_event(queue: asyncio.Queue, data: dict) -> None:
    if queue.full():
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            pass
    try:
        queue.put_nowait(data)
    except asyncio.QueueFull:
        pass


async def _publish_update(data: dict):
    """Broadcast one update event to every active SSE subscriber."""
    _update_events.append(data)
    if len(_update_events) > _update_event_limit:
        del _update_events[: len(_update_events) - _update_event_limit]
    for subscriber in list(_update_subscribers):
        _queue_update_event(subscriber, data)


async def _run_fetch(limit: int, discover: bool, delay: float, min_score: int, item_ids: set[int] | None = None):
    """Run the Steam batch update through the dedicated runner module."""
    global _update_running, _cache_version, _backtest_cache
    _update_running = True
    options = SteamUpdateOptions(
        limit=limit,
        discover=discover,
        delay=delay,
        min_score=min_score,
        item_ids=item_ids,
    )
    try:
        runner = SteamUpdateRunner()
        await runner.run(options, event_sink=_publish_update, log_sink=_log)
    finally:
        _update_running = False
        _cache.clear()
        _backtest_cache.clear()
        _cache_version += 1

@app.post("/api/fix-names")
async def fix_names():
    """修复饰品中文名称。"""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT id, market_hash_name FROM items WHERE name_cn IS NULL OR name_cn = ''"
        )
        rows = await cursor.fetchall()
        await update_all_chinese_names(db)
        updated = 0
        async with SteamScraper(delay=2.0) as scraper:
            for row in rows:
                try:
                    official_cn = await scraper.get_item_name_cn(row[1])
                    if official_cn and official_cn != row[1]:
                        await db.execute("UPDATE items SET name_cn = ? WHERE id = ?", (official_cn, row[0]))
                        updated += 1
                except Exception:
                    continue
        await db.commit()
        return {"code": 0, "message": f"已更新 {updated} 个饰品名称"}
    finally:
        await db.close()




# ------------------------------------------------------------------
# API: 价格预警
# ------------------------------------------------------------------

@app.put("/api/items/{item_id}/alert")
async def set_item_alert(item_id: int, target_price: float = Body(..., embed=True)):
    """设置饰品价格预警。"""
    if target_price <= 0:
        return {"code": 1, "message": "目标价必须大于 0"}
    db = await get_db()
    try:
        await set_alert(db, item_id, target_price)
        return {"code": 0, "data": {"item_id": item_id, "target_price": target_price}, "message": "预警已保存"}
    finally:
        await db.close()


@app.get("/api/items/{item_id}/alert")
async def get_item_alert(item_id: int):
    """获取饰品价格预警。"""
    db = await get_db()
    try:
        alert = await get_alert(db, item_id)
        return {"code": 0, "data": alert}
    finally:
        await db.close()


@app.delete("/api/items/{item_id}/alert")
async def remove_item_alert(item_id: int):
    """删除饰品价格预警。"""
    db = await get_db()
    try:
        await delete_alert(db, item_id)
        return {"code": 0, "message": "预警已删除"}
    finally:
        await db.close()



@app.get("/api/alerts/all")
async def all_alerts():
    """获取所有已设置预警的饰品 ID。"""
    db = await get_db()
    try:
        alerts = await get_all_alerts(db)
        return {"code": 0, "data": alerts}
    finally:
        await db.close()

@app.get("/api/alerts/triggered")
async def triggered_alerts():
    """获取所有已触发的价格预警。"""
    db = await get_db()
    try:
        alerts = await get_triggered_alerts(db)
        return {"code": 0, "data": alerts}
    finally:
        await db.close()


# ------------------------------------------------------------------
# API: 饰品管理
# ------------------------------------------------------------------

@app.delete("/api/items/{item_id}")
async def remove_item(item_id: int):
    """删除饰品及其所有价格数据。"""
    db = await get_db()
    try:
        ok = await delete_item(db, item_id)
        if ok:
            return {"code": 0, "message": "已删除"}
        return {"code": 1, "message": "饰品不存在"}
    finally:
        await db.close()


@app.post("/api/admin/clear-data")
async def clear_data(confirm: bool = Body(False, embed=True)):
    """Clear all monitored items and related local data after explicit confirmation."""
    global _cache_version, _update_events, _backtest_cache
    if not confirm:
        return {"code": 1, "message": "confirm required"}
    if _update_running:
        return {"code": 1, "message": "更新任务运行中，请完成后再清空数据"}
    db = await get_db()
    try:
        result = await clear_all_data(db)
        _cache.clear()
        _backtest_cache.clear()
        _update_events = []
        _cache_version += 1
        return {"code": 0, "data": result, "message": "数据已清空"}
    finally:
        await db.close()


@app.post("/api/items")
async def add_item(
    market_hash_name: str = Body(...),
    name_cn: str = Body(""),
    icon_url: str = Body(""),
    rarity: str = Body(""),
):
    """添加饰品到监控列表。"""
    global _cache_version
    if not market_hash_name:
        return {"code": 1, "message": "market_hash_name 不能为空"}
    db = await get_db()
    try:
        # 检查是否已存在
        cursor = await db.execute(
            "SELECT id FROM items WHERE market_hash_name = ?", (market_hash_name,)
        )
        existing = await cursor.fetchone()
        if existing:
            return {"code": 1, "message": "该饰品已在监控列表中"}
        
        item_id = await get_or_create_item(
            db,
            market_hash_name,
            name_cn=name_cn,
            icon_url=icon_url,
            rarity=rarity,
        )
        await db.commit()

        # 添加后立即抓取历史成交与 priceoverview 现价。
        try:
            async with SteamScraper(delay=1.0) as scraper:
                listing = await scraper.get_listing_data(market_hash_name, days=90)
                history = listing.get("history") or []
                now_ts3 = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                if history:
                    for h in history:
                        await upsert_price(
                            db, item_id, "steam",
                            buy_price=h.get("buy_price") or h["sell_price"],
                            sell_price=h["sell_price"],
                            volume_24h=h.get("volume_24h") or 0,
                            updated_at=h.get("updated_at"),
                        )
                    await compute_daily_summary(db, item_id)
                    await update_item_market_metadata(
                        db,
                        item_id,
                        fetched_at=now_ts3,
                        market_updated_at=history[-1].get("updated_at"),
                        orderbook=listing.get("orderbook"),
                        orderbook_updated_at=now_ts3,
                    )
                    await db.commit()
                price_data = await scraper.get_price(market_hash_name)
                checked_price, quote_status = _validate_quote_price(price_data, listing.get("orderbook"))
                if checked_price and checked_price.get("sell_price"):
                    now_ts3 = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                    await upsert_price(
                        db, item_id, "steam",
                        buy_price=checked_price.get("buy_price") or checked_price["sell_price"],
                        sell_price=checked_price["sell_price"],
                        volume_24h=checked_price.get("volume_24h") or 0,
                        updated_at=now_ts3,
                        snapshot_type="quote",
                    )
                    await update_item_market_metadata(
                        db,
                        item_id,
                        fetched_at=now_ts3,
                        market_updated_at=history[-1].get("updated_at") if history else now_ts3,
                        orderbook=listing.get("orderbook"),
                        orderbook_updated_at=now_ts3,
                    )
                    await db.commit()
                    _log("添加", f"现价 | {_short_name(name_cn)} | {_price_label(checked_price.get('sell_price'))} | {quote_status}")
                elif not history:
                    await update_item_market_metadata(
                        db,
                        item_id,
                        fetched_at=now_ts3,
                        orderbook=listing.get("orderbook"),
                        orderbook_updated_at=now_ts3,
                    )
                    await db.commit()
        except Exception as e:
            _log("添加", f"失败 | {_short_name(market_hash_name)} | {e}")

        _cache.clear()
        _cache_version += 1
        _backtest_cache.clear()
        return {"code": 0, "data": {"id": item_id}, "message": "已添加"}
    finally:
        await db.close()


# ------------------------------------------------------------------
# API: 收藏
# ------------------------------------------------------------------

@app.put("/api/items/{item_id}/favorite")
async def fav_toggle(item_id: int):
    db = await get_db()
    try:
        val = await toggle_favorite(db, item_id)
        if val is None:
            return {"code": 1, "message": "饰品不存在"}
        return {"code": 0, "data": {"item_id": item_id, "favorite": val}}
    finally:
        await db.close()


@app.get("/api/stats")
async def get_stats():
    """获取监控统计信息。"""
    db = await get_db()
    try:
        stats = await get_monitor_stats(db)
        return {"code": 0, "data": stats}
    finally:
        await db.close()


# ------------------------------------------------------------------
# 静态文件 (放在最后，避免拦截 API 路由)
# ------------------------------------------------------------------

app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


# ------------------------------------------------------------------
# 工具


# ------------------------------------------------------------------
# API: 周期性分析
# ------------------------------------------------------------------

@app.get("/api/items/{item_id}/periodic")
async def periodic_analysis(item_id: int, days: int = Query(180)):
    """获取饰品的周期性价格规律分析。"""
    db = await get_db()
    try:
        result = await get_periodic_analysis(db, item_id, days)
        return {"code": 0, "data": result}
    finally:
        await db.close()


# ------------------------------------------------------------------
# API: 买入记录
# ------------------------------------------------------------------

@app.post("/api/items/{item_id}/purchase")
async def add_item_purchase(
    item_id: int,
    buy_price: float = Body(...),
    quantity: int = Body(1),
    buy_date: str = Body(None),
    notes: str = Body(None),
):
    """记录一次买入。"""
    if buy_price <= 0:
        return {"code": 1, "message": "买入价必须大于 0"}
    db = await get_db()
    try:
        pid = await add_purchase(db, item_id, buy_price, quantity, buy_date, notes)
        return {"code": 0, "data": {"id": pid}, "message": "买入记录已保存"}
    finally:
        await db.close()


@app.get("/api/purchases")
async def list_purchases():
    """获取所有买入记录及盈亏。"""
    db = await get_db()
    try:
        records = await get_purchases(db)
        return {"code": 0, "data": records}
    finally:
        await db.close()


@app.delete("/api/purchases/{purchase_id}")
async def remove_purchase(purchase_id: int):
    """删除买入记录。"""
    db = await get_db()
    try:
        ok = await delete_purchase(db, purchase_id)
        if ok:
            return {"code": 0, "message": "已删除"}
        return {"code": 1, "message": "记录不存在"}
    finally:
        await db.close()


# ------------------------------------------------------------------

def _sse(data: dict) -> str:
    """格式化 SSE 事件。"""
    event_type = data.get("type", "message")
    return "event: " + event_type + "\n" + "data: " + json.dumps(data, ensure_ascii=False) + "\n\n"


if __name__ == "__main__":
    import uvicorn
    from config import settings

    uvicorn.run("main:app", host=settings.host, port=settings.port, reload=True)
