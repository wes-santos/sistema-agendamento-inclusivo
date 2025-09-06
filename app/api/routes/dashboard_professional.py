from __future__ import annotations

from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_roles
from app.models.appointment import Appointment, AppointmentStatus
from app.models.user import Role, User
from app.schemas.dashboard_professional import (
    ProApptItem,
    ProDaySchedule,
    ProWeekResponse,
    ProWeekSummary,
)
from app.utils.week import DEFAULT_TZ, week_bounds_local

router = APIRouter(prefix="/dashboard/professional", tags=["dashboard-professional"])


@router.get("/schedule/week", response_model=ProWeekResponse)
def my_week_schedule(
    current_user: Annotated[User, Depends(require_roles(Role.PROFESSIONAL))],
    db: Annotated[Session, Depends(get_db)],
    week_start: date | None = Query(
        default=None,
        description=(
            "Data (YYYY-MM-DD) que pertence à semana desejada. "
            "Se omitida, usa a semana da data atual (TZ local)."
        ),
    ),
    tz_local: str = Query(
        default="America/Sao_Paulo", description="Timezone para agrupar por dia"
    ),
    statuses: list[AppointmentStatus] | None = Query(
        default=None, description="Filtrar status (multi)"
    ),
):
    # Resolve TZ
    from zoneinfo import ZoneInfo

    try:
        tz = ZoneInfo(tz_local)
    except Exception:
        tz = DEFAULT_TZ

    # Define semana (segunda 00:00 → próxima segunda 00:00) na TZ local
    from datetime import datetime

    today_local = datetime.now(tz).date()
    anchor = week_start or today_local
    start_local, end_local = week_bounds_local(anchor, tz)

    # Converte os bounds para UTC para consultar corretamente quem cruza a fronteira
    start_utc = start_local.astimezone(tz=ZoneInfo("UTC"))
    end_utc = end_local.astimezone(tz=ZoneInfo("UTC"))

    # Filtros base
    conds = [
        Appointment.professional_id == current_user.id,
        Appointment.start_at >= start_utc,
        Appointment.start_at < end_utc,
    ]
    if statuses:
        conds.append(Appointment.status.in_(statuses))
    else:
        # Por padrão, exclui CANCELLED da visão semanal (ajuste se quiser incluir)
        from sqlalchemy import not_

        conds.append(not_(Appointment.status == AppointmentStatus.CANCELLED))

    # Query itens
    q = db.query(Appointment).filter(and_(*conds)).order_by(Appointment.start_at.asc())
    appts = q.all()

    # Agrupar por dia local
    # Cria os 7 dias vazios (seg→dom)
    from collections import defaultdict

    days_map: dict[date, list[ProApptItem]] = defaultdict(list)

    for ap in appts:
        start_local_dt = ap.start_at.astimezone(tz)
        end_local_dt = ap.end_at.astimezone(tz)
        item = ProApptItem(
            id=ap.id,
            family_id=ap.family_id,
            family_name=getattr(getattr(ap, "family", None), "full_name", None),
            service=ap.service,
            status=ap.status,
            location=ap.location,
            start_at_utc=ap.start_at,
            end_at_utc=ap.end_at,
            start_at_local=start_local_dt,
            end_at_local=end_local_dt,
        )
        days_map[start_local_dt.date()].append(item)

    # Ordenar por horário em cada dia
    for items in days_map.values():
        items.sort(key=lambda i: i.start_at_local)

    # Construir lista ordenada de dias seg→dom
    days = []
    cur = start_local
    for _ in range(7):
        d = cur.date()
        items = days_map.get(d, [])
        days.append(ProDaySchedule(date_local=d, items=items))
        cur = cur.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)

    # Summary
    # count_by_status na janela
    counts = (
        db.query(Appointment.status, func.count(Appointment.id))
        .filter(
            and_(
                Appointment.professional_id == current_user.id,
                Appointment.start_at >= start_utc,
                Appointment.start_at < end_utc,
            )
        )
        .group_by(Appointment.status)
        .all()
    )
    count_by_status = {s: int(c) for (s, c) in counts}

    summary = ProWeekSummary(
        week_start_local=start_local.date(),
        week_end_local=end_local.date(),
        count_by_status=count_by_status,
        total_week=sum(count_by_status.values()),
    )

    return ProWeekResponse(summary=summary, days=days)
