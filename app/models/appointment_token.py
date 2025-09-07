from __future__ import annotations

import datetime as dt
import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import Base


class TokenKind(str, enum.Enum):
    CONFIRM = "CONFIRM"
    CANCEL = "CANCEL"


class AppointmentToken(Base):
    __tablename__ = "appointment_tokens"

    # token é o próprio PK (UUID)
    token: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    appointment_id: Mapped[int] = mapped_column(
        ForeignKey("appointments.id", ondelete="CASCADE"), index=True, nullable=False
    )
    kind: Mapped[TokenKind] = mapped_column(
        Enum(TokenKind, name="appointment_token_kind"), nullable=False
    )
    email: Mapped[str] = mapped_column(nullable=False)  # destinatário
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: dt.datetime.now(tz=dt.UTC),
    )
