from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select

from app.models import Order, Position, StrategyLog, Trade


class Buyer:
    def __init__(self, config, notifier, state_machine, router) -> None:
        self.config = config
        self.notifier = notifier
        self.state_machine = state_machine
        self.router = router

    async def execute(self, session, candidate, signal_id: Optional[int], buy_reason: str, amount_usd: float):
        wallet = next(wallet for wallet in self.config.wallets if wallet.enabled)
        idempotency_key = f"buy:{candidate.ca}:{candidate.strategy_name}:{wallet.address}"
        existing_order = await session.execute(select(Order).where(Order.idempotency_key == idempotency_key))
        order = existing_order.scalar_one_or_none()
        if order and order.position_id:
            position_result = await session.execute(select(Position).where(Position.id == order.position_id))
            position = position_result.scalar_one_or_none()
            if position:
                return position
        if order and order.status in {"PENDING", "SUBMITTED"}:
            raise RuntimeError(f"buy order still in-flight for candidate {candidate.id}")
        order = Order(
            order_id=f"pending_buy_{candidate.id}",
            candidate_id=candidate.id,
            signal_id=signal_id,
            wallet=wallet.address,
            chain=candidate.chain,
            ca=candidate.ca,
            symbol=candidate.symbol,
            side="BUY",
            mode=self.config.system.mode,
            quantity_raw="0",
            price=max(candidate.market_cap / 1_000_000_000, 0.000001),
            value_usd=amount_usd,
            status="PENDING",
            idempotency_key=idempotency_key,
        )
        session.add(order)
        await session.flush()
        await self.notifier.notify("BUYORDERCREATED", f"buy order created for {candidate.ca}", {"candidate_id": candidate.id})
        await self.state_machine.transition_order(session, order, "SUBMITTED")
        try:
            routed = await self.router.route("BUY", candidate.ca, amount_usd, order.price)
        except Exception as exc:
            order.retries += 1
            await self.state_machine.transition_order(session, order, "FAILED", str(exc))
            session.add(
                StrategyLog(
                    strategy_name=candidate.strategy_name,
                    event="BUY_FAILED",
                    candidate_id=candidate.id,
                    signal_id=signal_id,
                    order_id=order.id,
                    message=str(exc),
                    snapshot='{"phase":"route_buy"}',
                )
            )
            await self.notifier.notify("BUY_FAILED", f"buy failed for {candidate.ca}", {"candidate_id": candidate.id, "reason": str(exc)})
            raise
        order.order_id = routed.order_id
        order.tx_hash = routed.tx_hash
        order.quantity_raw = routed.quantity_raw
        order.price = routed.price
        await self.state_machine.transition_order(session, order, "CONFIRMED")
        stable_order_key = order.order_id
        await self.state_machine.set_runtime_state(
            session,
            f"order:{stable_order_key}",
            {
                "order_id": stable_order_key,
                "status": order.status,
                "side": order.side,
                "ca": order.ca,
                "tx_hash": order.tx_hash,
            },
        )
        position = Position(
            position_id=f"pos_{candidate.id}_{int(datetime.now(timezone.utc).timestamp())}",
            candidate_id=candidate.id,
            signal_id=signal_id,
            wallet=wallet.address,
            chain=candidate.chain,
            ca=candidate.ca,
            symbol=candidate.symbol,
            strategy_name=candidate.strategy_name,
            entry_price=routed.price,
            entry_value=routed.value_usd,
            quantity_raw=routed.quantity_raw,
            current_price=routed.price,
            current_value=routed.value_usd,
            highest_price_seen=routed.price,
            lowest_price_seen=routed.price,
            stop_loss_price=routed.price * (1 - self.config.strategies.bscfourmememvp.stoplosspct),
            take_profit_price=routed.price * (1 + self.config.strategies.bscfourmememvp.takeprofitpct),
            trailing_stop_pct=self.config.strategies.bscfourmememvp.trailingstoppct,
            status="OPEN",
        )
        session.add(position)
        await session.flush()
        order.position_id = position.id
        candidate.last_buy_attempt_at = datetime.now(timezone.utc).isoformat()
        await self.state_machine.set_runtime_state(
            session,
            f"active_task:buy:{candidate.id}",
            {
                "candidate_id": candidate.id,
                "position_id": position.position_id,
                "status": "completed",
            },
        )
        session.add(
            Trade(
                trade_id=f"trade_open_{position.position_id}",
                position_id=position.id,
                candidate_id=candidate.id,
                signal_id=signal_id,
                signal_source="aggregated",
                strategy_name=candidate.strategy_name,
                wallet=wallet.address,
                chain=candidate.chain,
                ca=candidate.ca,
                symbol=candidate.symbol,
                why_enter=buy_reason,
                expected_logic="paper_open",
                entry_time=position.entry_time,
                entry_price=position.entry_price,
                entry_value=position.entry_value,
                trade_status="OPENING",
            )
        )
        session.add(
            StrategyLog(
                strategy_name=candidate.strategy_name,
                event="BUY_CONFIRMED",
                candidate_id=candidate.id,
                signal_id=signal_id,
                position_id=position.id,
                order_id=order.id,
                message=buy_reason,
                snapshot=(
                    f'{{"amount_usd":{amount_usd},"price":{routed.price},"quantity_raw":"{routed.quantity_raw}"}}'
                ),
            )
        )
        await self.notifier.notify("BUY_CONFIRMED", f"buy confirmed for {candidate.symbol or candidate.ca}", {"candidate_id": candidate.id, "position_id": position.id, "order_id": order.id})
        await self.notifier.notify("POSITION_OPENED", f"position opened for {candidate.symbol or candidate.ca}", {"position_id": position.id})
        return position
