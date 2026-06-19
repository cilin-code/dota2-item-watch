"""Display helpers for CMD logs and compact labels."""
from __future__ import annotations

import unicodedata


def _display_width(value: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in ("F", "W") else 1 for ch in value)


def _truncate_display(value: str, width: int) -> str:
    if _display_width(value) <= width:
        return value
    if width <= 3:
        out = ""
        used = 0
        for ch in value:
            ch_width = _display_width(ch)
            if used + ch_width > width:
                break
            out += ch
            used += ch_width
        return out
    out = ""
    used = 0
    for ch in value:
        ch_width = _display_width(ch)
        if used + ch_width > width - 3:
            break
        out += ch
        used += ch_width
    return out + "..."


def _pad_display(value: str | None, width: int, align: str = "left") -> str:
    text = _truncate_display(value or "-", width)
    padding = max(0, width - _display_width(text))
    if align == "right":
        return " " * padding + text
    return text + " " * padding


def _short_name(value: str | None, limit: int = 34) -> str:
    return _truncate_display(value or "-", limit)


def _price_label(value) -> str:
    if value is None:
        return "未获取"
    try:
        return f"¥{float(value):.2f}"
    except (TypeError, ValueError):
        return f"¥{value}"
