from __future__ import annotations

from sqlalchemy import String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class DailyReport(Base):
    __tablename__ = "daily_reports"
    __table_args__ = (UniqueConstraint("report_date", name="uq_daily_reports_report_date"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    report_date: Mapped[str] = mapped_column(String(32), nullable=False)
    total_pnl_usd: Mapped[float] = mapped_column(default=0.0)
    total_trades: Mapped[int] = mapped_column(default=0)
    win_rate: Mapped[float] = mapped_column(default=0.0)
    average_rr: Mapped[float] = mapped_column(default=0.0)
    max_drawdown: Mapped[float] = mapped_column(default=0.0)
    best_source: Mapped[str] = mapped_column(String(128), default="")
    worst_source: Mapped[str] = mapped_column(String(128), default="")
    fill_rate: Mapped[float] = mapped_column(default=0.0)
    report_json: Mapped[str] = mapped_column(default="{}")
