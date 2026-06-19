"""Steam Community Market scraper for Dota 2 items."""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import httpx

from .base import BaseScraper


def _log(section: str, message: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {_pad_display(section, 4)} | {message}", flush=True)


def _display_width(value: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in ("F", "W") else 1 for ch in value)


def _pad_display(value: str | None, width: int) -> str:
    text = value or "-"
    padding = max(0, width - _display_width(text))
    return text + " " * padding


class SteamScraper(BaseScraper):
    """Fetch current prices, listing history, and sell order books from Steam."""

    BASE = "https://steamcommunity.com/market"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._jpy_to_cny: float | None = None

    def get_headers(self) -> dict:
        headers = super().get_headers()
        headers["Referer"] = "https://steamcommunity.com/market/"
        headers["Accept-Language"] = "zh-CN,zh;q=0.9"
        return headers

    async def _ensure_rate(self):
        """Resolve JPY to CNY once per scraper session."""
        if self._jpy_to_cny is not None:
            return
        urls = [
            ("https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/jpy.json", "jpy"),
            ("https://api.exchangerate-api.com/v4/latest/JPY", "rates"),
            ("https://open.er-api.com/v6/latest/JPY", "rates"),
        ]
        import asyncio as _a
        for url, key in urls:
            try:
                async with httpx.AsyncClient(timeout=8, headers={"User-Agent": "Mozilla/5.0"}) as c:
                    r = await c.get(url)
                    if r.status_code != 200:
                        continue
                    data = r.json()
                    if key == "jpy":
                        rate = data.get("jpy", {}).get("cny")
                    else:
                        rate = data.get("rates", {}).get("CNY")
                    if rate:
                        self._jpy_to_cny = float(rate)
                        _log("汇率", f"JPY -> CNY = {self._jpy_to_cny:.6f}")
                        return
            except Exception:
                continue
            await _a.sleep(0.5)
        self._jpy_to_cny = 1.0 / 21.5
        _log("汇率", "获取失败，使用备用汇率 1/21.5")

    async def get_price(self, market_hash_name: str) -> dict | None:
        """Fetch current lowest sell price in CNY using priceoverview."""
        url = f"{self.BASE}/priceoverview/"
        params = {
            "appid": 570,
            "currency": 23,
            "market_hash_name": market_hash_name,
        }
        import asyncio as _asyncio
        for attempt in range(3):
            try:
                resp = await self.fetch(url, params=params)
                if resp.status_code == 429:
                    if attempt < 2:
                        await _asyncio.sleep((attempt + 1) * 5)
                        continue
                    return None
                if resp.status_code != 200:
                    return None
                data = resp.json()
                if data and data.get("success"):
                    lowest = self._parse_price(data.get("lowest_price"))
                    median = self._parse_price(data.get("median_price"))
                    volume = int(str(data.get("volume", "0")).replace(",", ""))
                    if lowest is None:
                        return None
                    return {
                        "buy_price": lowest,
                        "sell_price": lowest,
                        "median_price": median,
                        "volume_24h": volume,
                    }
                return None
            except Exception:
                if attempt < 2:
                    await _asyncio.sleep(3)
                    continue
        return None

    async def get_listing_data(self, market_hash_name: str, days: int = 90) -> dict:
        """Fetch one listing page and parse both history and sell order book."""
        await self._ensure_rate()
        url = f"{self.BASE}/listings/570/{quote(market_hash_name)}"
        try:
            resp = await self.fetch(url)
            if resp.status_code == 429:
                return {"history": [], "orderbook": None, "rate_limited": True}
            if resp.status_code != 200:
                return {"history": [], "orderbook": None, "rate_limited": False}
            html = resp.text
        except Exception:
            return {"history": [], "orderbook": None, "rate_limited": False}

        rate = self._jpy_to_cny or (1.0 / 21.5)
        prices = self._extract_history_prices(html)
        return {
            "history": self._build_history(prices, days=days, rate=rate),
            "orderbook": self._extract_orderbook(html, rate=rate),
            "rate_limited": False,
        }

    async def get_price_history(self, market_hash_name: str, days: int = 90) -> list[dict]:
        """Fetch listing-page price history converted from JPY to CNY."""
        data = await self.get_listing_data(market_hash_name, days=days)
        return data["history"]

    async def get_orderbook(self, market_hash_name: str) -> dict | None:
        """Fetch current compact sell order book from the listing page."""
        data = await self.get_listing_data(market_hash_name, days=1)
        return data["orderbook"]

    async def search_items(self, keyword: str = "", limit: int = 50) -> list:
        """Search Dota 2 market items."""
        items = []
        start = 0
        while len(items) < limit:
            url = f"{self.BASE}/search/render/"
            params = {
                "appid": 570,
                "norender": 1,
                "count": min(100, limit),
                "start": start,
                "query": keyword,
                "sort_column": "popular",
                "sort_dir": "desc",
                "language": "schinese",
            }
            try:
                resp = await self.fetch(url, params=params)
                if resp.status_code != 200:
                    break
                try:
                    data = resp.json()
                except Exception:
                    break
                if not data.get("results"):
                    break
                for row in data["results"]:
                    asset = row.get("asset_description", {})
                    icon = asset.get("icon_url", "")
                    items.append({
                        "market_hash_name": row["hash_name"],
                        "name_cn": row.get("name", row["hash_name"]),
                        "icon_url": f"https://steamcommunity-a.akamaihd.net/economy/image/{icon}" if icon else "",
                        "rarity": asset.get("type", ""),
                    })
                if len(data["results"]) < 100:
                    break
                start += 100
            except Exception as exc:
                _log("Steam", f"搜索失败 | {exc}")
                break
        return items[:limit]

    async def get_top_items(self, limit: int = 100) -> list:
        """Fetch popular market items."""
        return await self.search_items("", limit)

    async def get_item_name_cn(self, market_hash_name: str) -> str:
        """Look up the official Chinese item name when available."""
        results = await self.search_items(market_hash_name, limit=3)
        for row in results:
            if row["market_hash_name"] == market_hash_name:
                return row["name_cn"]
        return market_hash_name

    @staticmethod
    def _parse_price(value: str | None) -> float | None:
        """Extract a numeric value from a Steam price string."""
        if not value:
            return None
        parsed = re.sub(r"[^0-9.]", "", value)
        return float(parsed) if parsed else None

    @staticmethod
    def _extract_history_prices(html: str) -> list[dict]:
        """Parse embedded listing price-history JSON."""
        match = re.search(r'(?:\\\\\\")prices(?:\\\\\\")\s*:\s*(\[.*?\])', html, re.DOTALL)
        if not match:
            return []
        raw = match.group(1).replace('\\\\\\"', '"').replace('\\/', '/')
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return []
        return data if isinstance(data, list) else []

    @staticmethod
    def _build_history(prices: list[dict], *, days: int, rate: float) -> list[dict]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        history = []
        for point in prices:
            timestamp = point.get("time")
            price_jpy = point.get("price_median")
            if not timestamp or not price_jpy:
                continue
            updated_at = datetime.fromtimestamp(timestamp, tz=timezone.utc)
            if updated_at < cutoff:
                continue
            price_cny = float(price_jpy) * rate
            history.append({
                "sell_price": round(price_cny, 2),
                "buy_price": round(price_cny, 2),
                "volume_24h": int(point.get("purchases") or 0),
                "updated_at": updated_at.strftime("%Y-%m-%d %H:%M:%S"),
            })
        return history

    @staticmethod
    def _extract_orderbook(html: str, *, rate: float) -> dict | None:
        """Parse Steam SSR compact sell orders and convert JPY minor units to CNY."""
        orders_match = re.search(
            r'(?:\\\\\\"|\\"|")rgCompactSellOrders(?:\\\\\\"|\\"|")\s*:\s*\[([0-9,\s]+)\]',
            html,
        )
        if not orders_match:
            return None

        values = []
        for value in orders_match.group(1).split(","):
            value = value.strip()
            if not value:
                continue
            try:
                values.append(int(value))
            except ValueError:
                return None

        levels = []
        for idx in range(0, len(values) - 1, 2):
            price_minor = values[idx]
            quantity = values[idx + 1]
            if price_minor <= 0 or quantity <= 0:
                continue
            price_jpy = price_minor / 100
            levels.append({
                "price": round(price_jpy * rate, 2),
                "quantity": quantity,
                "price_jpy": round(price_jpy, 2),
                "price_minor": price_minor,
            })

        if not levels:
            return None

        count_match = re.search(
            r'(?:\\\\\\"|\\"|")cSellOrders(?:\\\\\\"|\\"|")\s*:\s*(\d+)',
            html,
        )
        total = int(count_match.group(1)) if count_match else sum(level["quantity"] for level in levels)
        return {
            "source": "steam_listing",
            "currency": "CNY",
            "raw_currency": "JPY",
            "total_sell_orders": total,
            "levels": levels,
        }
