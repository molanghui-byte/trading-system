from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from sqlalchemy import func, select

from app.db import get_session
from app.models import Candidate, DailyReport, Position, Signal, Trade
from app.reports.daily_report import generate_daily_report
from app.reports.trade_review import review_open_trades


class SchedulerService:
    def __init__(self, config, notifier, listener_service, candidate_pool, trader, position_manager, recovery_service, state_machine) -> None:
        self.config = config
        self.notifier = notifier
        self.listener_service = listener_service
        self.candidate_pool = candidate_pool
        self.trader = trader
        self.position_manager = position_manager
        self.recovery_service = recovery_service
        self.state_machine = state_machine
        self.active_chain = (config.system.chain or "").strip().lower()
        self.active_position_statuses = ["OPEN", "TP_PENDING", "SL_PENDING", "EXIT_PENDING"]
        self.tasks: list[asyncio.Task] = []

    async def start(self) -> None:
        await self.recovery_service.recover()
        self.tasks = [
            asyncio.create_task(self._run_loop("scan_signals", self.config.scheduler.signal_scan_seconds, self._scan_signals)),
            asyncio.create_task(self._run_loop("process_candidates", self.config.scheduler.candidate_process_seconds, self._process_candidates)),
            asyncio.create_task(self._run_loop("process_orders", self.config.scheduler.order_process_seconds, self._process_orders)),
            asyncio.create_task(self._run_loop("manage_positions", self.config.scheduler.position_check_seconds, self._manage_positions)),
            asyncio.create_task(self._run_loop("status_report", self.config.scheduler.status_report_seconds, self._status_report)),
            asyncio.create_task(self._run_loop("daily_report", self.config.scheduler.daily_report_seconds, self._daily_report)),
        ]
        await asyncio.gather(*self.tasks)

    async def _run_loop(self, name: str, interval: int, coroutine) -> None:
        while True:
            try:
                await coroutine()
            except Exception as exc:
                await self.notifier.notify("SYSTEM_ERROR", f"{name} failed: {exc}", {"task": name})
            await asyncio.sleep(interval)

    async def _scan_signals(self) -> None:
        async with get_session() as session:
            await self.listener_service.poll(session)
            await self.state_machine.set_runtime_state(
                session,
                "signal_scan_cursor",
                {"last_scan": datetime.now(timezone.utc).isoformat()},
            )

    async def _process_candidates(self) -> None:
        async with get_session() as session:
            await self.candidate_pool.ingest_signals(session)
            await self.candidate_pool.process_candidates(session)

    async def _process_orders(self) -> None:
        async with get_session() as session:
            query = select(Candidate).where(Candidate.status == "BUY_PENDING")
            if self.active_chain:
                query = query.where(Candidate.chain == self.active_chain)
            result = await session.execute(query)
            for candidate in result.scalars().all():
                position_exists = await session.execute(
                    select(Position).where(
                        Position.candidate_id == candidate.id,
                        Position.chain == candidate.chain,
                        Position.status.in_(self.active_position_statuses),
                    )
                )
                if position_exists.scalar_one_or_none():
                    await self.notifier.notify(
                        "SYSTEM_ERROR",
                        f"candidate {candidate.id} is BUY_PENDING with existing live position",
                        {"candidate_id": candidate.id},
                    )
                    continue
                signal_result = await session.execute(
                    select(Signal)
                    .where(Signal.chain == candidate.chain, Signal.ca == candidate.ca)
                    .order_by(Signal.discovered_at.desc())
                    .limit(1)
                )
                signal = signal_result.scalars().first()
                try:
                    position = await self.trader.buyer.execute(
                        session,
                        candidate,
                        signal.id if signal else None,
                        candidate.reject_reason or "buy_pending",
                        self.config.strategies.bscfourmememvp.buy.amount_usd,
                    )
                except Exception as exc:
                    await self.candidate_pool.state_machine.transition_candidate(session, candidate, "FAILED", str(exc))
                    await self.notifier.notify("BUY_FAILED", f"buy pipeline failed for {candidate.ca}", {"candidate_id": candidate.id, "reason": str(exc)})
                    continue
                await self.candidate_pool.state_machine.transition_candidate(session, candidate, "BOUGHT", "buy_confirmed")
                await self.state_machine.set_runtime_state(
                    session,
                    f"position:{position.position_id}",
                    {"status": position.status, "ca": position.ca, "candidate_id": candidate.id},
                )

    async def _manage_positions(self) -> None:
        async with get_session() as session:
            await self.position_manager.manage(session)
            await review_open_trades(session, self.state_machine)

    async def _status_report(self) -> None:
        async with get_session() as session:
            new_signals = await session.scalar(
                self._with_active_chain(
                    select(func.count()).select_from(Signal).where(Signal.processing_status == "NEW"),
                    Signal,
                )
            ) or 0
            active_candidates = await session.scalar(
                self._with_active_chain(
                    select(func.count()).select_from(Candidate).where(
                        Candidate.status.in_(["BUY_PENDING", "BOUGHT", "SELL_PENDING"])
                    ),
                    Candidate,
                )
            ) or 0
            active_positions = (
                await session.scalar(
                    self._with_active_chain(
                        select(func.count()).select_from(Position).where(
                            Position.status.in_(self.active_position_statuses)
                        ),
                        Position,
                    )
                )
                or 0
            )
            realized_pnl = (
                await session.scalar(
                    self._with_active_chain(
                        select(func.coalesce(func.sum(Trade.pnl_usd), 0.0)).where(
                            Trade.trade_status.in_(["CLOSED", "REVIEWED"])
                        ),
                        Trade,
                    )
                )
                or 0.0
            )
            unrealized_pnl = (
                await session.scalar(
                    self._with_active_chain(
                        select(func.coalesce(func.sum(Position.unrealized_pnl_usd), 0.0)).where(
                            Position.status.in_(self.active_position_statuses)
                        ),
                        Position,
                    )
                )
                or 0.0
            )
            open_value = (
                await session.scalar(
                    self._with_active_chain(
                        select(func.coalesce(func.sum(Position.current_value), 0.0)).where(
                            Position.status.in_(self.active_position_statuses)
                        ),
                        Position,
                    )
                )
                or 0.0
            )
            latest_report = (
                await session.execute(select(DailyReport).order_by(DailyReport.id.desc()).limit(1))
            ).scalar_one_or_none()
            starting_balance = sum(wallet.paper_balance_usd for wallet in self.config.wallets if wallet.enabled)
            total_equity = starting_balance + realized_pnl + unrealized_pnl
            available_cash = total_equity - open_value

            wallet_summary = {
                "mode": self.config.system.mode,
                "chain": self.active_chain or self.config.system.chain,
                "starting_balance": starting_balance,
                "realized_pnl": realized_pnl,
                "unrealized_pnl": unrealized_pnl,
                "open_position_value": open_value,
                "total_equity": total_equity,
                "available_cash": available_cash,
                "active_positions": active_positions,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }

            await self.state_machine.set_runtime_state(session, "wallet_summary", wallet_summary)
            if self.active_chain:
                await self.state_machine.set_runtime_state(
                    session,
                    f"wallet_summary:{self.active_chain}",
                    wallet_summary,
                )
            await self.notifier.notify(
                "SYSTEM_STATUS",
                (
                    f"chain={self.active_chain or 'all'} "
                    f"new_signals={new_signals} "
                    f"active_candidates={active_candidates} "
                    f"active_positions={active_positions} "
                    f"equity={total_equity:.2f}"
                ),
                {
                    "latest_report_date": latest_report.report_date if latest_report else None,
                    "realized_pnl": realized_pnl,
                    "unrealized_pnl": unrealized_pnl,
                    "available_cash": available_cash,
                },
            )

    async def _daily_report(self) -> None:
        async with get_session() as session:
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
            await self.notifier.notify("DAILY_REPORT", f"daily pnl={report.total_pnl_usd}", {"date": report.report_date})

    def _with_active_chain(self, query, model):
        if self.active_chain:
            return query.where(model.chain == self.active_chain)
        return query
