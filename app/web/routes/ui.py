from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import and_, func, not_, or_
from sqlalchemy.orm import Session
from starlette.datastructures import URL

from app.db import get_db
from app.deps import require_roles
from app.models.appointment import Appointment, AppointmentStatus
from app.models.user import Role, User
from app.schemas.dashboard_family import StudentApptItem, StudentApptSummary
from app.utils.week import DEFAULT_TZ, week_bounds_local

router = APIRouter(prefix="/ui", tags=["ui"])

templates = Jinja2Templates(directory="app/web/templates")
templates.env.globals.update(now=lambda: datetime.now(ZoneInfo("America/Sao_Paulo")))
templates.env.globals.update(Role=Role)
templates.env.add_extension("jinja2.ext.do")
templates.env.auto_reload = True
templates.env.cache = {}


# -------- helpers


def _make_url_factory(request: Request, page_param: str = "page"):
    def make_url(p: int) -> str:
        qp = dict(request.query_params)
        qp[page_param] = str(p)
        return str(URL(str(request.url)).replace_query_params(**qp))

    return make_url


# -------- login (mínimo)
@router.get("/login")
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


# -------- Família: Meus agendamentos
@router.get("/family/appointments")
def ui_family_appointments(
    request: Request,
    current_user: Annotated[User, Depends(require_roles(Role.FAMILY))],
    db: Annotated[Session, Depends(get_db)],
    range: str = Query(default="upcoming", pattern="^(upcoming|past|all)$"),
    status: str | None = Query(default=None),
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    q: str | None = None,
    page: int = 1,
    page_size: int = 10,
    tz_local: str = "America/Sao_Paulo",
):
    from zoneinfo import ZoneInfo

    try:
        tz = ZoneInfo(tz_local)
    except Exception:
        tz = DEFAULT_TZ

    now_utc = datetime.now(tz).astimezone(ZoneInfo("UTC"))

    conds = [Appointment.student_id == current_user.id]
    if range == "upcoming":
        conds.append(Appointment.starts_at >= now_utc)
    elif range == "past":
        conds.append(Appointment.starts_at < now_utc)

    if status:
        try:
            st = AppointmentStatus(status)
            conds.append(Appointment.status == st)
        except Exception:
            pass

    if date_from:
        conds.append(Appointment.starts_at >= date_from)
    if date_to:
        conds.append(Appointment.starts_at < date_to)

    if q:
        like = f"%{q}%"
        conds.append(
            or_(Appointment.service.ilike(like), Appointment.location.ilike(like))
        )

    qbase = (
        db.query(Appointment).filter(and_(*conds)).order_by(Appointment.starts_at.asc())
    )
    total_items = qbase.count()
    page = max(1, page)
    page_size = max(1, min(100, page_size))
    items = qbase.offset((page - 1) * page_size).limit(page_size).all()

    # Summary (simplificado)
    rows = (
        db.query(Appointment.status, func.count(Appointment.id))
        .filter(Appointment.student_id == current_user.id)
        .group_by(Appointment.status)
        .all()
    )
    count_by_status = {
        s.value if isinstance(s, AppointmentStatus) else str(s): int(c)
        for (s, c) in rows
    }

    next_appt = (
        db.query(Appointment)
        .filter(
            Appointment.student_id == current_user.id,
            Appointment.starts_at >= now_utc,
            Appointment.status != AppointmentStatus.CANCELLED,
        )
        .order_by(Appointment.starts_at.asc())
        .first()
    )

    def _to_item(ap: Appointment) -> StudentApptItem:
        prof_name = None
        try:
            prof_name = getattr(ap.professional, "name", None) or getattr(
                ap.professional, "email", None
            )
        except Exception:
            pass
        return StudentApptItem(
            id=ap.id,
            service=ap.service,
            status=ap.status,
            start_at_utc=ap.starts_at,
            end_at_utc=ap.end_at,
            start_at_local=ap.starts_at.astimezone(tz),
            end_at_local=ap.end_at.astimezone(tz),
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
        next_appointment_start_utc=next_appt.starts_at if next_appt else None,
        next_appointment_service=next_appt.service if next_appt else None,
    )

    total_pages = max(1, (total_items + page_size - 1) // page_size)
    trail = [("/", "Início"), ("/ui/family/appointments", "Meus agendamentos")]

    return templates.TemplateResponse(
        "family_my_schedules.html",
        {
            "request": request,
            "current_user": current_user,
            "items": [_to_item(ap) for ap in items],
            "summary": summary,
            "page": page,
            "page_size": page_size,
            "total_items": total_items,
            "total_pages": total_pages,
            "make_url": _make_url_factory(request),
            "trail": trail,
        },
    )


# -------- Profissional: semana
@router.get("/professional/week")
def ui_professional_week(
    request: Request,
    current_user: Annotated[User, Depends(require_roles(Role.PROFESSIONAL))],
    db: Annotated[Session, Depends(get_db)],
    week_start: date | None = None,
    tz_local: str = "America/Sao_Paulo",
    statuses: list[AppointmentStatus] | None = Query(default=None),
):
    from zoneinfo import ZoneInfo

    try:
        tz = ZoneInfo(tz_local)
    except Exception:
        tz = DEFAULT_TZ

    today_local = datetime.now(tz).date()
    anchor = week_start or today_local
    start_local, end_local = week_bounds_local(anchor, tz)
    start_utc = start_local.astimezone(ZoneInfo("UTC"))
    end_utc = end_local.astimezone(ZoneInfo("UTC"))

    conds = [
        Appointment.professional_id == current_user.id,
        Appointment.starts_at >= start_utc,
        Appointment.starts_at < end_utc,
    ]
    if statuses:
        conds.append(Appointment.status.in_(statuses))
    else:
        conds.append(not_(Appointment.status == AppointmentStatus.CANCELLED))

    appts = (
        db.query(Appointment)
        .filter(and_(*conds))
        .order_by(Appointment.starts_at.asc())
        .all()
    )

    # Bucket por dia
    from collections import defaultdict

    days_map: dict[date, list] = defaultdict(list)
    for ap in appts:
        sl = ap.starts_at.astimezone(tz)
        el = ap.end_at.astimezone(tz)
        days_map[sl.date()].append(
            {
                "id": ap.id,
                "service": ap.service,
                "status": ap.status,
                "location": ap.location,
                "student_name": getattr(getattr(ap, "student", None), "name", None)
                or getattr(getattr(ap, "student", None), "email", None),
                "student_id": ap.student_id,
                "start_at_local": sl,
                "end_at_local": el,
            }
        )
    for items in days_map.values():
        items.sort(key=lambda i: i["start_at_local"])

    days = []
    cur = start_local
    for _ in range(7):
        d = cur.date()
        days.append({"date_local": d, "items": days_map.get(d, [])})
        cur += timedelta(days=1)

    # Summary
    counts = (
        db.query(Appointment.status, func.count(Appointment.id))
        .filter(
            and_(
                Appointment.professional_id == current_user.id,
                Appointment.starts_at >= start_utc,
                Appointment.starts_at < end_utc,
            )
        )
        .group_by(Appointment.status)
        .all()
    )
    count_by_status = {s: int(c) for (s, c) in counts}
    summary = {
        "week_start_local": start_local.date(),
        "week_end_local": end_local.date(),
        "count_by_status": count_by_status,
        "total_week": sum(count_by_status.values()),
    }

    trail = [("/", "Início"), ("/ui/professional/week", "Minha semana")]
    return templates.TemplateResponse(
        "professional_week.html",
        {
            "request": request,
            "current_user": current_user,
            "days": days,
            "summary": summary,
            "trail": trail,
        },
    )


# -------- Coordenação: overview
@router.get("/coordination/overview")
def ui_coordination_overview(
    request: Request,
    current_user: Annotated[User, Depends(require_roles(Role.COORDINATION))],
    db: Annotated[Session, Depends(get_db)],
    week_start: date | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    tz_local: str = "America/Sao_Paulo",
    limit_lists: int = Query(default=10, ge=1, le=50),
):
    from zoneinfo import ZoneInfo

    try:
        tz = ZoneInfo(tz_local)
    except Exception:
        tz = DEFAULT_TZ
        tz_local = "America/Sao_Paulo"

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

    start_utc = start_local.astimezone(ZoneInfo("UTC"))
    end_utc = end_local.astimezone(ZoneInfo("UTC"))

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

    professionals_active = (
        db.query(func.count(func.distinct(Appointment.professional_id)))
        .filter(
            and_(Appointment.starts_at >= start_utc, Appointment.starts_at < end_utc)
        )
        .scalar()
        or 0
    )
    students_active = (
        db.query(func.count(func.distinct(Appointment.student_id)))
        .filter(
            and_(Appointment.starts_at >= start_utc, Appointment.starts_at < end_utc)
        )
        .scalar()
        or 0
    )

    # Série diária
    series_map = {}
    cur = start_local
    while cur < end_local:
        series_map[cur.date()] = {s: 0 for s in AppointmentStatus}
        cur += timedelta(days=1)
    for s, dt in db.query(Appointment.status, Appointment.starts_at).filter(
        and_(Appointment.starts_at >= start_utc, Appointment.starts_at < end_utc)
    ):
        d_local = dt.astimezone(tz).date()
        if d_local in series_map:
            series_map[d_local][s] = series_map[d_local].get(s, 0) + 1
    series_daily = [
        {
            "date_local": d,
            "count_total": sum(counts.values()),
            "count_by_status": counts,
        }
        for d, counts in sorted(series_map.items())
    ]

    # Tops
    prof_rows = (
        db.query(Appointment.professional_id, func.count(Appointment.id))
        .filter(
            and_(Appointment.starts_at >= start_utc, Appointment.starts_at < end_utc)
        )
        .group_by(Appointment.professional_id)
        .order_by(func.count(Appointment.id).desc())
        .limit(limit_lists)
        .all()
    )
    prof_ids = [pid for (pid, _c) in prof_rows]
    name_map = (
        {
            u.id: (getattr(u, "name", None) or getattr(u, "email", None))
            for u in db.query(User).filter(User.id.in_(prof_ids)).all()
        }
        if prof_ids
        else {}
    )
    top_professionals = [
        {
            "professional_id": int(pid),
            "professional_name": name_map.get(pid),
            "count": int(c),
        }
        for (pid, c) in prof_rows
    ]

    svc_rows = (
        db.query(Appointment.service, func.count(Appointment.id))
        .filter(
            and_(Appointment.starts_at >= start_utc, Appointment.starts_at < end_utc)
        )
        .group_by(Appointment.service)
        .order_by(func.count(Appointment.id).desc())
        .limit(limit_lists)
        .all()
    )
    top_services = [
        {"service": s or "(sem descrição)", "count": int(c)} for (s, c) in svc_rows
    ]

    recent_rows = (
        db.query(Appointment)
        .filter(
            and_(Appointment.starts_at >= start_utc, Appointment.starts_at < end_utc)
        )
        .order_by(getattr(Appointment, "created_at", Appointment.starts_at).desc())
        .limit(limit_lists)
        .all()
    )
    stud_map = {}
    stud_ids = list({r.student_id for r in recent_rows})
    if stud_ids:
        for u in db.query(User).filter(User.id.in_(stud_ids)).all():
            stud_map[u.id] = getattr(u, "name", None) or getattr(u, "email", None)
    pro_map = {}
    pro_ids = list({r.professional_id for r in recent_rows})
    if pro_ids:
        for u in db.query(User).filter(User.id.in_(pro_ids)).all():
            pro_map[u.id] = getattr(u, "name", None) or getattr(u, "email", None)
    recent = [
        {
            "id": r.id,
            "service": r.service,
            "status": r.status,
            "start_at_utc": r.start_at,
            "start_at_local": r.start_at.astimezone(tz),
            "professional_id": r.professional_id,
            "professional_name": pro_map.get(r.professional_id),
            "student_id": r.student_id,
            "student_name": stud_map.get(r.student_id),
        }
        for r in recent_rows
    ]

    summary = {
        "window_start_local": start_local.date(),
        "window_end_local": end_local.date(),
        "timezone": tz_local,
        "total_appointments": total_appointments,
        "count_by_status": count_by_status,
        "cancel_rate": cancel_rate,
        "professionals_active": int(professionals_active),
        "families_active": int(students_active),
        "today_upcoming": 0,
    }

    trail = [
        ("/", "Início"),
        ("/ui/coordination/overview", "Coordenação — Visão geral"),
    ]

    return templates.TemplateResponse(
        "coordination_overview.html",
        {
            "request": request,
            "current_user": current_user,
            "summary": summary,
            "series_daily": series_daily,
            "top_professionals": top_professionals,
            "top_services": top_services,
            "recent": recent,
            "trail": trail,
        },
    )
