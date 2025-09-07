from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.appointment import Appointment, AppointmentStatus
from app.models.appointment_token import AppointmentToken, TokenKind

router = APIRouter(prefix="/public/appointments", tags=["public"])


def _consume(db: Session, token: AppointmentToken):
    token.consumed_at = datetime.now(UTC)
    db.add(token)


@router.get("/confirm/{token}")
def confirm_appointment(token: uuid.UUID, db: Session = Depends(get_db)):
    t = db.get(AppointmentToken, token)
    if not t or t.kind != TokenKind.CONFIRM:
        raise HTTPException(404, "Token inválido")
    if t.consumed_at is not None:
        raise HTTPException(410, "Token já utilizado")
    if t.expires_at <= datetime.now(UTC):
        raise HTTPException(410, "Token expirado")

    ap = db.get(Appointment, t.appointment_id)
    if not ap:
        raise HTTPException(404, "Agendamento não encontrado")

    ap.status = AppointmentStatus.CONFIRMED
    _consume(db, t)
    db.commit()
    return {"ok": True, "message": "Agendamento confirmado."}


@router.get("/cancel/{token}")
def cancel_appointment(token: uuid.UUID, db: Session = Depends(get_db)):
    t = db.get(AppointmentToken, token)
    if not t or t.kind != TokenKind.CANCEL:
        raise HTTPException(404, "Token inválido")
    if t.consumed_at is not None:
        raise HTTPException(410, "Token já utilizado")
    if t.expires_at <= datetime.now(UTC):
        raise HTTPException(410, "Token expirado")

    ap = db.get(Appointment, t.appointment_id)
    if not ap:
        raise HTTPException(404, "Agendamento não encontrado")

    ap.status = AppointmentStatus.CANCELLED
    _consume(db, t)
    db.commit()
    return {"ok": True, "message": "Agendamento cancelado."}
