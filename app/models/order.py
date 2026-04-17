from __future__ import annotations

from typing import Optional

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_orders_idempotency_key"),
        Index("ix_orders_status_side", "status", "side"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    candidate_id: Mapped[Optional[int]] = mapped_column(ForeignKey("candidates.id"))
    position_id: Mapped[Optional[int]] = mapped_column(ForeignKey("positions.id"))
    signal_id: Mapped[Optional[int]] = mapped_column(ForeignKey("signals.id"))
    wallet: Mapped[str] = mapped_column(String(128), nullable=False)
    chain: Mapped[str] = mapped_column(String(32), nullable=False)
    ca: Mapped[str] = mapped_column(String(64), nullable=False)
    symbol: Mapped[str] = mapped_column(String(64), default="")
    side: Mapped[str] = mapped_column(String(16), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="paper")
    quantity_raw: Mapped[str] = mapped_column(String(128), default="0")
    price: Mapped[float] = mapped_column(default=0.0)
    value_usd: Mapped[float] = mapped_column(default=0.0)
    status: Mapped[str] = mapped_column(String(32), default="PENDING")
    fail_reason: Mapped[str] = mapped_column(String(255), default="")
    tx_hash: Mapped[str] = mapped_column(String(255), default="")
    retries: Mapped[int] = mapped_column(default=0)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
