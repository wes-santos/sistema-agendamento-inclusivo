from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.appointment import Appointment, AppointmentStatus
from app.models.appointment_token import AppointmentToken, TokenKind

router = APIRouter(prefix="/public/appointments", tags=["public"])


def _consume(db: Session, token: AppointmentToken):
    token.consumed_at = datetime.now(UTC)
    db.add(token)


def _ok_page(title: str, message: str) -> HTMLResponse:
    html = f"""
    <!doctype html>
    <meta charset='utf-8'>
    <title>{title}</title>
    <body style='font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial;line-height:1.5;padding:2rem'>
      <h2 style='margin:0 0 12px'>{title}</h2>
      <p style='margin:0 0 12px'>{message}</p>
      <p style='margin-top:16px'>
        <a href='/family/dashboard' style='display:inline-block;padding:.6rem .9rem;border:1px solid #ccc;border-radius:8px;text-decoration:none'>Voltar ao painel</a>
      </p>
    </body>
    """
    return HTMLResponse(html)


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
    return _ok_page("Presença confirmada", "Seu agendamento foi confirmado com sucesso.")


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
    return _ok_page("Agendamento cancelado", "Seu agendamento foi cancelado.")
