from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MarketDecision:
    label: str
    score: float
    risk_score: float
    reasons: list[str]
    blockers: list[str]


def evaluate_market_item(item: dict[str, Any]) -> MarketDecision:
    volume = _to_float(item.get("volume"))
    liquidity = _to_float(item.get("liquidity"))
    market_cap = _to_float(item.get("market_cap"))
    price_change_1h = _to_float(item.get("price_change_percent1h") or item.get("price_change_percent"))
    top10_rate = _to_ratio(item.get("top_10_holder_rate"))
    bundler_rate = _to_ratio(item.get("bundler_rate"))
    bot_rate = _to_ratio(item.get("bot_degen_rate"))
    rug_ratio = _to_ratio(item.get("rug_ratio"))
    smart_degen_count = _to_int(item.get("smart_degen_count"))
    renowned_count = _to_int(item.get("renowned_count"))
    holder_count = _to_int(item.get("holder_count"))
    creator_closed = bool(item.get("creator_close")) or item.get("creator_token_status") == "creator_close"
    wash_trading = bool(item.get("is_wash_trading"))
    is_honeypot = str(item.get("is_honeypot", "0")) == "1"

    score = 0.0
    reasons: list[str] = []
    blockers: list[str] = []

    if volume >= 1_000_000:
        score += 22
        reasons.append("volume_1m_plus")
    elif volume >= 250_000:
        score += 14
        reasons.append("volume_250k_plus")

    if liquidity >= 100_000:
        score += 18
        reasons.append("liquidity_100k_plus")
    elif liquidity >= 50_000:
        score += 14
        reasons.append("liquidity_50k_plus")
    elif liquidity >= 10_000:
        score += 8
        reasons.append("liquidity_10k_plus")

    if smart_degen_count >= 10:
        score += 20
        reasons.append("smart_money_10_plus")
    elif smart_degen_count >= 3:
        score += 14
        reasons.append("smart_money_3_plus")
    elif smart_degen_count > 0:
        score += 6
        reasons.append("smart_money_present")

    if renowned_count >= 5:
        score += 12
        reasons.append("kol_5_plus")
    elif renowned_count > 0:
        score += 6
        reasons.append("kol_present")

    if 10 <= price_change_1h <= 250:
        score += 10
        reasons.append("healthy_momentum")
    elif price_change_1h > 250:
        score += 4
        reasons.append("overheated_momentum")

    if holder_count >= 500:
        score += 8
        reasons.append("holder_base_500_plus")
    elif holder_count >= 100:
        score += 4
        reasons.append("holder_base_100_plus")

    if creator_closed:
        score += 6
        reasons.append("creator_closed")

    if market_cap > 0 and market_cap <= 500_000:
        score += 5
        reasons.append("early_market_cap")

    if wash_trading:
        blockers.append("wash_trading")
    if is_honeypot:
        blockers.append("honeypot")
    if rug_ratio > 0.3:
        blockers.append("rug_ratio_high")
    if top10_rate > 0.5:
        blockers.append("top10_concentration_high")
    if bundler_rate > 0.3:
        blockers.append("bundler_rate_high")
    if liquidity < 10_000:
        blockers.append("liquidity_too_low")
    if not creator_closed:
        blockers.append("creator_still_holds")

    risk_score = max(
        rug_ratio,
        top10_rate,
        bundler_rate,
        bot_rate * 0.5,
        0.95 if wash_trading or is_honeypot else 0.0,
        0.65 if liquidity < 10_000 else 0.0,
    )

    if blockers:
        label = "SKIP"
    elif score >= 70:
        label = "PASS"
    elif score >= 45:
        label = "WATCH"
    else:
        label = "WATCH"
        reasons.append("insufficient_confirmation")

    return MarketDecision(
        label=label,
        score=min(score, 100.0),
        risk_score=min(max(risk_score, 0.0), 1.0),
        reasons=reasons,
        blockers=blockers,
    )


def _to_float(value: Any) -> float:
    try:
        if value in ("", None):
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _to_int(value: Any) -> int:
    try:
        if value in ("", None):
            return 0
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _to_ratio(value: Any) -> float:
    try:
        if value in ("", None):
            return 0.0
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    if numeric > 1:
        return min(numeric / 100, 1.0)
    return max(numeric, 0.0)
