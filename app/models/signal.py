from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Signal(Base):
    __tablename__ = "signals"
    __table_args__ = (
        UniqueConstraint("signal_id", name="uq_signals_signal_id"),
        Index("ix_signals_ca_status", "ca", "processing_status"),
        Index("ix_signals_discovered_at", "discovered_at"),
        Index("ix_signals_chain_status_discovered", "chain", "processing_status", "discovered_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    signal_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_detail: Mapped[str] = mapped_column(String(255), default="")
    chain: Mapped[str] = mapped_column(String(32), nullable=False)
    ca: Mapped[str] = mapped_column(String(64), nullable=False)
    symbol: Mapped[str] = mapped_column(String(64), default="")
    narrative: Mapped[str] = mapped_column(String(255), default="")
    content: Mapped[str] = mapped_column(Text, default="")
    raw_payload: Mapped[str] = mapped_column(Text, default="{}")
    signal_score: Mapped[float] = mapped_column(default=0.0)
    risk_score: Mapped[float] = mapped_column(default=0.0)
    liquidity: Mapped[float] = mapped_column(default=0.0)
    market_cap: Mapped[float] = mapped_column(default=0.0)
    holder_count: Mapped[int] = mapped_column(default=0)
    top10_rate: Mapped[float] = mapped_column(default=0.0)
    bundler_rate: Mapped[float] = mapped_column(default=0.0)
    bot_rate: Mapped[float] = mapped_column(default=0.0)
    processing_status: Mapped[str] = mapped_column(String(32), default="NEW")
    error_reason: Mapped[str] = mapped_column(String(255), default="")
    discovered_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc)
    )
