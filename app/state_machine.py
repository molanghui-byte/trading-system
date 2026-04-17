from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import select

from app.models import Candidate, Order, Position, RuntimeState, Signal, StrategyLog, SystemLog, Trade


@dataclass(frozen=True)
class TransitionRule:
    allowed: dict[str, set[str]]

    def assert_transition(self, current: str, target: str) -> None:
        if target not in self.allowed.get(current, set()):
            raise ValueError(f"invalid state transition: {current} -> {target}")


SIGNAL_RULES = TransitionRule(
    {
        "NEW": {"LINKED", "IGNORED", "ERROR"},
        "LINKED": set(),
        "IGNORED": set(),
        "ERROR": set(),
    }
)
CANDIDATE_RULES = TransitionRule(
    {
        "NEW": {"DISCOVERED", "REJECTED", "FAILED"},
        "DISCOVERED": {"CHECKED", "REJECTED", "FAILED"},
        "CHECKED": {"BUY_PENDING", "REJECTED", "FAILED"},
        "BUY_PENDING": {"BOUGHT", "FAILED"},
        "BOUGHT": {"SELL_PENDING", "SOLD", "FAILED"},
        "SELL_PENDING": {"SOLD", "FAILED"},
        "REJECTED": set(),
        "SOLD": set(),
        "FAILED": set(),
    }
)
ORDER_RULES = TransitionRule(
    {
        "PENDING": {"SUBMITTED", "FAILED", "TIMEOUT", "CANCELLED"},
        "SUBMITTED": {"CONFIRMED", "FAILED", "TIMEOUT", "CANCELLED"},
        "CONFIRMED": set(),
        "FAILED": set(),
        "TIMEOUT": set(),
        "CANCELLED": set(),
    }
)
POSITION_RULES = TransitionRule(
    {
        "OPEN": {"TP_PENDING", "SL_PENDING", "EXIT_PENDING", "FAILED_EXIT"},
        "TP_PENDING": {"EXIT_PENDING", "EXITED", "FAILED_EXIT"},
        "SL_PENDING": {"EXIT_PENDING", "EXITED", "FAILED_EXIT"},
        "EXIT_PENDING": {"EXITED", "FAILED_EXIT"},
        "EXITED": set(),
        "FAILED_EXIT": set(),
    }
)
TRADE_RULES = TransitionRule(
    {
        "OPENING": {"CLOSED"},
        "CLOSED": {"REVIEWED"},
        "REVIEWED": set(),
    }
)


class StateMachine:
    def __init__(self, notifier) -> None:
        self.notifier = notifier

    async def transition_signal(self, session, signal: Signal, target: str, reason: str = "") -> None:
        SIGNAL_RULES.assert_transition(signal.processing_status, target)
        old = signal.processing_status
        signal.processing_status = target
        signal.error_reason = reason
        await self._system_log(session, "SIGNAL_STATE_CHANGED", f"{old} -> {target}", {"signal_id": signal.id, "reason": reason})

    async def transition_candidate(self, session, candidate: Candidate, target: str, reason: str = "") -> None:
        CANDIDATE_RULES.assert_transition(candidate.status, target)
        old = candidate.status
        candidate.status = target
        if target == "REJECTED":
            candidate.reject_reason = reason
        await self._strategy_log(
            session,
            candidate.strategy_name or "system",
            "CANDIDATE_STATE_CHANGED",
            candidate_id=candidate.id,
            message=f"{old} -> {target}",
            snapshot={"reason": reason},
        )

    async def transition_order(self, session, order: Order, target: str, reason: str = "") -> None:
        ORDER_RULES.assert_transition(order.status, target)
        old = order.status
        order.status = target
        if reason:
            order.fail_reason = reason
        await self._system_log(session, "ORDER_STATE_CHANGED", f"{old} -> {target}", {"order_id": order.id, "reason": reason})

    async def transition_position(self, session, position: Position, target: str, reason: str = "") -> None:
        POSITION_RULES.assert_transition(position.status, target)
        old = position.status
        position.status = target
        if reason:
            position.exit_reason = reason
        await self._system_log(session, "POSITION_STATE_CHANGED", f"{old} -> {target}", {"position_id": position.id, "reason": reason})

    async def transition_trade(self, session, trade: Trade, target: str, reason: str = "") -> None:
        TRADE_RULES.assert_transition(trade.trade_status, target)
        old = trade.trade_status
        trade.trade_status = target
        await self._system_log(session, "TRADE_STATE_CHANGED", f"{old} -> {target}", {"trade_id": trade.id, "reason": reason})

    async def set_runtime_state(self, session, key: str, payload: dict) -> None:
        result = await session.execute(select(RuntimeState).where(RuntimeState.state_key == key))
        state = result.scalar_one_or_none()
        data = json.dumps(payload, ensure_ascii=False)
        if not state:
            session.add(RuntimeState(state_key=key, state_json=data))
            await self._system_log(session, "RUNTIME_STATE_CREATED", key, payload)
            return
        state.state_json = data
        await self._system_log(session, "RUNTIME_STATE_UPDATED", key, payload)

    async def get_open_positions(self, session) -> list[Position]:
        result = await session.execute(select(Position).where(Position.status != "EXITED"))
        return list(result.scalars().all())

    async def _strategy_log(self, session, strategy_name: str, event: str, **kwargs) -> None:
        snapshot = kwargs.pop("snapshot", {})
        session.add(
            StrategyLog(
                strategy_name=strategy_name,
                event=event,
                snapshot=json.dumps(snapshot, ensure_ascii=False),
                **kwargs,
            )
        )

    async def _system_log(self, session, event: str, message: str, detail: dict) -> None:
        session.add(
            SystemLog(
                event=event,
                level="INFO",
                message=message,
                detail=json.dumps(detail, ensure_ascii=False),
            )
        )
