from __future__ import annotations

import json
from dataclasses import dataclass

from app.models import StrategyLog


@dataclass
class StrategyDecision:
    should_buy: bool
    amount_usd: float
    buy_reason: str
    risk_tags: list[str]
    priority: int


class BscFourMemeMvpStrategy:
    name = "bscfourmememvp"

    def __init__(self, config) -> None:
        self.config = config
        self.params = config.strategies.bscfourmememvp

    async def evaluate(self, session, candidate, holding_open: bool) -> StrategyDecision:
        p = self.params
        tags: list[str] = []
        allowed = True
        reason = "signal_cluster_ok"
        if holding_open:
            allowed = False
            reason = "already_holding"
        if candidate.liquidity < p.min_liquidity:
            allowed = False
            reason = "liquidity_too_low"
            tags.append("low_liquidity")
        if candidate.liquidity > p.max_liquidity:
            allowed = False
            reason = "liquidity_too_high"
            tags.append("crowded")
        if candidate.bundler_rate > p.maxbundlerrate:
            allowed = False
            reason = "bundler_rate_too_high"
            tags.append("bundler_risk")
        if candidate.bot_rate > p.maxbotrate:
            allowed = False
            reason = "bot_rate_too_high"
            tags.append("bot_risk")
        if candidate.holder_count < p.minholdercount:
            allowed = False
            reason = "holder_count_too_low"
        if candidate.top10_rate > p.maxtop10rate:
            allowed = False
            reason = "top10_concentration_too_high"
        priority = int(candidate.aggregated_signal_score * 100 - candidate.aggregated_risk_score * 50)
        decision = StrategyDecision(
            should_buy=allowed,
            amount_usd=p.buy.amount_usd,
            buy_reason=reason,
            risk_tags=tags,
            priority=priority,
        )
        session.add(
            StrategyLog(
                strategy_name=self.name,
                event="STRATEGY_EVALUATED",
                candidate_id=candidate.id,
                message=reason,
                snapshot=json.dumps(
                    {
                        "allowed": allowed,
                        "amount_usd": decision.amount_usd,
                        "priority": priority,
                        "risk_tags": tags,
                    },
                    ensure_ascii=False,
                ),
            )
        )
        return decision
