from __future__ import annotations

from sqlalchemy import String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class TrackedWallet(Base):
    __tablename__ = "tracked_wallets"
    __table_args__ = (UniqueConstraint("wallet", name="uq_tracked_wallets_wallet"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    wallet: Mapped[str] = mapped_column(String(128), nullable=False)
    chain: Mapped[str] = mapped_column(String(32), nullable=False, default="bsc")
    label: Mapped[str] = mapped_column(String(128), default="")
    is_active: Mapped[bool] = mapped_column(default=True)
