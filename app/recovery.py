from __future__ import annotations

import json

from sqlalchemy import select

from app.db import get_session
from app.models import Order, Position, RuntimeState, Trade


class RecoveryService:
    def __init__(self, notifier, state_machine) -> None:
        self.notifier = notifier
        self.state_machine = state_machine

    async def recover(self) -> None:
        await self.notifier.notify("RECOVERY_STARTED", "starting runtime recovery")
        async with get_session() as session:
            for key in ("signal_scan_cursor", "last_processed_block"):
                result = await session.execute(select(RuntimeState).where(RuntimeState.state_key == key))
                if not result.scalar_one_or_none():
                    await self.state_machine.set_runtime_state(session, key, {})
            order_result = await session.execute(select(Order).where(Order.status.in_(["PENDING", "SUBMITTED"])))
            for order in order_result.scalars().all():
                if order.status == "PENDING":
                    await self.state_machine.transition_order(session, order, "TIMEOUT", "recovery_timeout")
                elif order.status == "SUBMITTED":
                    await self.state_machine.transition_order(session, order, "TIMEOUT", "recovery_submitted_timeout")
                await self.state_machine.set_runtime_state(
                    session,
                    f"order:{order.order_id}",
                    {
                        "order_id": order.order_id,
                        "status": order.status,
                        "side": order.side,
                        "ca": order.ca,
                        "fail_reason": order.fail_reason,
                    },
                )
            position_result = await session.execute(
                select(Position).where(Position.status.in_(["OPEN", "TP_PENDING", "SL_PENDING", "EXIT_PENDING"]))
            )
            for position in position_result.scalars().all():
                await self.state_machine.set_runtime_state(
                    session,
                    f"open_position:{position.position_id}",
                    {
                        "position_id": position.position_id,
                        "status": position.status,
                        "ca": position.ca,
                        "entry_price": position.entry_price,
                        "current_price": position.current_price,
                    },
                )
            exited_position_result = await session.execute(select(Position).where(Position.status == "EXITED"))
            for position in exited_position_result.scalars().all():
                await self.state_machine.set_runtime_state(
                    session,
                    f"position:{position.position_id}",
                    {
                        "position_id": position.position_id,
                        "status": position.status,
                        "ca": position.ca,
                        "exit_reason": position.exit_reason,
                    },
                )
            trade_result = await session.execute(select(Trade).where(Trade.trade_status == "OPENING"))
            for trade in trade_result.scalars().all():
                related_position = await session.execute(select(Position).where(Position.id == trade.position_id))
                position = related_position.scalar_one_or_none()
                if position and position.status == "EXITED":
                    await self.state_machine.transition_trade(session, trade, "CLOSED", "recovered_exited_position")
        await self.notifier.notify("RECOVERY_FINISHED", "runtime recovery finished")
