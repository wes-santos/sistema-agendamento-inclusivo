from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_roles
from app.models.appointment import Appointment, AppointmentStatus
from app.models.student import Student
from app.models.user import Role, User
from app.schemas.dashboard_family import (
    StudentApptItem,
    StudentApptResponse,
    StudentApptSummary,
)

router = APIRouter(prefix="/dashboard/student", tags=["dashboard-student"])

RangeType = Annotated[
    Literal["upcoming", "past", "all"], Query(description="Intervalo de tempo")
]


@router.get("/appointments", response_model=StudentApptResponse)
def list_my_appointments(  # noqa: PLR0913
    current_user: User = Depends(require_roles(Role.FAMILY)),
    db: Session = Depends(get_db),
    range: RangeType = "upcoming",
    status: list[AppointmentStatus] | None = Query(
        default=None, description="Filtrar por status (multi)"
    ),
    date_from: datetime | None = Query(
        default=None, description="Filtrar por início >= (ISO 8601)"
    ),
    date_to: datetime | None = Query(
        default=None, description="Filtrar por início < (ISO 8601)"
    ),
    q: str | None = Query(
        default=None, description="Busca por texto: service/location"
    ),
    page: int = 1,
    page_size: int = 10,
    tz_local: str | None = Query(
        default="America/Sao_Paulo", description="TZ para campos *_local"
    ),
):
    # Monta filtros base
    now_utc = datetime.now(UTC)
    conds = []

    if range == "upcoming":
        conds.append(Appointment.starts_at >= now_utc)
    elif range == "past":
        conds.append(Appointment.starts_at < now_utc)

    if status:
        conds.append(Appointment.status.in_(status))

    if date_from:
        conds.append(Appointment.starts_at >= date_from)
    if date_to:
        conds.append(Appointment.starts_at < date_to)

    if q:
        like = f"%{q}%"
        conds.append(
            or_(Appointment.service.ilike(like), Appointment.location.ilike(like))
        )

    # Sempre filtra por alunos sob o responsável logado
    query = (
        db.query(Appointment)
        .join(Student, Appointment.student_id == Student.id)
        .filter(and_(Student.guardian_user_id == current_user.id, *conds))
        .order_by(Appointment.starts_at.asc())
    )

    # total antes da paginação
    total_items = query.count()

    # paginação
    page = max(1, page)
    page_size = max(1, min(100, page_size))
    items = query.offset((page - 1) * page_size).limit(page_size).all()

    # resumo (counts + próximo agendamento)
    # counts
    base = (
        db.query(Appointment.status, func.count(Appointment.id))
        .join(Student, Appointment.student_id == Student.id)
        .filter(Student.guardian_user_id == current_user.id)
        .group_by(Appointment.status)
        .all()
    )
    count_by_status = {
        s.value if isinstance(s, AppointmentStatus) else str(s): c for (s, c) in base
    }

    # próximo agendamento
    next_appt = (
        db.query(Appointment)
        .join(Student, Appointment.student_id == Student.id)
        .filter(
            Student.guardian_user_id == current_user.id,
            Appointment.starts_at >= now_utc,
            Appointment.status != AppointmentStatus.CANCELLED,
        )
        .order_by(Appointment.starts_at.asc())
        .first()
    )

    # montar resposta
    # detect tz
    tz = None
    if tz_local:
        try:
            from zoneinfo import ZoneInfo

            tz = ZoneInfo(tz_local)
        except Exception:
            tz = None

    def _item(ap: Appointment) -> StudentApptItem:
        # tenta pegar nome do professional se a relationship existir; senão devolve None e mantém o id
        prof_name = None
        try:
            prof_name = getattr(ap.professional, "email", None) or getattr(
                ap.professional, "name", None
            )
        except Exception:
            prof_name = None

        return StudentApptItem(
            id=ap.id,
            service=ap.service,
            status=ap.status,
            start_at_utc=ap.starts_at,
            end_at_utc=ap.ends_at,
            start_at_local=(ap.starts_at.astimezone(tz) if tz else None),
            end_at_local=(ap.ends_at.astimezone(tz) if tz else None),
            location=ap.location,
            professional_id=ap.professional_id,
            professional_name=prof_name,
        )

    summary = StudentApptSummary(
        total_upcoming=int(
            count_by_status.get("SCHEDULED", 0) + count_by_status.get("CONFIRMED", 0)
        ),
        total_past=int(count_by_status.get("DONE", 0)),
        total_cancelled=int(count_by_status.get("CANCELLED", 0)),
        next_appointment_start_utc=(next_appt.starts_at if next_appt else None),
        next_appointment_service=(next_appt.service if next_appt else None),
    )

    return StudentApptResponse(
        summary=summary,
        page=page,
        page_size=page_size,
        total_items=total_items,
        items=[_item(ap) for ap in items],
    )
