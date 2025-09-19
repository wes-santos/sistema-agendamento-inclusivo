from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_roles
from app.models.appointment import Appointment, AppointmentStatus
from app.models.user import Role, User
from app.schemas.dashboard_coordination import (
    CoordOverviewResponse,
    CoordRecentAppt,
    CoordSeriesDay,
    CoordSummary,
    CoordTopProfessional,
    CoordTopService,
)
from app.utils.week import DEFAULT_TZ, week_bounds_local

router = APIRouter(prefix="/dashboard/coordination", tags=["dashboard-coordination"])


@router.get("/overview", response_model=CoordOverviewResponse)
def coordination_overview(
    current_user: Annotated[User, Depends(require_roles(Role.COORDINATION))],
    db: Annotated[Session, Depends(get_db)],
    week_start: date | None = Query(
        default=None,
        description="Uma data dentro da semana desejada (YYYY-MM-DD). Se omitido, usa a semana atual.",
    ),
    date_from: date | None = Query(
        default=None,
        description="Alternativa: início da janela (YYYY-MM-DD). Se fornecido, ignora week_start.",
    ),
    date_to: date | None = Query(
        default=None,
        description="Alternativa: fim exclusivo da janela (YYYY-MM-DD). Se fornecido, ignora week_start.",
    ),
    tz_local: str = Query(
        default="America/Sao_Paulo", description="Timezone para agregações diárias"
    ),
    limit_lists: int = Query(
        default=10, ge=1, le=50, description="Tamanho das listas de topo/recents"
    ),
):
    # Resolve TZ
    from zoneinfo import ZoneInfo

    try:
        tz = ZoneInfo(tz_local)
    except Exception:
        tz = DEFAULT_TZ
        tz_local = "America/Sao_Paulo"

    # Define janela local (preferência: date_from/date_to > week_start > semana atual)
    if date_from and date_to:
        start_local = datetime.combine(date_from, datetime.min.time()).replace(
            tzinfo=tz
        )
        end_local = datetime.combine(date_to, datetime.min.time()).replace(tzinfo=tz)
    elif date_from and not date_to:
        start_local = datetime.combine(date_from, datetime.min.time()).replace(
            tzinfo=tz
        )
        end_local = start_local + timedelta(days=7)
    elif week_start:
        start_local, end_local = week_bounds_local(week_start, tz)
    else:
        today_local = datetime.now(tz).date()
        start_local, end_local = week_bounds_local(today_local, tz)

    # Converte bounds para UTC
    start_utc = start_local.astimezone(ZoneInfo("UTC"))
    end_utc = end_local.astimezone(ZoneInfo("UTC"))

    # -------- KPI counts
    base_q = db.query(Appointment).filter(
        and_(Appointment.starts_at >= start_utc, Appointment.starts_at < end_utc)
    )

    # count by status
    rows = (
        db.query(Appointment.status, func.count(Appointment.id))
        .filter(
            and_(Appointment.starts_at >= start_utc, Appointment.starts_at < end_utc)
        )
        .group_by(Appointment.status)
        .all()
    )
    count_by_status = {s: int(c) for (s, c) in rows}
    total_appointments = sum(count_by_status.values())
    cancel_rate = (
        (count_by_status.get(AppointmentStatus.CANCELLED, 0) / total_appointments)
        if total_appointments
        else 0.0
    )

    # ativos (distintos)
    professionals_active = (
        db.query(func.count(func.distinct(Appointment.professional_id)))
        .filter(
            and_(Appointment.starts_at >= start_utc, Appointment.starts_at < end_utc)
        )
        .scalar()
    ) or 0
    families_active = (
        db.query(func.count(func.distinct(Appointment.student_id)))
        .filter(
            and_(Appointment.starts_at >= start_utc, Appointment.starts_at < end_utc)
        )
        .scalar()
    ) or 0

    # today upcoming (local day window)
    day0 = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    day1 = day0 + timedelta(days=1)
    today_upcoming = (
        db.query(func.count(Appointment.id))
        .filter(
            and_(
                Appointment.starts_at >= day0.astimezone(ZoneInfo("UTC")),
                Appointment.starts_at < day1.astimezone(ZoneInfo("UTC")),
                Appointment.status != AppointmentStatus.CANCELLED,
            )
        )
        .scalar()
    ) or 0

    summary = CoordSummary(
        window_start_local=start_local.date(),
        window_end_local=end_local.date(),
        timezone=tz_local,
        total_appointments=total_appointments,
        count_by_status=count_by_status,
        cancel_rate=cancel_rate,
        professionals_active=int(professionals_active),
        families_active=int(families_active),
        today_upcoming=int(today_upcoming),
    )

    # -------- Série diária (agregação em Python para simplicidade)
    series_map: dict[date, dict[AppointmentStatus, int]] = {}
    # inicializa 0 para todos os 7 dias
    cur = start_local
    while cur < end_local:
        series_map[cur.date()] = {s: 0 for s in AppointmentStatus}
        cur += timedelta(days=1)

    # pega status+start para a janela e bucketiza por dia local
    for s, dt in db.query(Appointment.status, Appointment.starts_at).filter(
        and_(Appointment.starts_at >= start_utc, Appointment.starts_at < end_utc)
    ):
        d_local = dt.astimezone(tz).date()
        if d_local in series_map:
            series_map[d_local][s] = series_map[d_local].get(s, 0) + 1

    series_daily = [
        CoordSeriesDay(
            date_local=d,
            count_total=sum(counts.values()),
            count_by_status=counts,
        )
        for d, counts in sorted(series_map.items())
    ]

    # -------- Top profissionais (por contagem na janela)
    prof_rows = (
        db.query(Appointment.professional_id, func.count(Appointment.id).label("c"))
        .filter(
            and_(Appointment.starts_at >= start_utc, Appointment.starts_at < end_utc)
        )
        .group_by(Appointment.professional_id)
        .order_by(func.count(Appointment.id).desc())
        .limit(limit_lists)
        .all()
    )

    # tenta pegar nomes
    top_professionals: list[CoordTopProfessional] = []
    if prof_rows:
        prof_ids = [pid for (pid, _c) in prof_rows]
        name_map = {
            u.id: (getattr(u, "name", None) or getattr(u, "email", None))
            for u in db.query(User).filter(User.id.in_(prof_ids)).all()
        }
        for pid, c in prof_rows:
            top_professionals.append(
                CoordTopProfessional(
                    professional_id=int(pid),
                    professional_name=name_map.get(pid),
                    count=int(c),
                )
            )

    # -------- Top serviços
    svc_rows = (
        db.query(Appointment.service, func.count(Appointment.id).label("c"))
        .filter(
            and_(Appointment.starts_at >= start_utc, Appointment.starts_at < end_utc)
        )
        .group_by(Appointment.service)
        .order_by(func.count(Appointment.id).desc())
        .limit(limit_lists)
        .all()
    )
    top_services = [
        CoordTopService(service=s or "(sem descrição)", count=int(c))
        for (s, c) in svc_rows
    ]

    # -------- Recentes (ordenado por criação se houver; senão por starts_at desc)
    # Se seu model tiver created_at/updated_at timezone-aware, prefira created_at.
    recent_rows = (
        db.query(Appointment)
        .filter(
            and_(Appointment.starts_at >= start_utc, Appointment.starts_at < end_utc)
        )
        .order_by(getattr(Appointment, "created_at", Appointment.starts_at).desc())
        .limit(limit_lists)
        .all()
    )

    # mapear nomes
    student_name_map = {}
    student_ids = list({r.student_id for r in recent_rows})
    if student_ids:
        for u in db.query(User).filter(User.id.in_(student_ids)).all():
            student_name_map[u.id] = getattr(u, "name", None) or getattr(
                u, "email", None
            )

    prof_name_map = {}
    pro_ids = list({r.professional_id for r in recent_rows})
    if pro_ids:
        for u in db.query(User).filter(User.id.in_(pro_ids)).all():
            prof_name_map[u.id] = getattr(u, "name", None) or getattr(u, "email", None)

    recent = [
        CoordRecentAppt(
            id=r.id,
            service=r.service,
            status=r.status,
            start_at_utc=r.starts_at,
            start_at_local=r.starts_at.astimezone(tz),
            professional_id=r.professional_id,
            professional_name=prof_name_map.get(r.professional_id),
            student_id=r.student_id,
            student_name=student_name_map.get(r.student_id),
        )
        for r in recent_rows
    ]

    return CoordOverviewResponse(
        summary=summary,
        series_daily=series_daily,
        top_professionals=top_professionals,
        top_services=top_services,
        recent=recent,
    )
