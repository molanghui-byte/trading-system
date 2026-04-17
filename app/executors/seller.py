from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from app.models import Order, StrategyLog, Trade
from app.reports.daily_report import generate_daily_report


class Seller:
    def __init__(self, config, notifier, state_machine, router) -> None:
        self.config = config
        self.notifier = notifier
        self.state_machine = state_machine
        self.router = router

    async def execute(self, session, position, exit_reason: str, exit_price: float):
        if position.status == "EXITED":
            result = await session.execute(select(Trade).where(Trade.position_id == position.id))
            return result.scalars().all()[-1]
        position.entry_time = self._ensure_utc(position.entry_time)
        idempotency_key = f"sell:{position.id}"
        result = await session.execute(select(Order).where(Order.idempotency_key == idempotency_key))
        order = result.scalar_one_or_none()
        if order and order.status == "CONFIRMED":
            trade_result = await session.execute(select(Trade).where(Trade.position_id == position.id))
            return trade_result.scalars().all()[-1]
        order = order or Order(
            order_id=f"pending_sell_{position.id}",
            candidate_id=position.candidate_id,
            position_id=position.id,
            signal_id=position.signal_id,
            wallet=position.wallet,
            chain=position.chain,
            ca=position.ca,
            symbol=position.symbol,
            side="SELL",
            mode=self.config.system.mode,
            quantity_raw=position.quantity_raw,
            price=exit_price,
            value_usd=position.current_value,
            status="PENDING",
            idempotency_key=idempotency_key,
        )
        session.add(order)
        await session.flush()
        await self.state_machine.transition_order(session, order, "SUBMITTED")
        try:
            routed = await self.router.route("SELL", position.ca, position.current_value, exit_price)
        except Exception as exc:
            order.retries += 1
            await self.state_machine.transition_order(session, order, "FAILED", str(exc))
            if position.status in {"TP_PENDING", "SL_PENDING", "EXIT_PENDING"}:
                await self.state_machine.transition_position(session, position, "FAILED_EXIT", str(exc))
            session.add(
                StrategyLog(
                    strategy_name=position.strategy_name,
                    event="SELL_FAILED",
                    candidate_id=position.candidate_id,
                    signal_id=position.signal_id,
                    position_id=position.id,
                    order_id=order.id,
                    message=str(exc),
                    snapshot='{"phase":"route_sell"}',
                )
            )
            await self.notifier.notify("SELL_FAILED", f"sell failed for {position.symbol or position.ca}", {"position_id": position.id, "reason": str(exc)})
            raise
        order.order_id = routed.order_id
        order.tx_hash = routed.tx_hash
        order.price = exit_price
        order.value_usd = position.current_value
        await self.state_machine.transition_order(session, order, "CONFIRMED")
        await self.state_machine.set_runtime_state(
            session,
            f"order:{order.order_id}",
            {
                "order_id": order.order_id,
                "status": order.status,
                "side": order.side,
                "ca": order.ca,
                "tx_hash": order.tx_hash,
            },
        )
        await self.state_machine.transition_position(session, position, "EXIT_PENDING", exit_reason)
        position.exited_at = datetime.now(timezone.utc)
        await self.state_machine.transition_position(session, position, "EXITED", exit_reason)
        trade_result = await session.execute(select(Trade).where(Trade.position_id == position.id))
        trade = trade_result.scalar_one()
        trade.entry_time = self._ensure_utc(trade.entry_time)
        trade.exit_time = self._ensure_utc(position.exited_at)
        trade.exit_price = exit_price
        trade.exit_value = position.current_value
        trade.pnl_usd = position.current_value - position.entry_value
        trade.pnl_pct = (trade.pnl_usd / position.entry_value) if position.entry_value else 0.0
        trade.hold_minutes = (
            (trade.exit_time - trade.entry_time).total_seconds() / 60 if trade.exit_time else 0.0
        )
        trade.why_exit = exit_reason
        trade.actual_result = "closed"
        trade.exit_trigger_type = exit_reason
        trade.pass_or_fail = "PASS" if trade.pnl_usd >= 0 else "FAIL"
        await self.state_machine.transition_trade(session, trade, "CLOSED", exit_reason)
        await self.state_machine.set_runtime_state(
            session,
            f"position:{position.position_id}",
            {
                "position_id": position.position_id,
                "status": position.status,
                "ca": position.ca,
                "exit_reason": exit_reason,
                "pnl_usd": trade.pnl_usd,
            },
        )
        session.add(
            StrategyLog(
                strategy_name=position.strategy_name,
                event="SELL_CONFIRMED",
                candidate_id=position.candidate_id,
                signal_id=position.signal_id,
                position_id=position.id,
                order_id=order.id,
                message=exit_reason,
                snapshot=(
                    f'{{"exit_price":{exit_price},"exit_value":{position.current_value},"pnl_usd":{trade.pnl_usd}}}'
                ),
            )
        )
        await self.notifier.notify("SELL_CONFIRMED", f"sell confirmed for {position.symbol or position.ca}", {"position_id": position.id, "order_id": order.id, "reason": exit_reason})
        await self.notifier.notify("POSITION_EXITED", f"position exited for {position.symbol or position.ca}", {"position_id": position.id, "reason": exit_reason})
        report = await generate_daily_report(session)
        await self.state_machine.set_runtime_state(
            session,
            f"daily_report:{report.report_date}",
            {
                "report_date": report.report_date,
                "total_pnl_usd": report.total_pnl_usd,
                "total_trades": report.total_trades,
                "win_rate": report.win_rate,
            },
        )
        return trade

    @staticmethod
    def _ensure_utc(value):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
