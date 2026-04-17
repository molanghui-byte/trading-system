from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import desc, func, select

from app.models import Position, Trade


@dataclass
class RiskDecision:
    allowed: bool
    reason: str = ""


class RiskManager:
    def __init__(self, config, notifier) -> None:
        self.config = config
        self.notifier = notifier

    async def evaluate_candidate(self, session, candidate) -> RiskDecision:
        risk = self.config.risk
        if candidate.ca in risk.blacklist_ca:
            return RiskDecision(False, "ca_blacklisted")
        open_positions = await session.scalar(
            select(func.count()).select_from(Position).where(Position.status == "OPEN")
        )
        if int(open_positions or 0) >= risk.max_concurrent_positions:
            return RiskDecision(False, "max_concurrent_positions_reached")
        recent_position = await session.execute(
            select(Position).where(Position.ca == candidate.ca).order_by(desc(Position.entry_time)).limit(1)
        )
        position = recent_position.scalar_one_or_none()
        if position:
            cooldown_until = position.entry_time + timedelta(minutes=risk.rebuy_cooldown_minutes)
            if cooldown_until > datetime.now(timezone.utc):
                return RiskDecision(False, "rebuy_cooldown")
        if await self._loss_pause(session):
            return RiskDecision(False, "loss_pause")
        return RiskDecision(True)

    async def _loss_pause(self, session) -> bool:
        risk = self.config.risk
        result = await session.execute(
            select(Trade)
            .where(Trade.trade_status.in_(["CLOSED", "REVIEWED"]))
            .order_by(desc(Trade.exit_time))
            .limit(risk.consecutive_loss_pause_count)
        )
        trades = list(result.scalars().all())
        if len(trades) < risk.consecutive_loss_pause_count:
            return False
        return all(trade.pnl_usd < 0 for trade in trades)
