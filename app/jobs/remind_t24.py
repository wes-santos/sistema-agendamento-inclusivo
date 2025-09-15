from __future__ import annotations

import uuid
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import configure_mappers, joinedload

import app.models  # noqa: F401
from app.core.settings import settings
from app.db.session import SessionLocal
from app.email.render import render
from app.models.appointment import ACTIVE_STATUSES, Appointment, AppointmentStatus
from app.models.appointment_token import AppointmentToken, TokenKind
from app.models.student import Student
from app.services.mailer import send_email
from app.utils.tz import to_local

BR = ZoneInfo("America/Sao_Paulo")

configure_mappers()


def _tomorrow_local_window_utc(now_local: datetime) -> tuple[datetime, datetime]:
    tomorrow = (now_local + timedelta(days=1)).date()
    start_local = datetime.combine(tomorrow, time(0, 0, 0, tzinfo=BR))
    end_local = datetime.combine(tomorrow, time(23, 59, 59, tzinfo=BR))
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


def _normalize_base(url: str | None) -> str:
    if not url:
        return "http://localhost:8000"
    url = url.strip()
    if not url:
        return "http://localhost:8000"
    if not (url.startswith("http://") or url.startswith("https://")):
        url = "http://" + url
    return url.rstrip("/")


def _public_url(path: str) -> str:
    base = _normalize_base(getattr(settings, "APP_PUBLIC_BASE_URL", None))
    if not path.startswith("/"):
        path = "/" + path
    return f"{base}{path}"


def _get_or_create_token(
    db, ap: Appointment, email: str, kind: TokenKind, ttl_hours: int = 48
) -> AppointmentToken:
    now = datetime.now(UTC)
    t = (
        db.query(AppointmentToken)
        .filter(
            AppointmentToken.appointment_id == ap.id,
            AppointmentToken.kind == kind,
            AppointmentToken.email == email,
            AppointmentToken.consumed_at.is_(None),
            AppointmentToken.expires_at > now,
        )
        .order_by(AppointmentToken.created_at.desc())
        .first()
    )
    if t:
        return t
    # cria novo
    t = AppointmentToken(
        token=uuid.uuid4(),
        appointment_id=ap.id,
        kind=kind,
        email=email,
        expires_at=now + timedelta(hours=ttl_hours),
    )
    db.add(t)
    db.flush()  # garante que o token está persistido p/ montar URL
    return t


def main() -> None:
    now_local = datetime.now(BR)
    start_utc, end_utc = _tomorrow_local_window_utc(now_local)

    sent = 0
    with SessionLocal() as db:
        appts = (
            db.query(Appointment)
            .options(
                joinedload(Appointment.student).joinedload(Student.guardian),
                joinedload(Appointment.professional),
            )
            .filter(
                Appointment.status.in_(ACTIVE_STATUSES),
                Appointment.reminder_24h_sent_at.is_(None),
                Appointment.starts_at >= start_utc,
                Appointment.starts_at <= end_utc,
            )
            .all()
        )

        for ap in appts:
            # Student has relationship 'guardian' (User); not 'guardian_user'
            guardian = getattr(ap.student, "guardian", None)
            recipient = getattr(guardian, "email", None) or getattr(
                settings, "FALLBACK_REMINDER_EMAIL", None
            )
            if not recipient:
                continue

            # tokens válidos (cria se não houver)
            cancel_t = _get_or_create_token(
                db, ap, recipient, TokenKind.CANCEL, ttl_hours=48
            )
            confirm_url = None
            if ap.status != AppointmentStatus.CONFIRMED:
                confirm_t = _get_or_create_token(
                    db, ap, recipient, TokenKind.CONFIRM, ttl_hours=48
                )
                confirm_url = _public_url(
                    f"/public/appointments/confirm/{confirm_t.token}"
                )

            cancel_url = _public_url(f"/public/appointments/cancel/{cancel_t.token}")

            starts_local_fmt = to_local(ap.starts_at, tz=BR).strftime("%d/%m %H:%M")
            ctx = {
                "student_name": ap.student.name,
                "professional_name": ap.professional.name,
                "service": ap.service,
                "location": ap.location,
                "starts_local": starts_local_fmt,
                "confirm_url": confirm_url,
                "cancel_url": cancel_url,
            }
            # Template name is 'appointment_reminder.html'
            html = render("appointment_reminder.html").render(ctx)
            subject = f"[SAI] Lembrete — amanhã {starts_local_fmt} ({ap.service})"

            from app.services.mailer import send_email

            send_email(subject, [recipient], html, text=None)

            ap.reminder_24h_sent_at = datetime.now(UTC)
            sent += 1

        db.commit()

    # evidência em log
    print(
        f"[remind_t24] {now_local.isoformat()} - enviados={sent} - "
        f"janelaUTC=({start_utc.isoformat()}→{end_utc.isoformat()})"
    )


if __name__ == "__main__":
    main()
