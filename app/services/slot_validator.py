from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.models.appointment import ACTIVE_STATUSES, Appointment
from app.models.availability import Availability


def validate_slot(
    db: Session, professional_id: int, start_utc: datetime, slot_minutes: int
) -> tuple[bool, str | None]:
    """
    True se o slot [start, end) cabe em availability do dia (UTC) e não colide com appointments.
    """
    end_utc = start_utc + timedelta(minutes=slot_minutes)
    # availability por weekday (UTC)
    avs = (
        db.query(Availability)
        .filter(Availability.professional_id == professional_id)
        .all()
    )
    day_avs = [
        (a.starts_utc, a.ends_utc) for a in avs if a.weekday == start_utc.weekday()
    ]
    if not day_avs:
        return False, "Fora do horário de atendimento."

    s_t, e_t = start_utc.time(), end_utc.time()
    fits = any(s_t >= a0 and e_t <= a1 for (a0, a1) in day_avs)
    if not fits:
        return False, "Fora da janela disponível."

    # colisão com appointments (≠ CANCELLED)
    appts = (
        db.query(Appointment)
        .filter(
            and_(
                Appointment.professional_id == professional_id,
                Appointment.status.in_(ACTIVE_STATUSES),  # <<< aqui
                Appointment.starts_at < end_utc,
                Appointment.ends_at > start_utc,
            )
        )
        .all()
    )
    if appts:
        return False, "Horário já ocupado."
    return True, None
