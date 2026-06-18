"""Steam Dota 2 price-history analysis and purchase recommendation engine."""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta
from statistics import mean, stdev

from price_semantics import current_price_from_quote


class TrendEngine:
    WINDOWS = (3, 7, 15, 30, 60, 90)
    STEAM_TAX_NOMINAL = 0.13
    STEAM_TAX_THRESHOLD = 1.60
    STEAM_TAX_MIN_FEE = 0.208

    @classmethod
    def breakeven_multiplier(cls, price: float) -> float:
        if price >= cls.STEAM_TAX_THRESHOLD:
            return 1.0 / (1.0 - cls.STEAM_TAX_NOMINAL)
        net = price - cls.STEAM_TAX_MIN_FEE
        if net <= 0:
            return 999.0
        return price / net

    @classmethod
    def effective_tax_rate(cls, price: float) -> float:
        if price >= cls.STEAM_TAX_THRESHOLD:
            return cls.STEAM_TAX_NOMINAL
        return round(cls.STEAM_TAX_MIN_FEE / price, 4) if price > 0 else 1.0

    def __init__(self):
        self.items: list[dict] = []

    def load_history(self, rows: list[dict]):
        grouped = self._group_rows(rows)
        self.items = []
        for item_id, raw in grouped.items():
            raw.sort(key=lambda r: r.get("updated_at") or "")
            latest = raw[-1]
            volume_24h = int(latest.get("volume_24h") or 0)
            trend = self._build_trend(raw)
            analysis = self._analyze(raw, latest, trend, volume_24h)
            self.items.append(self._format_item(item_id, latest, trend, analysis, volume_24h))

    def analyze_one(self, rows, item_info):
        raw = []
        for row in rows:
            price = row.get("sell_price") or row.get("buy_price")
            if price and price > 0:
                raw.append({**row, "price": float(price)})
        if not raw:
            return None
        raw.sort(key=lambda r: r.get("updated_at") or "")
        latest = raw[-1]
        for key in ("orderbook_json", "orderbook_updated_at", "latest_quote_price", "latest_quote_at"):
            if item_info.get(key) and not latest.get(key):
                latest[key] = item_info.get(key)
        volume_24h = int(latest.get("volume_24h") or 0)
        trend = self._build_trend(raw)
        analysis = self._analyze(raw, latest, trend, volume_24h)
        item = self._format_item(item_info.get("id"), {**latest, **item_info}, trend, analysis, volume_24h)
        item["id"] = item_info.get("id")
        return item

    def recommendations(self, *, recommend_only: bool = False, min_score: int = 0) -> list[dict]:
        items = self.items
        if recommend_only:
            items = [i for i in items if i.get("analysis", {}).get("recommend")]
        elif min_score:
            items = [i for i in items if i.get("score", 0) >= min_score]
        return sorted(items, key=lambda i: (i.get("score", 0), i.get("volume_24h", 0)), reverse=True)

    def backtest(self, rows: list[dict], *, horizon_days: int = 7, min_score: int = 75) -> dict:
        grouped = self._group_rows(rows)
        trades = []
        max_checkpoints_per_item = 140
        for item_id, raw in grouped.items():
            raw.sort(key=lambda r: r.get("updated_at") or "")
            raw = self._daily_last_snapshots(raw)
            parsed = [(self._time(r.get("updated_at")), r) for r in raw]
            parsed = [(t, r) for t, r in parsed if t is not None]
            if len(parsed) < 12:
                continue
            raw = [r for _, r in parsed]
            times = [t for t, _ in parsed]
            step = max(1, len(raw) // max_checkpoints_per_item)
            for idx in range(5, len(raw) - 1, step):
                latest = raw[idx]
                latest_time = times[idx]
                target_time = latest_time + timedelta(days=horizon_days)
                future_idx = None
                lo, hi = idx + 1, len(times) - 1
                while lo <= hi:
                    mid = (lo + hi) // 2
                    if times[mid] >= target_time:
                        future_idx = mid
                        hi = mid - 1
                    else:
                        lo = mid + 1
                if future_idx is None:
                    continue
                future = raw[future_idx]
                history = raw[: idx + 1]
                trend = self._build_trend(history)
                analysis = self._analyze(history, latest, trend, int(latest.get("volume_24h") or 0))
                if analysis["score"] < min_score:
                    continue
                start = float(latest["price"])
                end = float(future["price"])
                trades.append({
                    "item_id": item_id,
                    "market_hash_name": latest.get("market_hash_name"),
                    "name_cn": latest.get("name_cn") or latest.get("market_hash_name"),
                    "at": latest.get("updated_at"),
                    "future_at": future.get("updated_at"),
                    "score": analysis["score"],
                    "rank": analysis["recommendation"],
                    "start_price": round(start, 2),
                    "future_price": round(end, 2),
                    "return_pct": round((end - start) / start * 100, 2) if start > 0 else 0,
                })
        returns = [t["return_pct"] for t in trades]
        wins = [r for r in returns if r > 0]
        return {
            "horizon_days": horizon_days,
            "min_score": min_score,
            "signals": len(trades),
            "win_rate": round(len(wins) / len(trades) * 100, 1) if trades else 0,
            "avg_return_pct": round(mean(returns), 2) if returns else 0,
            "best_return_pct": round(max(returns), 2) if returns else 0,
            "worst_return_pct": round(min(returns), 2) if returns else 0,
            "samples": trades[-50:],
        }

    def _format_item(self, item_id, latest, trend, analysis, volume_24h):
        return {
            "id": item_id,
            "market_hash_name": latest.get("market_hash_name", ""),
            "name_cn": latest.get("name_cn") or latest.get("market_hash_name", ""),
            "icon_url": latest.get("icon_url") or "",
            "rarity": latest.get("rarity") or "",
            "current_price": current_price_from_quote(latest),
            "volume_24h": volume_24h,
            "updated_at": latest.get("updated_at"),
            "trend": trend,
            "score": analysis["score"],
            "recommendation": analysis["recommendation"],
            "reason": analysis["reason"],
            "analysis": {k: analysis[k] for k in (
                "cv", "slope", "r_squared", "status", "volume_class", "price_percentile",
                "recent_percentile", "ma7", "ma30", "bb_upper", "bb_lower", "pressure",
                "pressure_source", "orderbook_count", "smart_price", "recommend", "confidence",
                "low_volume_risk", "low_sample_risk", "reject_reasons", "reason_details",
                "outlier_count", "anomaly_detected",
            )},
        }

    def _analyze(self, raw, latest, trend, volume_24h):
        market_price = round(float(latest.get("latest_quote_price") or latest["price"]), 2)
        all_prices = [float(s["price"]) for s in raw]
        clean_prices = self._clean_prices(all_prices)
        outlier_count = max(0, len(all_prices) - len(clean_prices))
        base = self._base_analysis(market_price, clean_prices, volume_24h, outlier_count)
        if len(clean_prices) < 5:
            return self._finish_reject(base, trend, "历史样本不足")
        if volume_24h <= 0:
            return self._finish_reject(base, trend, "无近期成交量")

        volume_class = "LIQUID" if volume_24h >= 5 else "THIN"
        avg = mean(clean_prices)
        sigma = stdev(clean_prices) if len(clean_prices) >= 2 else 0
        cv = round(sigma / avg, 6) if avg > 0 else None
        price_percentile = self._price_rank(clean_prices, market_price)
        recent_percentile = self._recent_percentile(raw, market_price)
        daily_prices = self._daily_avg_prices(raw)
        slope, r2 = self._linear_regression(daily_prices[-7:])
        status = self._status(slope, r2)
        ma7 = self._ema(daily_prices, 7)
        ma30 = self._ema(daily_prices, 30)
        bb_sigma = stdev(daily_prices[-30:]) if len(daily_prices[-30:]) >= 2 else 0
        bb_upper, bb_lower = self._bollinger(ma30, bb_sigma)
        orderbook = self._orderbook_from_record(latest)
        pressure_source = "real" if orderbook else "synthetic"
        pressure = self._sell_pressure(current_price=market_price, daily_volume=volume_24h, orderbook=orderbook)
        smart_price = self._smart_price(current_price=market_price, daily_volume=volume_24h, volume_class=volume_class, orderbook=orderbook)

        reject_reasons = []
        if cv is not None and cv > (0.18 if volume_class == "LIQUID" else 0.12):
            reject_reasons.append("价格波动过大")
        if status == "FALLING":
            reject_reasons.append("趋势持续下跌")
        if price_percentile is not None and price_percentile > (0.8 if volume_class == "LIQUID" else 0.7):
            reject_reasons.append("处于历史高位")
        if pressure is not None and pressure > (2.0 if volume_class == "LIQUID" else 1.5):
            reject_reasons.append("卖压过重")

        score, recommendation, reason = self._score_simple(
            market_price=market_price,
            trend=trend,
            volume_24h=volume_24h,
            volume_class=volume_class,
            cv=cv,
            price_percentile=price_percentile,
            recent_percentile=recent_percentile,
            status=status,
            pressure=pressure,
            reject=bool(reject_reasons),
            reject_reasons=reject_reasons,
        )
        return {
            **base,
            "cv": cv,
            "slope": slope,
            "slope_lt": slope,
            "r_squared": r2,
            "status": status,
            "volume_class": volume_class,
            "price_percentile": price_percentile,
            "recent_percentile": recent_percentile,
            "ma7": ma7,
            "ma30": ma30,
            "bb_upper": bb_upper,
            "bb_lower": bb_lower,
            "pressure": pressure,
            "pressure_source": pressure_source,
            "orderbook_count": len(orderbook or []),
            "smart_price": smart_price,
            "recommend": not reject_reasons,
            "confidence": self._confidence(len(clean_prices), volume_class),
            "low_volume_risk": volume_class == "THIN",
            "low_sample_risk": len(clean_prices) < 15,
            "reject_reasons": reject_reasons,
            "reason_details": self._reason_details(reason, reject_reasons),
            "score": score,
            "recommendation": recommendation,
            "reason": reason,
            "anomaly_detected": outlier_count > 0,
        }

    def _base_analysis(self, current_price, clean_prices, volume_24h, outlier_count):
        return {
            "current_price": current_price,
            "cv": None,
            "slope": None,
            "slope_lt": None,
            "r_squared": None,
            "status": None,
            "volume_class": None,
            "price_percentile": None,
            "recent_percentile": None,
            "ma7": None,
            "ma30": None,
            "bb_upper": None,
            "bb_lower": None,
            "pressure": None,
            "pressure_source": "synthetic",
            "orderbook_count": 0,
            "smart_price": self._smart_price(current_price=current_price, daily_volume=volume_24h, volume_class="LIQUID"),
            "recommend": False,
            "confidence": self._confidence(len(clean_prices), None),
            "low_volume_risk": False,
            "low_sample_risk": len(clean_prices) < 15,
            "reject_reasons": [],
            "reason_details": [],
            "outlier_count": outlier_count,
            "anomaly_detected": outlier_count > 0,
        }

    def _finish_reject(self, base, trend, reason):
        score, recommendation, display_reason = self._score_simple(
            market_price=base["current_price"], trend=trend, volume_24h=0,
            reject=True, reject_reasons=[reason]
        )
        return {
            **base,
            "reject_reasons": [reason],
            "reason_details": self._reason_details(display_reason, [reason]),
            "score": score,
            "recommendation": recommendation,
            "reason": display_reason,
        }

    def _score_simple(self, *, market_price, trend, volume_24h, volume_class=None, cv=None,
                      price_percentile=None, recent_percentile=None, status=None, pressure=None,
                      reject=False, reject_reasons=None):
        score = 50
        reasons = []
        warnings = list(reject_reasons or [])
        def pct_label(value):
            if value is None:
                return ""
            return f" {max(0, min(100, round(value * 100)))}%"

        if price_percentile is not None:
            if price_percentile <= 0.2:
                score += 25
                reasons.append("历史低位" + pct_label(price_percentile))
            elif price_percentile <= 0.4:
                score += 10
                reasons.append("价格偏低" + pct_label(price_percentile))
            elif price_percentile > 0.8:
                score -= 20
                warnings.append("历史高位" + pct_label(price_percentile))
        if recent_percentile is not None and recent_percentile <= 0.2:
            score += 8
            reasons.append("近期低位确认")
        if status == "STABLE":
            score += 10
            reasons.append("走势稳定")
        elif status == "RISING":
            score += 6
            reasons.append("趋势向上")
        elif status == "FALLING":
            score -= 12
            warnings.append("下跌趋势")
        if volume_24h >= 50:
            score += 12
            reasons.append("高流动性")
        elif volume_24h >= 20:
            score += 8
        elif volume_24h < 5:
            score -= 6
            warnings.append("成交量较低")
        if cv is not None and cv > 0.15:
            score -= 10
            warnings.append("波动偏高")
        if pressure is not None and pressure > 1.2:
            score -= 6
            warnings.append("卖压偏高")
        if volume_class == "THIN":
            score -= 5
            warnings.append("冷门饰品")
        if reject:
            score -= 25
        score = max(0, round(score))
        if score >= 120:
            rec = "S"
        elif score >= 100:
            rec = "A"
        elif score >= 85:
            rec = "B"
        elif score >= 70:
            rec = "C"
        elif score >= 55:
            rec = "D"
        else:
            rec = "E"
        parts = reasons + warnings[:3]
        return score, rec, "；".join(parts or ["趋势信号不足"])

    def _reason_details(self, reason, reject_reasons=None):
        details = []
        for text in reject_reasons or []:
            details.append({"type": "reject", "level": "danger", "text": text})
        for text in [p.strip() for p in (reason or "").replace("，", "；").split("；") if p.strip()]:
            if any(k in text for k in ("低位", "偏低", "稳定", "向上")):
                kind, level = "opportunity", "good"
            elif any(k in text for k in ("风险", "过高", "过大", "下跌", "冷门", "卖压", "不足", "高位", "波动")):
                kind, level = "risk", "warn"
            elif any(k in text for k in ("成交", "流动")):
                kind, level = "liquidity", "info"
            else:
                kind, level = "signal", "info"
            if not any(d["text"] == text for d in details):
                details.append({"type": kind, "level": level, "text": text})
        return details[:8]

    def _group_rows(self, rows):
        grouped = defaultdict(list)
        for row in rows:
            price = row.get("sell_price") or row.get("buy_price")
            if price and price > 0:
                grouped[row["id"]].append({**row, "price": float(price)})
        return grouped

    def _daily_last_snapshots(self, rows):
        by_day = {}
        for row in rows:
            t = self._time(row.get("updated_at"))
            if not t:
                continue
            by_day[t.strftime("%Y-%m-%d")] = row
        return [by_day[k] for k in sorted(by_day)] or rows

    def _build_trend(self, snapshots):
        latest = snapshots[-1]
        latest_time = self._time(latest.get("updated_at")) or datetime.utcnow()
        trend = {}
        for days in self.WINDOWS:
            since = latest_time - timedelta(days=days)
            window = [s for s in snapshots if (self._time(s.get("updated_at")) or latest_time) >= since]
            prices = [float(s["price"]) for s in window] or [float(latest["price"])]
            baseline = self._baseline(snapshots, since)
            trend[str(days)] = {
                "change_pct": self._pct(float(baseline["price"]), float(latest["price"])) if baseline else None,
                "start_price": round(float(baseline["price"]), 2) if baseline else None,
                "avg_price": round(mean(prices), 2),
                "low_price": round(min(prices), 2),
                "high_price": round(max(prices), 2),
                "snapshots": len(window),
                "coverage_days": days,
                "enough_history": baseline is not None,
            }
        return trend

    def _clean_prices(self, prices):
        if len(prices) < 4:
            return list(prices)
        s = sorted(prices)
        q1 = self._percentile(s, 0.25)
        q3 = self._percentile(s, 0.75)
        iqr = q3 - q1
        buffer = max(0.5, mean(prices) * 0.05)
        effective = max(iqr, buffer)
        lower = q1 - 1.5 * effective
        upper = q3 + 1.5 * effective
        clean = [p for p in prices if lower <= p <= upper]
        return clean or list(prices)

    def _daily_avg_prices(self, snapshots):
        bucket = defaultdict(list)
        for s in snapshots:
            t = self._time(s.get("updated_at"))
            if t:
                bucket[t.strftime("%Y-%m-%d")].append(float(s["price"]))
        return [mean(bucket[k]) for k in sorted(bucket)] or [float(snapshots[-1]["price"])]

    def _linear_regression(self, values):
        if len(values) < 2:
            return None, None
        xs = list(range(len(values)))
        xbar = mean(xs)
        ybar = mean(values)
        denom = sum((x - xbar) ** 2 for x in xs)
        if denom == 0:
            return 0.0, 0.0
        slope = sum((x - xbar) * (y - ybar) for x, y in zip(xs, values)) / denom
        intercept = ybar - slope * xbar
        ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(xs, values))
        ss_tot = sum((y - ybar) ** 2 for y in values)
        return slope, 1 - ss_res / ss_tot if ss_tot > 0 else 0.0

    def _status(self, slope, r_squared):
        if slope is None or r_squared is None:
            return "UNKNOWN"
        if r_squared > 0.6:
            return "RISING" if slope > 0 else "FALLING"
        return "STABLE"

    def _price_rank(self, data, current_price):
        s = sorted(data)
        if not s or s[-1] == s[0]:
            return 0.5
        return sum(1 for x in s if x <= current_price) / len(s)

    def _recent_percentile(self, snapshots, current_price):
        latest = self._time(snapshots[-1].get("updated_at")) or datetime.utcnow()
        recent = [float(s["price"]) for s in snapshots if (self._time(s.get("updated_at")) or latest) >= latest - timedelta(days=14)]
        if len(recent) < 2:
            return None
        lo, hi = min(recent), max(recent)
        return 0.0 if hi == lo else (current_price - lo) / (hi - lo)

    def _percentile(self, data, p):
        s = sorted(data)
        if not s:
            return 0.0
        k = max(0.0, min(1.0, p)) * (len(s) - 1)
        f = int(k)
        c = min(f + 1, len(s) - 1)
        return s[f] + (s[c] - s[f]) * (k - f)

    def _ema(self, values, span):
        if not values:
            return None
        alpha = 2 / (span + 1)
        ema = values[0]
        for value in values[1:]:
            ema = value * alpha + ema * (1 - alpha)
        return ema

    def _bollinger(self, ma30, sigma):
        if ma30 is None:
            return None, None
        band = max(2 * sigma, abs(ma30) * 0.02)
        return round(ma30 + band, 6), round(ma30 - band, 6)

    def _sell_pressure(self, *, current_price, daily_volume, orderbook=None):
        if current_price <= 0:
            return None
        orders = orderbook or self._synthetic_orders(current_price)
        volumes = [v for _, v in orders[:5]]
        if not volumes:
            return None
        base = sum(volumes) / daily_volume if daily_volume > 0 else sum(volumes)
        wall_vol = max(3, daily_volume * 0.15)
        return base * 0.4 if min(volumes) <= wall_vol else base

    def _synthetic_orders(self, price):
        gap = self._dynamic_gap(price)
        return [(round(price + gap * (i + 1), 2), 2 + i) for i in range(5)]

    def _dynamic_gap(self, price):
        if price < 5:
            return max(0.10, price * 0.08)
        if price < 20:
            return max(0.30, price * 0.05)
        if price < 100:
            return max(1.0, price * 0.03)
        if price < 500:
            return max(5.0, price * 0.02)
        return max(10.0, price * 0.015)

    def _smart_price(self, *, current_price, daily_volume, volume_class, orderbook=None):
        if current_price <= 0:
            return None
        orders = sorted(orderbook or self._synthetic_orders(current_price), key=lambda x: x[0])
        if not orders:
            return None
        if orders[0][1] <= 3:
            orders = orders[1:]
        if not orders:
            return None
        threshold = 10 if volume_class == "THIN" else 20
        acc = 0
        lowest = orders[0][0]
        target = lowest
        for price, volume in orders:
            acc += volume
            target = price
            if acc >= threshold:
                break
        gap = self._dynamic_gap(current_price)
        return round(target - 0.01, 2) if target - lowest > gap else round(lowest - 0.01, 2)

    def _orderbook_from_record(self, record):
        raw = record.get("orderbook_json")
        if not raw:
            return None
        try:
            payload = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, json.JSONDecodeError):
            return None
        levels = payload.get("levels") if isinstance(payload, dict) else None
        if not isinstance(levels, list):
            return None
        orders = []
        for level in levels:
            try:
                price = float(level.get("price"))
                quantity = int(level.get("quantity") or 0)
            except (TypeError, ValueError, AttributeError):
                continue
            if price > 0 and quantity > 0:
                orders.append((price, quantity))
        return orders or None

    def _confidence(self, clean_count, volume_class):
        if clean_count < 15:
            return "LOW"
        if volume_class == "THIN":
            return "LOW" if clean_count < 30 else "MEDIUM"
        return "HIGH"

    @staticmethod
    def _baseline(snapshots, since):
        base = None
        for s in snapshots:
            t = TrendEngine._time(s.get("updated_at"))
            if t and t <= since:
                base = s
            elif t and t > since:
                break
        return base

    @staticmethod
    def _pct(start, end):
        if not start or start <= 0:
            return None
        return round((end - start) / start * 100, 2)

    @staticmethod
    def _time(value):
        if not value:
            return None
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(str(value).split(".")[0], fmt)
            except ValueError:
                continue
        return None


engine = TrendEngine()
