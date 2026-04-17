from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Trade(Base):
    __tablename__ = "trades"
    __table_args__ = (Index("ix_trades_trade_status", "trade_status"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    trade_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    position_id: Mapped[int] = mapped_column(ForeignKey("positions.id"), nullable=False)
    candidate_id: Mapped[Optional[int]] = mapped_column(ForeignKey("candidates.id"))
    signal_id: Mapped[Optional[int]] = mapped_column(ForeignKey("signals.id"))
    signal_source: Mapped[str] = mapped_column(String(64), default="")
    strategy_name: Mapped[str] = mapped_column(String(128), nullable=False)
    wallet: Mapped[str] = mapped_column(String(128), nullable=False)
    chain: Mapped[str] = mapped_column(String(32), nullable=False)
    ca: Mapped[str] = mapped_column(String(64), nullable=False)
    symbol: Mapped[str] = mapped_column(String(64), default="")
    why_enter: Mapped[str] = mapped_column(String(255), default="")
    why_exit: Mapped[str] = mapped_column(String(255), default="")
    expected_logic: Mapped[str] = mapped_column(String(255), default="")
    actual_result: Mapped[str] = mapped_column(String(255), default="")
    entry_time: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc)
    )
    exit_time: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    hold_minutes: Mapped[float] = mapped_column(default=0.0)
    entry_price: Mapped[float] = mapped_column(default=0.0)
    exit_price: Mapped[float] = mapped_column(default=0.0)
    entry_value: Mapped[float] = mapped_column(default=0.0)
    exit_value: Mapped[float] = mapped_column(default=0.0)
    pnl_usd: Mapped[float] = mapped_column(default=0.0)
    pnl_pct: Mapped[float] = mapped_column(default=0.0)
    slippage_loss: Mapped[float] = mapped_column(default=0.0)
    gas_cost: Mapped[float] = mapped_column(default=0.0)
    pass_or_fail: Mapped[str] = mapped_column(String(32), default="")
    lesson_tag: Mapped[str] = mapped_column(String(128), default="")
    exit_trigger_type: Mapped[str] = mapped_column(String(64), default="")
    trade_status: Mapped[str] = mapped_column(String(32), default="OPENING")
