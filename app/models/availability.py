from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    PrimaryKeyConstraint,
    Time,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Availability(Base):
    """
    Janelas semanais recorrentes em UTC.
    PK composta para evitar duplicatas por (profissional, dia, início).
    """

    __tablename__ = "availability"
    __table_args__ = (
        PrimaryKeyConstraint(
            "professional_id", "weekday", "starts_utc", name="pk_availability"
        ),
        CheckConstraint(
            "weekday >= 0 AND weekday <= 6", name="ck_availability_weekday"
        ),
        CheckConstraint("ends_utc > starts_utc", name="ck_availability_time_order"),
    )

    professional_id: Mapped[int] = mapped_column(
        ForeignKey("professionals.id", ondelete="CASCADE"), nullable=False
    )
    weekday: Mapped[int] = mapped_column(
        Integer, nullable=False
    )  # 0=segunda ... 6=domingo
    starts_utc: Mapped = mapped_column(Time(), nullable=False)  # time do dia em UTC
    ends_utc: Mapped = mapped_column(Time(), nullable=False)

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(tz=dt.UTC),
        nullable=False,
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(tz=dt.UTC),
        onupdate=lambda: dt.datetime.now(tz=dt.UTC),
        nullable=False,
    )
