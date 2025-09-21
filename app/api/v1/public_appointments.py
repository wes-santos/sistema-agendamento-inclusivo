from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.appointment import Appointment, AppointmentStatus
from app.models.appointment_token import AppointmentToken, TokenKind
from app.models.student import Student
from app.models.professional import Professional
from app.models.user import User
from app.services.mailer import send_email
from app.email.render import render as render_email
from zoneinfo import ZoneInfo

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


def _send_professional_notification(db: Session, appointment: Appointment, action: str):
    """Send notification to professional when appointment is confirmed or cancelled"""
    try:
        # Get related objects
        student = db.query(Student).filter(Student.id == appointment.student_id).first()
        professional = db.query(Professional).filter(Professional.id == appointment.professional_id).first()
        
        if not student or not professional:
            return
            
        # Get guardian user
        guardian_user = db.query(User).filter(User.id == student.guardian_user_id).first()
        if not guardian_user:
            return
        
        # Format date for email
        tz = ZoneInfo("America/Sao_Paulo")
        starts_local = appointment.starts_at.astimezone(tz).strftime("%d/%m/%Y %H:%M")
        
        # Check if professional has an email
        if not hasattr(professional, 'user') or not professional.user or not professional.user.email:
            return
            
        # Prepare email context
        ctx = {
            "professional_name": professional.name,
            "guardian_name": guardian_user.name,
            "student_name": student.name,
            "service_name": appointment.service,
            "starts_local": starts_local,
            "location": appointment.location or "Não especificado",
        }
        
        # Select template and subject based on action
        if action == "confirmed":
            html = render_email("appointment_confirmed_professional.html").render(ctx)
            subject = f"[SAI] Agendamento confirmado - {starts_local}"
        elif action == "cancelled":
            html = render_email("appointment_cancelled_professional.html").render(ctx)
            subject = f"[SAI] Agendamento cancelado - {starts_local}"
        else:
            return
            
        # Send email to professional
        send_email(subject, [professional.user.email], html, text=None)
    except Exception as e:
        # Log error but don't fail the main operation
        print(f"Failed to send professional notification: {e}")


@router.get("/confirm/{token}")
def confirm_appointment(token: uuid.UUID, db: Session = Depends(get_db)):
    # Debug: Log that we're hitting this route
    print(f"DEBUG: confirm_appointment called with token: {token}")
    
    t = db.get(AppointmentToken, token)
    print(f"DEBUG: Token lookup result: {t}")
    
    if not t or t.kind != TokenKind.CONFIRM:
        print(f"DEBUG: Token invalid or wrong kind. Token: {t}, Kind: {t.kind if t else 'None'}")
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
    
    # Send notification to professional
    _send_professional_notification(db, ap, "confirmed")
    
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
    
    # Send notification to professional
    _send_professional_notification(db, ap, "cancelled")
    
    return _ok_page("Agendamento cancelado", "Seu agendamento foi cancelado.")
