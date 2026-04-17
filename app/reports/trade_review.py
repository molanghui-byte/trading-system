from __future__ import annotations

from sqlalchemy import select

from app.models import Trade


async def review_open_trades(session, state_machine) -> None:
    result = await session.execute(select(Trade).where(Trade.trade_status == "CLOSED"))
    for trade in result.scalars().all():
        trade.lesson_tag = "follow_plan" if trade.pnl_usd >= 0 else "tighten_filter"
        await state_machine.transition_trade(session, trade, "REVIEWED", "trade_review_completed")
