from __future__ import annotations

from sqlalchemy import ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class CandidateSignal(Base):
    __tablename__ = "candidate_signals"
    __table_args__ = (
        UniqueConstraint(
            "candidate_id", "signal_id", name="uq_candidate_signals_candidate_signal"
        ),
        Index("ix_candidate_signals_signal_id", "signal_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"), nullable=False)
    signal_id: Mapped[int] = mapped_column(ForeignKey("signals.id"), nullable=False)
