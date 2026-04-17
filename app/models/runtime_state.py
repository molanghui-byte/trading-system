from __future__ import annotations

from sqlalchemy import String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class RuntimeState(Base):
    __tablename__ = "runtime_state"
    __table_args__ = (UniqueConstraint("state_key", name="uq_runtime_state_state_key"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    state_key: Mapped[str] = mapped_column(String(128), nullable=False)
    state_json: Mapped[str] = mapped_column(default="{}")
