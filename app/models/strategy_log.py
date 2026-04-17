from __future__ import annotations

from typing import Optional

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class StrategyLog(Base):
    __tablename__ = "strategy_logs"
    __table_args__ = (Index("ix_strategy_logs_strategy_event", "strategy_name", "event"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    strategy_name: Mapped[str] = mapped_column(String(128), nullable=False)
    event: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_id: Mapped[Optional[int]] = mapped_column(ForeignKey("candidates.id"))
    signal_id: Mapped[Optional[int]] = mapped_column(ForeignKey("signals.id"))
    position_id: Mapped[Optional[int]] = mapped_column(ForeignKey("positions.id"))
    order_id: Mapped[Optional[int]] = mapped_column(ForeignKey("orders.id"))
    message: Mapped[str] = mapped_column(String(255), default="")
    snapshot: Mapped[str] = mapped_column(Text, default="{}")
