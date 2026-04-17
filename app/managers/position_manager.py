from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select

from app.models import Candidate, Signal, Position


class PositionManager:
    def __init__(self, config, notifier, state_machine, trader) -> None:
        self.config = config
        self.notifier = notifier
        self.state_machine = state_machine
        self.trader = trader
        self.params = config.strategies.bscfourmememvp

    async def manage(self, session) -> None:
        result = await session.execute(select(Position).where(Position.status == "OPEN"))
        now = datetime.now(timezone.utc)
        for position in result.scalars().all():
            position.entry_time = self._ensure_utc(position.entry_time)
            position.exited_at = self._ensure_utc(position.exited_at)
            candidate_result = await session.execute(select(Candidate).where(Candidate.id == position.candidate_id))
            candidate = candidate_result.scalar_one()
            await self._refresh_position(session, position, candidate, now)
            trigger = await self._exit_trigger(session, position, candidate, now)
            if not trigger:
                continue
            await self.notifier.notify("SELL_TRIGGERED", f"sell triggered for {position.ca}", {"position_id": position.id, "reason": trigger})
            if candidate.status == "BOUGHT":
                await self.state_machine.transition_candidate(session, candidate, "SELL_PENDING", trigger)
            try:
                await self.trader.seller.execute(session, position, trigger, position.current_price)
            except Exception as exc:
                candidate.status = "BOUGHT"
                await self.notifier.notify(
                    "POSITIONEXITFAILED",
                    f"sell execution failed for {position.ca}",
                    {"position_id": position.id, "reason": str(exc)},
                )
                continue
            if candidate.status == "SELL_PENDING":
                await self.state_machine.transition_candidate(session, candidate, "SOLD", trigger)

    async def _refresh_position(self, session, position: Position, candidate: Candidate, now: datetime) -> None:
        latest_signal_result = await session.execute(
            select(Signal).where(Signal.ca == position.ca).order_by(Signal.discovered_at.desc()).limit(1)
        )
        latest_signal = latest_signal_result.scalar_one_or_none()
        latest_signal_score = latest_signal.signal_score if latest_signal else candidate.aggregated_signal_score
        latest_risk_score = latest_signal.risk_score if latest_signal else candidate.aggregated_risk_score
        elapsed_seconds = max((now - position.entry_time).total_seconds(), 0.0)
        confidence = max(latest_signal_score - latest_risk_score, 0.05)

        # Paper mode still needs a deterministic, explainable mark-price path so exits can be validated.
        # We model early momentum from signal confidence, then a fade phase that can trigger trailing exits.
        if elapsed_seconds <= 20:
            multiplier = 1 + min(confidence * 0.16 * (elapsed_seconds / 20), 0.16)
        elif elapsed_seconds <= 40:
            fade = (elapsed_seconds - 20) / 20
            multiplier = 1 + (confidence * 0.16) - (confidence * 0.08 * fade)
        else:
            decay = min((elapsed_seconds - 40) / 20, 1.0)
            multiplier = 1 + max(confidence * 0.08 * (1 - decay), -self.params.stoplosspct)

        position.current_price = max(position.entry_price * multiplier, 0.0000001)
        position.current_value = position.entry_value * (position.current_price / position.entry_price)
        position.unrealized_pnl_usd = position.current_value - position.entry_value
        position.unrealized_pnl_pct = position.unrealized_pnl_usd / position.entry_value if position.entry_value else 0.0
        position.highest_price_seen = max(position.highest_price_seen, position.current_price)
        position.lowest_price_seen = min(position.lowest_price_seen or position.current_price, position.current_price)

    async def _exit_trigger(self, session, position: Position, candidate: Candidate, now: datetime) -> Optional[str]:
        if position.current_price <= position.stop_loss_price:
            return "fixed_stop_loss"
        if position.current_price >= position.take_profit_price:
            return "fixed_take_profit"
        if now >= position.entry_time + timedelta(minutes=self.params.maxholdminutes):
            return "max_hold_timeout"
        latest_signal_result = await session.execute(
            select(Signal).where(Signal.ca == position.ca).order_by(Signal.discovered_at.desc()).limit(1)
        )
        latest_signal = latest_signal_result.scalar_one_or_none()
        latest_liquidity = latest_signal.liquidity if latest_signal else candidate.liquidity
        latest_signal_score = latest_signal.signal_score if latest_signal else candidate.aggregated_signal_score
        latest_risk_score = latest_signal.risk_score if latest_signal else candidate.aggregated_risk_score
        if self.params.signalreverseexit and latest_signal_score < latest_risk_score:
            return "signal_reverse_exit"
        if latest_liquidity and latest_liquidity < self.params.liquidityexitthreshold:
            return "liquidity_exit_threshold"
        trailing_floor = position.highest_price_seen * (1 - self.params.trailingstoppct)
        if position.current_price <= trailing_floor and position.highest_price_seen > position.entry_price:
            return "trailing_stop"
        return None

    @staticmethod
    def _ensure_utc(value: Optional[datetime]) -> Optional[datetime]:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
