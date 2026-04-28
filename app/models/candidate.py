from __future__ import annotations

from sqlalchemy import Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Candidate(Base):
    __tablename__ = "candidates"
    __table_args__ = (
        UniqueConstraint("chain", "ca", name="uq_candidates_chain_ca"),
        Index("ix_candidates_status_priority", "status", "priority"),
        Index("ix_candidates_chain_status_priority", "chain", "status", "priority"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    candidate_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    chain: Mapped[str] = mapped_column(String(32), nullable=False)
    ca: Mapped[str] = mapped_column(String(64), nullable=False)
    symbol: Mapped[str] = mapped_column(String(64), default="")
    narrative: Mapped[str] = mapped_column(String(255), default="")
    aggregated_signal_score: Mapped[float] = mapped_column(default=0.0)
    aggregated_risk_score: Mapped[float] = mapped_column(default=0.0)
    liquidity: Mapped[float] = mapped_column(default=0.0)
    market_cap: Mapped[float] = mapped_column(default=0.0)
    holder_count: Mapped[int] = mapped_column(default=0)
    top10_rate: Mapped[float] = mapped_column(default=0.0)
    bundler_rate: Mapped[float] = mapped_column(default=0.0)
    bot_rate: Mapped[float] = mapped_column(default=0.0)
    status: Mapped[str] = mapped_column(String(32), default="NEW")
    reject_reason: Mapped[str] = mapped_column(String(255), default="")
    strategy_name: Mapped[str] = mapped_column(String(128), default="")
    priority: Mapped[int] = mapped_column(default=0)
    last_signal_at: Mapped[str] = mapped_column(String(64), default="")
    last_buy_attempt_at: Mapped[str] = mapped_column(String(64), default="")
