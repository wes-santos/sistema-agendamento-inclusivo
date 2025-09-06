# app/models/audit_log.py
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_timestamp_utc", "timestamp_utc"),
        Index("ix_audit_user_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    action: Mapped[str] = mapped_column(
        String(80), nullable=False
    )  # e.g. "CREATE","UPDATE","LOGIN"
    entity: Mapped[str] = mapped_column(
        String(80), nullable=False
    )  # e.g. "appointment","student"
    entity_id: Mapped[int | None] = mapped_column(Integer)
    timestamp_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    ip: Mapped[str | None] = mapped_column(INET)

    user = relationship("User")
