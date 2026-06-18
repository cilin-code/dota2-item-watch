"""Update admission policy for low-value Steam items."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

LOW_SCORE_LIMIT = 20.0


@dataclass(slots=True)
class UpdateDecision:
    allow: bool
    reason: str
    cooldown_hours: int | None = None
    update_after: str | None = None
    bypass: bool = False
    remaining_seconds: int = 0


def cooldown_hours_for_score(score: float) -> int | None:
    if score >= LOW_SCORE_LIMIT:
        return None
    if score >= 15:
        return 12
    if score >= 10:
        return 24
    if score >= 5:
        return 72
    return 168


def parse_db_time(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S"):
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def format_db_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def decide_update(
    item: dict[str, Any],
    *,
    score: float,
    now: datetime,
    hot_item_ids: set[int] | None = None,
    protected_item_ids: set[int] | None = None,
) -> UpdateDecision:
    item_id = int(item["id"])
    hot_item_ids = hot_item_ids or set()
    protected_item_ids = protected_item_ids or set()

    if item_id in hot_item_ids:
        return UpdateDecision(True, "Steam 热门命中", bypass=True)
    if int(item.get("favorite") or 0):
        return UpdateDecision(True, "收藏饰品", bypass=True)
    if item_id in protected_item_ids:
        return UpdateDecision(True, "买入或预警保护", bypass=True)
    if score >= LOW_SCORE_LIMIT:
        return UpdateDecision(True, "评分不低于 20")

    hours = cooldown_hours_for_score(score)
    update_after_at = parse_db_time(item.get("update_after"))
    if update_after_at and update_after_at > now:
        remaining = max(0, int((update_after_at - now).total_seconds()))
        return UpdateDecision(
            False,
            f"评分 {score:.1f} 低于 20，冷却中",
            cooldown_hours=hours,
            update_after=format_db_time(update_after_at),
            remaining_seconds=remaining,
        )

    next_update = now + timedelta(hours=hours or 0)
    return UpdateDecision(
        True,
        f"评分 {score:.1f} 低于 20，进入 {hours} 小时冷却",
        cooldown_hours=hours,
        update_after=format_db_time(next_update),
    )


def format_remaining(seconds: int) -> str:
    if seconds <= 0:
        return "已到期"
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    parts = []
    if days:
        parts.append(f"{days}天")
    if hours:
        parts.append(f"{hours}小时")
    if not parts and minutes:
        parts.append(f"{minutes}分钟")
    return "".join(parts) or "不到1分钟"
