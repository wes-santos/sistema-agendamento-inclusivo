from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.core.settings import settings
from app.db.session import SessionLocal
from app.email.render import render
from app.models.appointment import Appointment
from app.models.appointment_token import AppointmentToken, TokenKind
from app.models.professional import Professional
from app.models.student import Student
from app.models.user import User
from app.services.mailer import send_email
from app.utils.tz import to_local

BR_TZ = ZoneInfo("America/Sao_Paulo")


def _normalize_base(url: str | None) -> str:
    if not url:
        return "http://localhost:8000"
    url = url.strip()
    if not url:
        return "http://localhost:8000"
    if not (url.startswith("http://") or url.startswith("https://")):
        # treat as host[:port] without scheme
        url = "http://" + url
    return url.rstrip("/")


def _make_link(path: str) -> str:
    # Always build absolute, well-formed links for emails
    base = _normalize_base(getattr(settings, "APP_PUBLIC_BASE_URL", None))
    if not path.startswith("/"):
        path = "/" + path
    return f"{base}{path}"


def create_tokens_for_appointment(
    db: Session, ap: Appointment, email: str, hours: int = 48
) -> tuple[uuid.UUID, uuid.UUID]:
    now = datetime.now(UTC)
    expires = now + timedelta(hours=hours)

    t1 = AppointmentToken(
        appointment_id=ap.id,
        kind=TokenKind.CONFIRM,
        email=email,
        expires_at=expires,
        created_at=now,
    )
    t2 = AppointmentToken(
        appointment_id=ap.id,
        kind=TokenKind.CANCEL,
        email=email,
        expires_at=expires,
        created_at=now,
    )
    db.add_all([t1, t2])
    db.flush()  # gera UUIDs
    return t1.token, t2.token


def send_confirmation_email_bg(
    appointment_id: int,
    guardian_user_id: int,
    confirm_token: str,
    cancel_token: str,
    expires_human: str = "48 horas",
):
    with SessionLocal() as db:
        ap = db.get(Appointment, appointment_id)
        if not ap:
            return
        guardian = db.get(User, guardian_user_id)
        if not guardian:
            return
        student = db.get(Student, ap.student_id)
        prof = db.get(Professional, ap.professional_id)

        starts_local = to_local(ap.starts_at, BR_TZ).strftime("%d/%m/%Y %H:%M")
        confirm_url = _make_link(f"/public/appointments/confirm/{confirm_token}")
        cancel_url = _make_link(f"/public/appointments/cancel/{cancel_token}")

        ctx = {
            "guardian_name": guardian.name,
            "student_name": student.name if student else "Estudante",
            "professional_name": prof.name if prof else "Profissional",
            "starts_local": starts_local,
            "confirm_url": confirm_url,
            "cancel_url": cancel_url,
            "expires_human": expires_human,
        }

        html_confirm = render("confirm.html").render(ctx)
        # inclui link de cancelamento ao final do e-mail de confirmação
        html = html_confirm.replace(
            "</body>",
            f'<p style="margin-top:16px">Se precisar, você pode '
            f'<a href="{cancel_url}">cancelar o agendamento</a>.</p></body>',
        )
        subject = f"[SAI] Confirme seu agendamento — {starts_local}"
        send_email(subject, [guardian.email], html, text=None)
