"""Shared price semantics for Steam market snapshots.

The app stores two different market facts in one snapshot table:
- trade: Steam listing history points, used for charts, summaries, scoring, and backtests.
- quote: priceoverview current lowest sell price, used as the displayed current price.
"""
from __future__ import annotations

from typing import Any

TRADE_SNAPSHOT = "trade"
QUOTE_SNAPSHOT = "quote"


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
