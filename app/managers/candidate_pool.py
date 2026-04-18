from __future__ import annotations

import json

from sqlalchemy import case, func, select

from app.models import Candidate, CandidateSignal, Signal, StrategyLog


class CandidatePoolManager:
    def __init__(self, config, notifier, state_machine, strategy, risk_manager) -> None:
        self.config = config
        self.notifier = notifier
        self.state_machine = state_machine
        self.strategy = strategy
        self.risk_manager = risk_manager

    async def ingest_signals(self, session) -> None:
        chain_priority = self._chain_priority_case(Signal.chain)
        result = await session.execute(
            select(Signal)
            .where(Signal.processing_status == "NEW")
            .order_by(chain_priority.asc(), Signal.discovered_at.asc())
            .limit(self.config.candidate_pool.max_candidates_per_cycle)
        )
        for signal in result.scalars().all():
            if signal.signal_score < self.config.candidate_pool.min_signal_score:
                await self.state_machine.transition_signal(session, signal, "IGNORED", "signal_score_too_low")
                await self.notifier.notify("SIGNAL_IGNORED", f"ignored low score signal {signal.signal_id}", {"signal_id": signal.id})
                continue
            candidate_result = await session.execute(
                select(Candidate).where(Candidate.chain == signal.chain, Candidate.ca == signal.ca)
            )
            candidate = candidate_result.scalar_one_or_none()
            if not candidate:
                candidate = Candidate(
                    candidate_id=f"{signal.chain}:{signal.ca}",
                    chain=signal.chain,
                    ca=signal.ca,
                    symbol=signal.symbol,
                    narrative=signal.narrative,
                    aggregated_signal_score=signal.signal_score,
                    aggregated_risk_score=signal.risk_score,
                    liquidity=signal.liquidity,
                    market_cap=signal.market_cap,
                    holder_count=signal.holder_count,
                    top10_rate=signal.top10_rate,
                    bundler_rate=signal.bundler_rate,
                    bot_rate=signal.bot_rate,
                    status="NEW",
                    strategy_name=self.strategy.name,
                    last_signal_at=signal.discovered_at.isoformat(),
                )
                session.add(candidate)
                await session.flush()
                await self.state_machine.transition_candidate(session, candidate, "DISCOVERED")
                await self.notifier.notify("CANDIDATE_CREATED", f"candidate created for {signal.ca}", {"candidate_id": candidate.id})
            else:
                signal_count = int(
                    await session.scalar(
                        select(func.count()).select_from(CandidateSignal).where(CandidateSignal.candidate_id == candidate.id)
                    )
                    or 0
                ) + 1
                candidate.aggregated_signal_score = ((candidate.aggregated_signal_score * (signal_count - 1)) + signal.signal_score) / signal_count
                candidate.aggregated_risk_score = max(candidate.aggregated_risk_score, signal.risk_score)
                candidate.liquidity = max(candidate.liquidity, signal.liquidity)
                candidate.market_cap = max(candidate.market_cap, signal.market_cap)
                candidate.holder_count = max(candidate.holder_count, signal.holder_count)
                candidate.top10_rate = max(candidate.top10_rate, signal.top10_rate)
                candidate.bundler_rate = max(candidate.bundler_rate, signal.bundler_rate)
                candidate.bot_rate = max(candidate.bot_rate, signal.bot_rate)
                candidate.last_signal_at = signal.discovered_at.isoformat()
            existing_link = await session.execute(
                select(CandidateSignal).where(
                    CandidateSignal.candidate_id == candidate.id,
                    CandidateSignal.signal_id == signal.id,
                )
            )
            if not existing_link.scalar_one_or_none():
                session.add(CandidateSignal(candidate_id=candidate.id, signal_id=signal.id))
            session.add(
                StrategyLog(
                    strategy_name=self.strategy.name,
                    event="CANDIDATE_LINKED_SIGNAL",
                    candidate_id=candidate.id,
                    signal_id=signal.id,
                    message="signal linked to candidate",
                    snapshot=json.dumps({"signal_id": signal.signal_id}, ensure_ascii=False),
                )
            )
            await self.state_machine.transition_signal(session, signal, "LINKED")

    async def process_candidates(self, session) -> list[Candidate]:
        chain_priority = self._chain_priority_case(Candidate.chain)
        result = await session.execute(
            select(Candidate)
            .where(Candidate.status.in_(["DISCOVERED", "CHECKED"]))
            .order_by(chain_priority.asc(), Candidate.priority.desc(), Candidate.updated_at.asc())
        )
        accepted: list[Candidate] = []
        for candidate in result.scalars().all():
            if candidate.status == "DISCOVERED":
                await self.state_machine.transition_candidate(session, candidate, "CHECKED")
            decision = await self.strategy.evaluate(session, candidate, holding_open=False)
            candidate.priority = decision.priority
            risk_decision = await self.risk_manager.evaluate_candidate(session, candidate)
            if not risk_decision.allowed:
                await self.state_machine.transition_candidate(session, candidate, "REJECTED", risk_decision.reason)
                await self.notifier.notify("CANDIDATE_REJECTED", f"candidate rejected {candidate.ca}", {"candidate_id": candidate.id, "reason": risk_decision.reason})
                continue
            if decision.should_buy:
                await self.state_machine.transition_candidate(session, candidate, "BUY_PENDING", decision.buy_reason)
                accepted.append(candidate)
                await self.notifier.notify("CANDIDATE_ACCEPTED", f"candidate accepted {candidate.ca}", {"candidate_id": candidate.id, "reason": decision.buy_reason})
            else:
                await self.state_machine.transition_candidate(session, candidate, "REJECTED", decision.buy_reason)
                await self.notifier.notify("CANDIDATE_REJECTED", f"candidate rejected {candidate.ca}", {"candidate_id": candidate.id, "reason": decision.buy_reason})
        return accepted

    def _chain_priority_case(self, column):
        ordered_chains = [self.config.candidate_pool.primary_chain, *self.config.candidate_pool.secondary_chains]
        return case(
            {chain: index for index, chain in enumerate(ordered_chains)},
            value=column,
            else_=len(ordered_chains),
        )
