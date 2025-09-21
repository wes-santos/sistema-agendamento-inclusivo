# app/web/routes/coordination.py
from __future__ import annotations

from calendar import monthrange
from collections.abc import Iterable
from datetime import UTC, date, datetime, time, timedelta
from io import StringIO
from typing import Annotated, Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import and_, case, func, or_
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_roles
from app.models.appointment import Appointment, AppointmentStatus
from app.models.professional import Professional
from app.models.student import Student
from app.models.user import Role, User
from app.web.templating import render

router = APIRouter()

# ==========================
# Helpers de datas e formato
# ==========================
PT_WEEKDAYS_SHORT = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]


def parse_iso(d: str | None) -> date | None:
    if not d:
        return None
    try:
        return date.fromisoformat(d)
    except Exception:
        return None


def start_of_week(d: date) -> date:
    return d - timedelta(days=d.weekday())  # seg=0


def end_of_week(d: date) -> date:
    return start_of_week(d) + timedelta(days=6)


def fmt_dmy(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def fmt_hm(t: time) -> str:
    return f"{t.hour:02d}:{t.minute:02d}"


def format_brl(n: float) -> str:
    # R$ 1.234,56
    s = f"{n:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}"


def build_persist_query(request: Request, keep: Iterable[str]) -> str:
    params = []
    for k in keep:
        v = request.query_params.get(k)
        if v not in (None, ""):
            params.append(f"{k}={v}")
    return "&".join(params)


def _render_coordination_dashboard(
    request: Request,
    current_user: User,
    db: Session,
    *,
    q: str | None = None,
    status: str | None = None,
) -> HTMLResponse:
    today = date.today()
    tz = ZoneInfo("America/Sao_Paulo")
    now = datetime.now(UTC)

    queue: list[dict[str, Any]] = []
    kpis = {"to_confirm": 0, "today": 0, "week": 0, "canceled_7d": 0}

    in_7d = now + timedelta(days=7)
    query = (
        db.query(Appointment, Student, Professional, User)
        .join(Student, Student.id == Appointment.student_id)
        .join(Professional, Professional.id == Appointment.professional_id)
        .join(User, User.id == Student.guardian_user_id)
        .filter(
            Appointment.status == AppointmentStatus.SCHEDULED,
            Appointment.starts_at >= now,
            Appointment.starts_at < in_7d,
        )
    )

    if status:
        st = status.lower()
        if st == "confirmed":
            query = query.filter(Appointment.status == AppointmentStatus.CONFIRMED)
        elif st == "scheduled":
            query = query.filter(Appointment.status == AppointmentStatus.SCHEDULED)

    if q:
        like = f"%{q.strip()}%"
        query = query.filter(
            or_(
                Appointment.service.ilike(like),
                Professional.name.ilike(like),
                User.name.ilike(like),
            )
        )

    rows = query.order_by(Appointment.starts_at.asc()).all()
    queue = [
        {
            "id": ap.id,
            "family_name": guardian.name if guardian else getattr(st.guardian, "name", "Família"),
            "service_name": ap.service,
            "professional_name": pr.name or getattr(pr.user, "name", None),
            "starts_at_local": ap.starts_at.astimezone(tz).strftime("%d/%m/%Y %H:%M"),
            "status": (
                "confirmed"
                if ap.status == AppointmentStatus.CONFIRMED
                else "scheduled"
            ),
            "confirm_url": None,
            "remind_url": None,
            "cancel_url": None,
        }
        for (ap, st, pr, guardian) in rows
    ]

    kpis["to_confirm"] = (
        db.query(Appointment)
        .filter(Appointment.status == AppointmentStatus.SCHEDULED)
        .count()
    )

    start_today = datetime.combine(today, time.min, tzinfo=tz).astimezone(UTC)
    end_today = datetime.combine(today, time.max, tzinfo=tz).astimezone(UTC)
    kpis["today"] = (
        db.query(Appointment)
        .filter(
            Appointment.starts_at >= start_today,
            Appointment.starts_at <= end_today,
            Appointment.status.in_(
                [
                    AppointmentStatus.SCHEDULED,
                    AppointmentStatus.CONFIRMED,
                    AppointmentStatus.DONE,
                ]
            ),
        )
        .count()
    )

    week_start = start_of_week(today)
    week_end = end_of_week(today)
    start_week = datetime.combine(week_start, time.min, tzinfo=tz).astimezone(UTC)
    end_week = datetime.combine(week_end, time.max, tzinfo=tz).astimezone(UTC)
    kpis["week"] = (
        db.query(Appointment)
        .filter(
            Appointment.starts_at >= start_week,
            Appointment.starts_at <= end_week,
            Appointment.status.in_(
                [
                    AppointmentStatus.SCHEDULED,
                    AppointmentStatus.CONFIRMED,
                    AppointmentStatus.DONE,
                ]
            ),
        )
        .count()
    )

    seven_days_ago = today - timedelta(days=7)
    start_7d = datetime.combine(seven_days_ago, time.min, tzinfo=tz).astimezone(UTC)
    kpis["canceled_7d"] = (
        db.query(Appointment)
        .filter(
            Appointment.starts_at >= start_7d,
            Appointment.status == AppointmentStatus.CANCELLED,
        )
        .count()
    )

    ctx = {
        "current_user": current_user,
        "queue": queue,
        "kpis": kpis,
    }
    return render(request, "pages/coordination/dashboard.html", ctx)

@router.get("/coordination/dashboard", response_class=HTMLResponse)
def ui_coordination_dashboard(
    request: Request,
    current_user: User = Depends(require_roles(Role.COORDINATION)),
    db: Session = Depends(get_db),
    q: str | None = Query(None),
    status: str | None = Query(None),
):
    return _render_coordination_dashboard(request, current_user, db, q=q, status=status)


# ==========================
# Reports (filtros + tabela)
# ==========================
def _render_coordination_reports(
    request: Request,
    current_user: User,
    db: Session,
    filters: dict[str, Any],
) -> HTMLResponse:
    today = date.today()
    default_from = today.replace(day=1)
    quick = (filters.get("range") or "").lower()

    if quick == "today":
        date_from = today
        date_to = today
    elif quick == "week":
        date_from = start_of_week(today)
        date_to = end_of_week(today)
    elif quick == "month":
        date_from = default_from
        last_day = monthrange(today.year, today.month)[1]
        date_to = today.replace(day=last_day)
    else:
        date_from = parse_iso(filters.get("date_from")) or default_from
        date_to = parse_iso(filters.get("date_to")) or today

    group_by = filters.get("group_by") or "day"
    service_id = filters.get("service_id") or None
    professional_id = filters.get("professional_id") or None
    status = filters.get("status") or None

    tz = ZoneInfo("America/Sao_Paulo")

    services = [
        {"id": s or "(sem descrição)", "name": s or "(sem descrição)"}
        for (s,) in db.query(Appointment.service).distinct().order_by(Appointment.service).all()
    ]
    professionals = [
        {"id": p.id, "name": p.name or getattr(p.user, "name", None) or f"Profissional {p.id}"}
        for p in db.query(Professional).order_by(Professional.name).all()
    ]

    start_dt = datetime.combine(date_from, time.min, tzinfo=tz).astimezone(ZoneInfo("UTC"))
    end_dt = datetime.combine(date_to, time.max, tzinfo=tz).astimezone(ZoneInfo("UTC"))

    base = db.query(Appointment).filter(
        Appointment.starts_at >= start_dt,
        Appointment.starts_at <= end_dt,
    )
    if service_id:
        base = base.filter(Appointment.service == service_id)
    if professional_id:
        try:
            pid = int(professional_id)
        except Exception:
            pid = None
        if pid is not None:
            base = base.filter(Appointment.professional_id == pid)
    if status:
        st = status.lower()
        if st == "scheduled":
            base = base.filter(Appointment.status == AppointmentStatus.SCHEDULED)
        elif st == "confirmed":
            base = base.filter(Appointment.status == AppointmentStatus.CONFIRMED)
        elif st.startswith("cancel"):
            base = base.filter(Appointment.status == AppointmentStatus.CANCELLED)
        elif st in ("attended", "done", "past"):
            base = base.filter(Appointment.status == AppointmentStatus.DONE)

    total = base.count()
    confirmed = base.filter(Appointment.status == AppointmentStatus.CONFIRMED).count()
    canceled = base.filter(Appointment.status == AppointmentStatus.CANCELLED).count()
    attended = base.filter(Appointment.status == AppointmentStatus.DONE).count()
    kpis = {
        "total": int(total),
        "confirmed": int(confirmed),
        "canceled": int(canceled),
        "attendance_rate": round((attended / total * 100.0), 1) if total else 0.0,
    }

    rows: list[dict[str, Any]] = []

    if group_by == "day":
        dtexpr = func.date_trunc("day", Appointment.starts_at).label("d")
        day_query = (
            db.query(
                dtexpr,
                func.count().label("n"),
                func.sum(case((Appointment.status == AppointmentStatus.SCHEDULED, 1), else_=0)).label(
                    "scheduled"
                ),
                func.sum(case((Appointment.status == AppointmentStatus.CONFIRMED, 1), else_=0)).label(
                    "confirmed"
                ),
                func.sum(case((Appointment.status == AppointmentStatus.DONE, 1), else_=0)).label(
                    "attended"
                ),
                func.sum(case((Appointment.status == AppointmentStatus.CANCELLED, 1), else_=0)).label(
                    "canceled"
                ),
            )
            .filter(
                Appointment.starts_at >= start_dt,
                Appointment.starts_at <= end_dt,
            )
            .group_by(dtexpr)
            .order_by(dtexpr)
        )
        rows = [
            {
                "label": rec.d.astimezone(tz).date().strftime("%d/%m/%Y"),
                "scheduled": int(rec.scheduled or 0),
                "confirmed": int(rec.confirmed or 0),
                "attended": int(rec.attended or 0),
                "canceled": int(rec.canceled or 0),
                "no_show": 0,
            }
            for rec in day_query
        ]
    elif group_by == "service":
        svc_query = (
            db.query(
                Appointment.service.label("label"),
                func.count().label("n"),
                func.sum(case((Appointment.status == AppointmentStatus.SCHEDULED, 1), else_=0)).label(
                    "scheduled"
                ),
                func.sum(case((Appointment.status == AppointmentStatus.CONFIRMED, 1), else_=0)).label(
                    "confirmed"
                ),
                func.sum(case((Appointment.status == AppointmentStatus.DONE, 1), else_=0)).label(
                    "attended"
                ),
                func.sum(case((Appointment.status == AppointmentStatus.CANCELLED, 1), else_=0)).label(
                    "canceled"
                ),
            )
            .filter(
                Appointment.starts_at >= start_dt,
                Appointment.starts_at <= end_dt,
            )
            .group_by(Appointment.service)
            .order_by(Appointment.service)
        )
        rows = [
            {
                "label": rec.label or "(sem descrição)",
                "scheduled": int(rec.scheduled or 0),
                "confirmed": int(rec.confirmed or 0),
                "attended": int(rec.attended or 0),
                "canceled": int(rec.canceled or 0),
                "no_show": 0,
            }
            for rec in svc_query
        ]
    else:  # professional
        prof_query = (
            db.query(
                Professional.name.label("label"),
                func.count().label("n"),
                func.sum(case((Appointment.status == AppointmentStatus.SCHEDULED, 1), else_=0)).label(
                    "scheduled"
                ),
                func.sum(case((Appointment.status == AppointmentStatus.CONFIRMED, 1), else_=0)).label(
                    "confirmed"
                ),
                func.sum(case((Appointment.status == AppointmentStatus.DONE, 1), else_=0)).label(
                    "attended"
                ),
                func.sum(case((Appointment.status == AppointmentStatus.CANCELLED, 1), else_=0)).label(
                    "canceled"
                ),
            )
            .join(Professional, Professional.id == Appointment.professional_id)
            .filter(
                Appointment.starts_at >= start_dt,
                Appointment.starts_at <= end_dt,
            )
            .group_by(Professional.name)
            .order_by(Professional.name)
        )
        rows = [
            {
                "label": rec.label or "(profissional)",
                "scheduled": int(rec.scheduled or 0),
                "confirmed": int(rec.confirmed or 0),
                "attended": int(rec.attended or 0),
                "canceled": int(rec.canceled or 0),
                "no_show": 0,
            }
            for rec in prof_query
        ]

    persist_query = urlencode(
        {
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "group_by": group_by,
            "service_id": service_id or "",
            "professional_id": professional_id or "",
            "status": status or "",
        }
    )

    ctx = {
        "current_user": current_user,
        "filters": {
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "group_by": group_by,
            "service_id": service_id or "",
            "professional_id": professional_id or "",
            "status": status or "",
        },
        "services": services,
        "professionals": professionals,
        "rows": rows,
        "report_rows": rows,
        "kpis": kpis,
        "persist_query": persist_query,
        "export_url": request.url_for("export_coordination_reports_csv"),
        "pagination": None,
    }
    return render(request, "pages/coordination/reports.html", ctx)

@router.get("/coordination/reports", response_class=HTMLResponse)
def ui_coordination_reports(
    request: Request,
    current_user: User = Depends(require_roles(Role.COORDINATION)),
    db: Session = Depends(get_db),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    group_by: str = Query("day", pattern="^(day|service|professional)$"),
    service_id: str | None = Query(None),
    professional_id: str | None = Query(None),
    status: str | None = Query(None),
):
    filters = {
        "date_from": date_from,
        "date_to": date_to,
        "group_by": group_by,
        "service_id": service_id,
        "professional_id": professional_id,
        "status": status,
        "range": request.query_params.get("range"),
    }
    return _render_coordination_reports(request, current_user, db, filters)


# ==========================
# Export CSV
# ==========================
@router.get("/coordination/reports/export")
def export_coordination_reports_csv(
    request: Request,
    current_user: User = Depends(require_roles(Role.COORDINATION)),
    db: Session = Depends(get_db),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    group_by: str = Query("day", pattern="^(day|service|professional)$"),
    service_id: str | None = Query(None),
    professional_id: str | None = Query(None),
    status: str | None = Query(None),
):
    # Mesmo filtro da tela (real data)
    today = date.today()
    default_from = today.replace(day=1)
    df = parse_iso(date_from) or default_from
    dt = parse_iso(date_to) or today

    tz = ZoneInfo("America/Sao_Paulo")
    start_dt = datetime.combine(df, time.min, tzinfo=tz).astimezone(ZoneInfo("UTC"))
    end_dt = datetime.combine(dt, time.max, tzinfo=tz).astimezone(ZoneInfo("UTC"))

    base = db.query(Appointment).filter(
        Appointment.starts_at >= start_dt, Appointment.starts_at <= end_dt
    )
    if service_id:
        base = base.filter(Appointment.service == service_id)
    if professional_id:
        try:
            pid = int(professional_id)
        except Exception:
            pid = None
        if pid is not None:
            base = base.filter(Appointment.professional_id == pid)
    if status:
        st = status.lower()
        if st == "scheduled":
            base = base.filter(Appointment.status == AppointmentStatus.SCHEDULED)
        elif st == "confirmed":
            base = base.filter(Appointment.status == AppointmentStatus.CONFIRMED)
        elif st.startswith("cancel"):
            base = base.filter(Appointment.status == AppointmentStatus.CANCELLED)
        elif st in ("attended", "done", "past"):
            base = base.filter(Appointment.status == AppointmentStatus.DONE)

    # Agrupar conforme group_by
    buf = StringIO()
    buf.write("label,scheduled,confirmed,attended,canceled,no_show\\n")

    if group_by == "day":
        day_query = (
            db.query(
                func.date_trunc("day", Appointment.starts_at).label("label"),
                func.sum(case((Appointment.status == AppointmentStatus.SCHEDULED, 1), else_=0)).label(
                    "scheduled"
                ),
                func.sum(case((Appointment.status == AppointmentStatus.CONFIRMED, 1), else_=0)).label(
                    "confirmed"
                ),
                func.sum(case((Appointment.status == AppointmentStatus.DONE, 1), else_=0)).label(
                    "attended"
                ),
                func.sum(case((Appointment.status == AppointmentStatus.CANCELLED, 1), else_=0)).label(
                    "canceled"
                ),
            )
            .filter(Appointment.starts_at >= start_dt, Appointment.starts_at <= end_dt)
        )
        
        # Apply filters to the day query
        if service_id:
            day_query = day_query.filter(Appointment.service == service_id)
        if professional_id:
            try:
                pid = int(professional_id)
            except Exception:
                pid = None
            if pid is not None:
                day_query = day_query.filter(Appointment.professional_id == pid)
        if status:
            st = status.lower()
            if st == "scheduled":
                day_query = day_query.filter(Appointment.status == AppointmentStatus.SCHEDULED)
            elif st == "confirmed":
                day_query = day_query.filter(Appointment.status == AppointmentStatus.CONFIRMED)
            elif st.startswith("cancel"):
                day_query = day_query.filter(Appointment.status == AppointmentStatus.CANCELLED)
            elif st in ("attended", "done", "past"):
                day_query = day_query.filter(Appointment.status == AppointmentStatus.DONE)
        
        rows = day_query.group_by(func.date_trunc("day", Appointment.starts_at)).order_by(func.date_trunc("day", Appointment.starts_at)).all()
        for r in rows:
            label = r.label.astimezone(tz).date().isoformat()
            buf.write(
                f"{label},{int(r.scheduled or 0)},{int(r.confirmed or 0)},{int(r.attended or 0)},{int(r.canceled or 0)},0\\n"
            )
    elif group_by == "service":
        service_query = (
            db.query(
                Appointment.service.label("label"),
                func.sum(case((Appointment.status == AppointmentStatus.SCHEDULED, 1), else_=0)).label(
                    "scheduled"
                ),
                func.sum(case((Appointment.status == AppointmentStatus.CONFIRMED, 1), else_=0)).label(
                    "confirmed"
                ),
                func.sum(case((Appointment.status == AppointmentStatus.DONE, 1), else_=0)).label(
                    "attended"
                ),
                func.sum(case((Appointment.status == AppointmentStatus.CANCELLED, 1), else_=0)).label(
                    "canceled"
                ),
            )
            .filter(Appointment.starts_at >= start_dt, Appointment.starts_at <= end_dt)
        )
        
        # Apply filters to the service query
        if professional_id:
            try:
                pid = int(professional_id)
            except Exception:
                pid = None
            if pid is not None:
                service_query = service_query.filter(Appointment.professional_id == pid)
        if status:
            st = status.lower()
            if st == "scheduled":
                service_query = service_query.filter(Appointment.status == AppointmentStatus.SCHEDULED)
            elif st == "confirmed":
                service_query = service_query.filter(Appointment.status == AppointmentStatus.CONFIRMED)
            elif st.startswith("cancel"):
                service_query = service_query.filter(Appointment.status == AppointmentStatus.CANCELLED)
            elif st in ("attended", "done", "past"):
                service_query = service_query.filter(Appointment.status == AppointmentStatus.DONE)
        
        rows = service_query.group_by(Appointment.service).order_by(Appointment.service).all()
        for r in rows:
            label = r.label or "(sem descrição)"
            buf.write(
                f"{label},{int(r.scheduled or 0)},{int(r.confirmed or 0)},{int(r.attended or 0)},{int(r.canceled or 0)},0\\n"
            )
    else:  # professional
        professional_query = (
            db.query(
                Professional.name.label("label"),
                func.sum(case((Appointment.status == AppointmentStatus.SCHEDULED, 1), else_=0)).label(
                    "scheduled"
                ),
                func.sum(case((Appointment.status == AppointmentStatus.CONFIRMED, 1), else_=0)).label(
                    "confirmed"
                ),
                func.sum(case((Appointment.status == AppointmentStatus.DONE, 1), else_=0)).label(
                    "attended"
                ),
                func.sum(case((Appointment.status == AppointmentStatus.CANCELLED, 1), else_=0)).label(
                    "canceled"
                ),
            )
            .join(Professional, Professional.id == Appointment.professional_id)
            .filter(Appointment.starts_at >= start_dt, Appointment.starts_at <= end_dt)
        )
        
        # Apply filters to the professional query
        if service_id:
            professional_query = professional_query.filter(Appointment.service == service_id)
        if status:
            st = status.lower()
            if st == "scheduled":
                professional_query = professional_query.filter(Appointment.status == AppointmentStatus.SCHEDULED)
            elif st == "confirmed":
                professional_query = professional_query.filter(Appointment.status == AppointmentStatus.CONFIRMED)
            elif st.startswith("cancel"):
                professional_query = professional_query.filter(Appointment.status == AppointmentStatus.CANCELLED)
            elif st in ("attended", "done", "past"):
                professional_query = professional_query.filter(Appointment.status == AppointmentStatus.DONE)
        
        rows = professional_query.group_by(Professional.name).order_by(Professional.name).all()
        for r in rows:
            label = r.label or "(Profissional)"
            buf.write(
                f"{label},{int(r.scheduled or 0)},{int(r.confirmed or 0)},{int(r.attended or 0)},{int(r.canceled or 0)},0\\n"
            )

    filename = f'reports_{group_by}_{df.strftime("%Y%m%d")}_{dt.strftime("%Y%m%d")}.csv'
    headers = {
        "Content-Type": "text/csv; charset=utf-8",
        "Content-Disposition": f'attachment; filename="{filename}"',
    }
    return Response(content=buf.getvalue(), headers=headers)


# ---------------------------
# Coordination Overview Route
# ---------------------------

# Helper functions (duplicates from ui.py, but we'll keep them here for now)
def _ensure_tz(tz_local: str):
    try:
        tz = ZoneInfo(tz_local)
    except Exception:
        tz = ZoneInfo("America/Sao_Paulo")
    return tz


def _week_bounds_local(anchor: date, tz) -> tuple[datetime, datetime]:
    # segunda às 00:00 até segunda seguinte 00:00
    start_local_date = anchor - timedelta(days=anchor.weekday())
    start_local = datetime.combine(start_local_date, time.min, tzinfo=tz)
    end_local = start_local + timedelta(days=7)
    return start_local, end_local


def _get_col(model, *names):
    for n in names:
        if hasattr(model, n):
            return getattr(model, n)
    return None


def _status_key(s) -> str:
    # Normaliza o status para STRING UPPER (compatível com template)
    try:
        # Enum: usa .name (SCHEDULED, CONFIRMED, DONE, CANCELLED...)
        return s.name.upper()
    except Exception:
        return str(s or "").strip().upper()


def _status_matches(key: str, needle_list: list[str]) -> bool:
    lk = key.lower()
    return any(n in lk for n in needle_list)


def _build_url(base: str, params: dict) -> str:
    clean = {k: v for k, v in params.items() if v not in (None, "")}
    qs = urlencode(clean, doseq=True)
    return f"{base}?{qs}" if qs else base


def _fmt_local(dtval: datetime | None, tz):
    if not isinstance(dtval, datetime):
        return "-"
    if dtval.tzinfo is None:
        dtval = dtval.replace(tzinfo=UTC)
    return dtval.astimezone(tz).strftime("%d/%m/%Y %H:%M")


def _fmt_period(d: date) -> str:
    # Ex.: 01 set 2025
    meses = [
        "jan",
        "fev",
        "mar",
        "abr",
        "mai",
        "jun",
        "jul",
        "ago",
        "set",
        "out",
        "nov",
        "dez",
    ]
    return f"{d.day:02d} {meses[d.month-1]} {d.year}"


@router.get("/coordination/overview", name="coordination_overview")
def coordination_overview(
    request: Request,
    current_user: Annotated[User, Depends(require_roles(Role.COORDINATION))],
    db: Annotated[Session, Depends(get_db)],
    week_start: date | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    tz_local: str = "America/Sao_Paulo",
    limit_lists: int = Query(default=10, ge=1, le=50),
):
    tz = _ensure_tz(tz_local)

    # Resolve janela local
    if date_from and date_to:
        start_local = datetime.combine(date_from, time.min, tzinfo=tz)
        end_local = datetime.combine(date_to, time.min, tzinfo=tz)
    elif date_from and not date_to:
        start_local = datetime.combine(date_from, time.min, tzinfo=tz)
        end_local = start_local + timedelta(days=7)
    elif week_start:
        start_local, end_local = _week_bounds_local(week_start, tz)
    else:
        today_local = datetime.now(tz).date()
        start_local, end_local = _week_bounds_local(today_local, tz)

    # UTC bounds (colunas fallback)
    START_COL = _get_col(Appointment, "starts_at", "starts_at_utc")
    END_COL = _get_col(Appointment, "ends_at", "ends_at_utc")
    if START_COL is None or END_COL is None:
        raise RuntimeError("Appointment precisa de starts_at/ends_at (ou *_utc)")

    start_utc = (
        start_local.astimezone(ZoneInfo("UTC"))
        if hasattr(datetime, "timezone")
        else start_local
    )
    end_utc = (
        end_local.astimezone(ZoneInfo("UTC"))
        if hasattr(datetime, "timezone")
        else end_local
    )

    # Contagem por status
    rows = (
        db.query(Appointment.status, func.count(Appointment.id))
        .filter(and_(START_COL >= start_utc, START_COL < end_utc))
        .group_by(Appointment.status)
        .all()
    )
    count_by_status = {_status_key(s): int(c) for (s, c) in rows}
    total_appointments = sum(count_by_status.values())
    cancel_rate = (
        (count_by_status.get("CANCELLED", 0) / total_appointments)
        if total_appointments
        else 0.0
    )

    # Profissionais/estudantes ativos
    professionals_active = (
        db.query(func.count(func.distinct(Appointment.professional_id)))
        .filter(and_(START_COL >= start_utc, START_COL < end_utc))
        .scalar()
        or 0
    )
    students_active = (
        db.query(func.count(func.distinct(Appointment.student_id)))
        .filter(and_(START_COL >= start_utc, START_COL < end_utc))
        .scalar()
        or 0
    )

    # Série diária
    series_map: dict[date, dict[str, int]] = {}
    cur = start_local
    while cur < end_local:
        series_map[cur.date()] = {
            "SCHEDULED": 0,
            "CONFIRMED": 0,
            "DONE": 0,
            "CANCELLED": 0,
        }
        cur += timedelta(days=1)

    for s, dt in db.query(Appointment.status, START_COL).filter(
        and_(START_COL >= start_utc, START_COL < end_utc)
    ):
        s_key = _status_key(s)
        d_local = dt.astimezone(tz).date()
        if d_local in series_map:
            series_map[d_local][s_key] = series_map[d_local].get(s_key, 0) + 1

    series_daily = [
        {
            "date_local": d,
            "count_total": sum(counts.values()),
            "count_by_status": counts,
        }
        for d, counts in sorted(series_map.items())
    ]

    # Top profissionais
    prof_rows = (
        db.query(Appointment.professional_id, func.count(Appointment.id))
        .filter(and_(START_COL >= start_utc, START_COL < end_utc))
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

    # Top serviços
    svc_rows = (
        db.query(Appointment.service, func.count(Appointment.id))
        .filter(and_(START_COL >= start_utc, START_COL < end_utc))
        .group_by(Appointment.service)
        .order_by(func.count(Appointment.id).desc())
        .limit(limit_lists)
        .all()
    )
    top_services = [
        {"service": s or "(sem descrição)", "count": int(c)} for (s, c) in svc_rows
    ]

    # Recentes
    recent_rows = (
        db.query(Appointment)
        .filter(and_(START_COL >= start_utc, START_COL < end_utc))
        .order_by(getattr(Appointment, "created_at", START_COL).desc())
        .limit(limit_lists)
        .all()
    )
    stud_ids = list({r.student_id for r in recent_rows})
    pro_ids = list({r.professional_id for r in recent_rows})

    stud_map = (
        {
            u.id: (getattr(u, "name", None) or getattr(u, "email", None))
            for u in db.query(User).filter(User.id.in_(stud_ids)).all()
        }
        if stud_ids
        else {}
    )
    pro_map = (
        {
            u.id: (getattr(u, "name", None) or getattr(u, "email", None))
            for u in db.query(User).filter(User.id.in_(pro_ids)).all()
        }
        if pro_ids
        else {}
    )

    def _fmt_local(dt):
        return dt.astimezone(tz).strftime("%d/%m %H:%M") if dt else "-"

    recent = [
        {
            "id": r.id,
            "service": getattr(r, "service", None),
            "status": _status_key(getattr(r, "status", None)),
            "starts_at": getattr(r, "starts_at", getattr(r, "starts_at_utc", None)),
            "starts_at_str": _fmt_local(
                getattr(r, "starts_at", getattr(r, "starts_at_utc", None))
            ),
            "professional_id": r.professional_id,
            "professional_name": pro_map.get(r.professional_id),
            "student_id": r.student_id,
            "student_name": stud_map.get(r.student_id),
        }
        for r in recent_rows
    ]

    # Navegação semanal (prev/next)
    base_path = str(request.url_for("coordination_overview"))
    prev_week = (start_local.date() - timedelta(days=7)).isoformat()
    next_week = (start_local.date() + timedelta(days=7)).isoformat()

    prev_url = _build_url(
        base_path,
        {"week_start": prev_week, "tz_local": tz_local, "limit_lists": limit_lists},
    )
    next_url = _build_url(
        base_path,
        {"week_start": next_week, "tz_local": tz_local, "limit_lists": limit_lists},
    )
    clear_filters_url = _build_url(
        base_path, {"week_start": start_local.date().isoformat(), "tz_local": tz_local}
    )

    summary = {
        "window_start_local": start_local.date(),
        "window_end_local": (end_local - timedelta(days=1)).date(),  # inclusivo
        "timezone": tz_local,
        "period_start_str": _fmt_period(start_local.date()),
        "period_end_str": _fmt_period((end_local - timedelta(days=1)).date()),
        "total_appointments": total_appointments,
        "count_by_status": count_by_status,
        "cancel_rate": cancel_rate,
        "professionals_active": int(professionals_active),
        "families_active": int(students_active),
    }

    trail = [
        ("/", "Início"),
        ("/coordination/overview", "Coordenação — Visão geral"),
    ]

    def jinja_url_for(name: str, **params) -> str:
        return str(request.url_for(name, **params))

    return render(
        request,
        "pages/coordination_overview.html",
        {
            "current_user": current_user,
            "summary": summary,
            "series_daily": series_daily,
            "top_professionals": top_professionals,
            "top_services": top_services,
            "recent": recent,
            "prev_url": prev_url,
            "next_url": next_url,
            "clear_filters_url": clear_filters_url,
            "trail": trail,
            "url_for": jinja_url_for,
            "csp_nonce": getattr(request.state, "csp_nonce", None),
        },
    )
