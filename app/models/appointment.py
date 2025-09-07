from __future__ import annotations

import datetime as dt
import enum
from sqlalchemy import (
    CheckConstraint,
    String,
    Integer,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base


class AppointmentStatus(str, enum.Enum):
    SCHEDULED = "SCHEDULED"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    DONE = "DONE"


class Appointment(Base):
    __tablename__ = "appointments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(
        ForeignKey("students.id", ondelete="RESTRICT"), nullable=False
    )
    professional_id: Mapped[int] = mapped_column(
        ForeignKey("professionals.id", ondelete="RESTRICT"), nullable=False
    )
    service: Mapped[str] = mapped_column(String(120), nullable=False)
    location: Mapped[str | None] = mapped_column(String(160))
    status: Mapped[AppointmentStatus] = mapped_column(
        Enum(AppointmentStatus, name="appointment_status_enum"),
        nullable=False,
        default=AppointmentStatus.SCHEDULED,
    )
    starts_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    ends_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: dt.datetime.now(tz=dt.UTC),
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: dt.datetime.now(tz=dt.UTC),
        onupdate=lambda: dt.datetime.now(tz=dt.UTC),
    )

    student = relationship("Student")
    professional = relationship("Professional")

    __table_args__ = (
        UniqueConstraint("professional_id", "starts_at", name="uq_appt_prof_start"),
        CheckConstraint("ends_at > starts_at", name="ck_appt_time_order"),
        Index("ix_appt_professional_id", "professional_id"),
        Index("ix_appt_student_id", "student_id"),
    )
