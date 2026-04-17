from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import select

from app.models import DailyReport, Trade


async def generate_daily_report(session) -> DailyReport:
    today = datetime.now(timezone.utc).date().isoformat()
    result = await session.execute(select(Trade).where(Trade.exit_time.is_not(None)))
    trades = [
        trade
        for trade in result.scalars().all()
        if _ensure_utc(trade.exit_time) and _ensure_utc(trade.exit_time).date().isoformat() == today
    ]
    total_trades = len(trades)
    total_pnl = sum(trade.pnl_usd for trade in trades)
    wins = [trade for trade in trades if trade.pnl_usd > 0]
    losses = [trade for trade in trades if trade.pnl_usd <= 0]
    source_pnl: dict[str, list[float]] = defaultdict(list)
    for trade in trades:
        source_pnl[trade.signal_source].append(trade.pnl_usd)
    ranked = sorted(source_pnl.items(), key=lambda item: sum(item[1]), reverse=True)
    existing = await session.execute(select(DailyReport).where(DailyReport.report_date == today))
    report = existing.scalar_one_or_none()
    if not report:
        report = DailyReport(report_date=today)
        session.add(report)
        await session.flush()
    report.total_pnl_usd = total_pnl
    report.total_trades = total_trades
    report.win_rate = (len(wins) / total_trades) if total_trades else 0.0
    report.average_rr = (sum(trade.pnl_pct for trade in trades) / total_trades) if total_trades else 0.0
    report.max_drawdown = min((trade.pnl_pct for trade in losses), default=0.0)
    report.best_source = ranked[0][0] if ranked else ""
    report.worst_source = ranked[-1][0] if ranked else ""
    opening_count = len([trade for trade in trades if trade.trade_status in {"OPENING", "CLOSED", "REVIEWED"}])
    report.fill_rate = (opening_count / total_trades) if total_trades else 0.0
    report.report_json = json.dumps(
        {
            "trade_ids": [trade.trade_id for trade in trades],
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "best_source_pnl": sum(source_pnl[ranked[0][0]]) if ranked else 0.0,
            "worst_source_pnl": sum(source_pnl[ranked[-1][0]]) if ranked else 0.0,
        },
        ensure_ascii=False,
    )
    return report


def _ensure_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value
