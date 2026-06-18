"""Shared price semantics for Steam market snapshots.

The app stores two different market facts in one snapshot table:
- trade: Steam listing history points, used for charts, summaries, scoring, and backtests.
- quote: priceoverview current lowest sell price, used as the displayed current price.
"""
from __future__ import annotations

from typing import Any

TRADE_SNAPSHOT = "trade"
QUOTE_SNAPSHOT = "quote"
QUOTE_LOW_TOLERANCE = 0.02
QUOTE_HIGH_TOLERANCE = 0.03


def normalize_snapshot_type(value: str | None) -> str:
    return value or TRADE_SNAPSHOT


def is_trade_snapshot(value: str | None) -> bool:
    return normalize_snapshot_type(value) == TRADE_SNAPSHOT


def is_quote_snapshot(value: str | None) -> bool:
    return normalize_snapshot_type(value) == QUOTE_SNAPSHOT


def snapshot_type_sql(column: str = "snapshot_type") -> str:
    return f"COALESCE({column}, '{TRADE_SNAPSHOT}')"


def current_price_from_quote(record: dict[str, Any]) -> float | None:
    value = record.get("latest_quote_price")
    if value is None:
        return None
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    return price if price > 0 else None


def orderbook_lowest_price(orderbook: dict[str, Any] | None) -> float | None:
    if not isinstance(orderbook, dict):
        return None
    levels = orderbook.get("levels")
    if not isinstance(levels, list) or not levels:
        return None
    prices = []
    for level in levels:
        try:
            price = float(level.get("price"))
        except (TypeError, ValueError, AttributeError):
            continue
        if price > 0:
            prices.append(price)
    return min(prices) if prices else None


def validate_quote_price(price_data: dict[str, Any] | None, orderbook: dict[str, Any] | None) -> tuple[dict[str, Any] | None, str]:
    """Validate priceoverview against orderbook without replacing it.

    priceoverview remains the current-price source. Orderbook can only annotate
    the quote as unusually low/high so the UI and logs can explain the mismatch.
    """
    if not price_data or not price_data.get("sell_price"):
        return None, "missing"
    checked = dict(price_data)
    checked.setdefault("quote_source", "priceoverview")
    orderbook_low = orderbook_lowest_price(orderbook)
    if orderbook_low is None:
        return checked, "unchecked"

    quote_price = float(checked["sell_price"])
    if quote_price < orderbook_low * (1 - QUOTE_LOW_TOLERANCE):
        checked["orderbook_lowest"] = orderbook_low
        return checked, f"priceoverview_primary_low quote={quote_price:.2f} orderbook={orderbook_low:.2f}"
    if quote_price > orderbook_low * (1 + QUOTE_HIGH_TOLERANCE):
        checked["orderbook_lowest"] = orderbook_low
        return checked, f"priceoverview_primary_high quote={quote_price:.2f} orderbook={orderbook_low:.2f}"
    return checked, "ok"
