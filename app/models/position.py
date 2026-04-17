from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Position(Base):
    __tablename__ = "positions"
    __table_args__ = (
        Index("ix_positions_status_wallet", "status", "wallet"),
        Index("ix_positions_candidate_status", "candidate_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    position_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"), nullable=False)
    signal_id: Mapped[Optional[int]] = mapped_column(ForeignKey("signals.id"))
    wallet: Mapped[str] = mapped_column(String(128), nullable=False)
    chain: Mapped[str] = mapped_column(String(32), nullable=False)
    ca: Mapped[str] = mapped_column(String(64), nullable=False)
    symbol: Mapped[str] = mapped_column(String(64), default="")
    strategy_name: Mapped[str] = mapped_column(String(128), nullable=False)
    entry_time: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc)
    )
    entry_price: Mapped[float] = mapped_column(default=0.0)
    entry_value: Mapped[float] = mapped_column(default=0.0)
    quantity_raw: Mapped[str] = mapped_column(String(128), default="0")
    current_price: Mapped[float] = mapped_column(default=0.0)
    current_value: Mapped[float] = mapped_column(default=0.0)
    unrealized_pnl_usd: Mapped[float] = mapped_column(default=0.0)
    unrealized_pnl_pct: Mapped[float] = mapped_column(default=0.0)
    highest_price_seen: Mapped[float] = mapped_column(default=0.0)
    lowest_price_seen: Mapped[float] = mapped_column(default=0.0)
    stop_loss_price: Mapped[float] = mapped_column(default=0.0)
    take_profit_price: Mapped[float] = mapped_column(default=0.0)
    trailing_stop_pct: Mapped[float] = mapped_column(default=0.0)
    status: Mapped[str] = mapped_column(String(32), default="OPEN")
    exit_reason: Mapped[str] = mapped_column(String(255), default="")
    exited_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
