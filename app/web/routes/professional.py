from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from urllib.parse import urlencode
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, case

from app.core.settings import settings
from app.db.session import get_db
from app.deps import require_roles
from app.models.user import Role, User
from app.models.appointment import Appointment, AppointmentStatus
from app.models.professional import Professional
from app.web.templating import render

router = APIRouter()

# --------------------------
# Helpers (datas & formatação)
# --------------------------
PT_WEEKDAYS_SHORT = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]


def fmt_dmy(dt: date) -> str:
    return dt.strftime("%d/%m/%Y")


def fmt_hm(t: time) -> str:
    return f"{t.hour:02d}:{t.minute:02d}"


def start_of_week(d: date) -> date:
    """Segunda-feira da semana do dia d."""
    return d - timedelta(days=(d.weekday()))  # weekday(): Mon=0 .. Sun=6


def timeslots(start_h=8, end_h=18) -> list[str]:
    """Slots de hora cheia (08:00 .. 17:00)"""
    return [f"{h:02d}:00" for h in range(start_h, end_h)]


def build_nav_urls_range(
    base_path: str,
    *,
    date_from: date,
    date_to: date | None,
    persist: dict | None = None,
) -> dict[str, str]:
    persist = {k: v for (k, v) in (persist or {}).items() if v not in (None, "")}

    def _url(df: date, dt: date | None) -> str:
        params = {**persist}
        params["date_from"] = df.isoformat()
        if dt:
            params["date_to"] = dt.isoformat()
        return f"{base_path}?{urlencode(params)}"

    step = 7
    prev_df = date_from - timedelta(days=step)
    prev_dt = (date_to - timedelta(days=step)) if date_to else None
    next_df = date_from + timedelta(days=step)
    next_dt = (date_to + timedelta(days=step)) if date_to else None

    # today
    t = date.today()
    ws = start_of_week(t)
    today_df, today_dt = ws, ws + timedelta(days=6)

    return {
        "prev_url": _url(prev_df, prev_dt),
        "next_url": _url(next_df, next_dt),
        "today_url": _url(today_df, today_dt),
    }


# --------------------------
# Demo data
# --------------------------
def demo_sessions_for_week(week_start: date) -> list[dict[str, Any]]:
    """Gera 3 sessões fake espalhadas na semana (determinístico)."""
    sessions = []
    # Segunda 09:00
    d0 = week_start
    sessions.append(
        {
            "date": d0,
            "starts_at": datetime.combine(d0, time(9, 0)),
            "ends_at": datetime.combine(d0, time(9, 45)),
            "client_name": "João",
            "service_name": "Fonoaudiologia",
            "status": "scheduled",
        }
    )
    # Quarta 14:00
    d2 = week_start + timedelta(days=2)
    sessions.append(
        {
            "date": d2,
            "starts_at": datetime.combine(d2, time(14, 0)),
            "ends_at": datetime.combine(d2, time(14, 45)),
            "client_name": "Maria",
            "service_name": "Psicopedagogia",
            "status": "confirmed",
        }
    )
    # Sexta 10:00
    d4 = week_start + timedelta(days=4)
    sessions.append(
        {
            "date": d4,
            "starts_at": datetime.combine(d4, time(10, 0)),
            "ends_at": datetime.combine(d4, time(10, 45)),
            "client_name": "Pedro",
            "service_name": "Terapia Ocupacional",
            "status": "scheduled",
        }
    )
    return sessions


def to_local_labels(st: datetime, en: datetime | None) -> dict[str, str]:
    """Formata horários em strings 'dd/mm/yyyy hh:mm' (ajuste fuso se necessário)."""
    starts_at_local = st.strftime("%d/%m/%Y %H:%M")
    ends_at_local = en.strftime("%d/%m/%Y %H:%M") if en else None
    return {"starts_at_local": starts_at_local, "ends_at_local": ends_at_local}


# --------------------------
# Render: DASHBOARD
# --------------------------
def _render_professional_dashboard(
    request: Request,
    current_user: User | None,
    db: Session | None,
    demo: bool,
) -> HTMLResponse:
    today = date.today()
    week_start = start_of_week(today)

    next_session = None
    kpis = {"today": 0, "week": 0, "attended_30d": 0, "no_show_30d": 0}
    today_sessions: list[dict[str, Any]] = []

    if demo:
        sessions = demo_sessions_for_week(week_start)
        # KPI semana
        kpis["week"] = len(sessions)
        # Sessões de hoje
        for s in sessions:
            if s["date"] == today:
                kpis["today"] += 1
                today_sessions.append(
                    {
                        "id": f"demo-{s['starts_at'].isoformat()}",
                        "client_name": s["client_name"],
                        "service_name": s["service_name"],
                        **to_local_labels(s["starts_at"], s["ends_at"]),
                        "status": s["status"],
                        "start_url": "/start/DEMO",
                        "cancel_url": "/cancel/DEMO",
                    }
                )
        # Proxima sessão (menor datetime >= agora na semana)
        now = datetime.now()
        upcoming = sorted(
            [s for s in sessions if s["starts_at"] >= now], key=lambda x: x["starts_at"]
        )
        if not upcoming:
            upcoming = sorted(sessions, key=lambda x: x["starts_at"])
        s = upcoming[0]
        next_session = {
            "id": "next-demo",
            "client_name": s["client_name"],
            "service_name": s["service_name"],
            "starts_at_human": "Em breve"
            if s["date"] == today
            else PT_WEEKDAYS_SHORT[s["date"].weekday()],
            **to_local_labels(s["starts_at"], s["ends_at"]),
            "location": "Sala 2",
            "status": s["status"],
            "start_url": "/start/DEMO",
            "cancel_url": "/cancel/DEMO",
        }
        # KPIs simples últimos 30 dias (fake)
        kpis["attended_30d"] = 12
        kpis["no_show_30d"] = 2
    else:
        # Dados reais: sessões do profissional vinculado ao usuário
        from zoneinfo import ZoneInfo

        tz = ZoneInfo("America/Sao_Paulo")
        now = datetime.now(UTC)
        prof = (
            db.query(Professional)
            .filter(Professional.user_id == current_user.id)
            .one_or_none()
        )
        prof_id = prof.id if prof else None
        if prof_id is not None:
            # Próxima sessão
            ap = (
                db.query(Appointment)
                .filter(
                    Appointment.professional_id == prof_id,
                    Appointment.starts_at >= now,
                    Appointment.status == AppointmentStatus.SCHEDULED,
                )
                .order_by(Appointment.starts_at.asc())
                .first()
            )
            if ap:
                next_session = {
                    "id": ap.id,
                    "client_name": "Aluno",
                    "service_name": ap.service,
                    "starts_at_human": ap.starts_at.astimezone(tz).strftime(
                        "%d/%m %H:%M"
                    ),
                    **to_local_labels(ap.starts_at, ap.ends_at),
                    "location": ap.location,
                    "status": (
                        "confirmed"
                        if ap.status == AppointmentStatus.CONFIRMED
                        else (
                            "canceled"
                            if ap.status == AppointmentStatus.CANCELLED
                            else ("past" if ap.status == AppointmentStatus.DONE else "scheduled")
                        )
                    ),
                    "start_url": None,
                    "cancel_url": None,
                }

            # Hoje
            start_today = (
                datetime.combine(today, time.min, tzinfo=tz).astimezone(UTC)
            )
            end_today = (
                datetime.combine(today, time.max, tzinfo=tz).astimezone(UTC)
            )
            todays = (
                db.query(Appointment)
                .filter(
                    Appointment.professional_id == prof_id,
                    Appointment.starts_at >= start_today,
                    Appointment.starts_at <= end_today,
                )
                .order_by(Appointment.starts_at.asc())
                .all()
            )
            for ap in todays:
                today_sessions.append(
                    {
                        "id": ap.id,
                        "client_name": "Aluno",
                        "service_name": ap.service,
                        **to_local_labels(ap.starts_at, ap.ends_at),
                        "status": (
                            "confirmed"
                            if ap.status == AppointmentStatus.CONFIRMED
                            else (
                                "canceled"
                                if ap.status == AppointmentStatus.CANCELLED
                                else ("past" if ap.status == AppointmentStatus.DONE else "scheduled")
                            )
                        ),
                        "start_url": None,
                        "cancel_url": None,
                    }
                )
            kpis["today"] = len(todays)

            # Semana
            ws = start_of_week(today)
            we = ws + timedelta(days=6)
            start_week = (
                datetime.combine(ws, time.min, tzinfo=tz).astimezone(UTC)
            )
            end_week = (
                datetime.combine(we, time.max, tzinfo=tz).astimezone(UTC)
            )
            kpis["week"] = (
                db.query(Appointment)
                .filter(
                    Appointment.professional_id == prof_id,
                    Appointment.starts_at >= start_week,
                    Appointment.starts_at <= end_week,
                )
                .count()
            )

            # Últimos 30 dias — DONE como compareceu, no_show não mapeado (0)
            start_30d_ago = now - timedelta(days=30)
            kpis["attended_30d"] = (
                db.query(Appointment)
                .filter(
                    Appointment.professional_id == prof_id,
                    Appointment.starts_at >= start_30d_ago,
                    Appointment.status == AppointmentStatus.DONE,
                )
                .count()
            )
            kpis["no_show_30d"] = 0

    ctx = {
        "request": request,
        "current_user": current_user,
        "app_version": getattr(settings, "APP_VERSION", "dev"),
        "next_session": next_session,
        "kpis": kpis,
        "today_sessions": today_sessions,
    }
    return render(request, "pages/professional/dashboard.html", ctx)


@router.get("/professional/dashboard", response_class=HTMLResponse)
def ui_professional_dashboard(
    request: Request,
    current_user: User = Depends(require_roles(Role.PROFESSIONAL)),
    db: Session = Depends(get_db),
    demo: bool = Query(False),
):
    return _render_professional_dashboard(request, current_user, db, demo)


# Preview dev (sem auth)
@router.get("/__dev/professional/dashboard", response_class=HTMLResponse)
def preview_professional_dashboard(request: Request, demo: bool = Query(True)):
    return _render_professional_dashboard(request, None, None, demo)


# --------------------------
# Render: SCHEDULE (day/week)
# --------------------------
def _week_payload(base_date: date, demo: bool) -> dict[str, Any]:
    week_start = start_of_week(base_date)
    days = [
        {"label": f"{PT_WEEKDAYS_SHORT[i]} # {fmt_dmy(week_start + timedelta(days=i))}"}
        for i in range(7)
    ]
    rows = []
    if not demo:
        # vazio
        for ts in timeslots():
            rows.append(
                {
                    "label": ts,
                    "cells": [{"state": "is-free", "items": []} for _ in range(7)],
                }
            )
        return {"days": days, "rows": rows}

    sessions = demo_sessions_for_week(week_start)
    sessions_map: dict[tuple, list[dict[str, Any]]] = {}
    for s in sessions:
        key = (s["date"], fmt_hm(s["starts_at"].time()))
        sessions_map.setdefault(key, []).append(s)

    for ts in timeslots():
        cells = []
        for i in range(7):
            d = week_start + timedelta(days=i)
            items = []
            state = "is-free"
            key = (d, ts)
            if key in sessions_map:
                for s in sessions_map[key]:
                    items.append(
                        {
                            "client_name": s["client_name"],
                            "service_name": s["service_name"],
                            "starts_at_local": f"{fmt_hm(s['starts_at'].time())}",
                            "ends_at_local": f"{fmt_hm(s['ends_at'].time())}",
                        }
                    )
                state = "is-busy"
            cells.append({"state": state, "items": items})
        rows.append({"label": ts, "cells": cells})

    return {"days": days, "rows": rows}


def _day_payload(base_date: date, demo: bool) -> list[dict[str, Any]]:
    rows = []
    if not demo:
        for ts in timeslots():
            rows.append({"label": ts, "slot": {"state": "is-free", "items": []}})
        return rows

    # Marca 09:00 e 14:00 como ocupados no dia-base (se coincidirem com o demo)
    demo_map = {
        "09:00": {"client_name": "João", "service_name": "Fonoaudiologia"},
        "14:00": {"client_name": "Maria", "service_name": "Psicopedagogia"},
    }
    for ts in timeslots():
        if ts in demo_map:
            item = demo_map[ts]
            rows.append(
                {
                    "label": ts,
                    "slot": {
                        "state": "is-busy",
                        "items": [
                            {
                                "client_name": item["client_name"],
                                "service_name": item["service_name"],
                                "starts_at_local": ts,
                                "ends_at_local": (
                                    datetime.strptime(ts, "%H:%M")
                                    + timedelta(minutes=45)
                                ).strftime("%H:%M"),
                            }
                        ],
                    },
                }
            )
        else:
            rows.append({"label": ts, "slot": {"state": "is-free", "items": []}})
    return rows


def _render_professional_schedule(
    request: Request,
    current_user: User | None,
    db: Session | None,
    filters: dict[str, Any],
    demo: bool,
) -> HTMLResponse:
    # filtros
    view = "week"
    # parse date range
    df_str = (filters.get("date_from") or "").strip()
    dt_str = (filters.get("date_to") or "").strip()
    def _parse_date(s: str | None, fallback: date) -> date:
        try:
            return date.fromisoformat(s) if s else fallback
        except Exception:
            return fallback
    today_d = date.today()
    if df_str and dt_str:
        range_from = _parse_date(df_str, today_d)
        range_to = _parse_date(dt_str, range_from + timedelta(days=6))
    else:
        ws = start_of_week(today_d)
        range_from, range_to = ws, ws + timedelta(days=6)

    # Services list (fallback static; replaced with DB values below if available)
    services = [
        {"id": "fono", "name": "Fonoaudiologia"},
        {"id": "psico", "name": "Psicopedagogia"},
        {"id": "neuro", "name": "Neuropsicologia"},
    ]

    nav = build_nav_urls_range(
        "/professional/schedule",
        date_from=range_from,
        date_to=range_to,
        persist=filters,
    )

    context = {
        "request": request,
        "current_user": current_user,
        "app_version": getattr(settings, "APP_VERSION", "dev"),
        "filters": {
            "date_from": range_from.isoformat(),
            "date_to": (range_to.isoformat() if range_to else ""),
            "view": view,
            "service_id": filters.get("service_id", ""),
        },
        "services": services,
        "nav": nav,
        "day_rows": None,
        "week": None,
    }

    # Real data when possible (fallback to demo renderer)
    if not demo and db and current_user:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("America/Sao_Paulo")

        # resolve professional id
        prof = (
            db.query(Professional)
            .filter(Professional.user_id == current_user.id)
            .one_or_none()
        )
        prof_id = prof.id if prof else None

        if prof_id is None:
            # keep empty grids
            pass
        else:
            # replace services with distinct values from DB for this professional
            try:
                db_services = (
                    db.query(Appointment.service)
                    .filter(Appointment.professional_id == prof_id)
                    .distinct()
                    .order_by(Appointment.service.asc())
                    .all()
                )
                services = [
                    {"id": s or "", "name": s or "(sem descrição)"} for (s,) in db_services
                ]
            except Exception:
                services = []
            # window
            ws = range_from
            start_local = datetime.combine(ws, time.min, tzinfo=tz)
            if range_to:
                end_local = datetime.combine(range_to, time.max, tzinfo=tz)
            else:
                end_local = start_local + timedelta(days=7) - timedelta(microseconds=1)

            start_utc = start_local.astimezone(UTC)
            end_utc = end_local.astimezone(UTC)

            q = (
                db.query(Appointment)
                .filter(
                    Appointment.professional_id == prof_id,
                    Appointment.starts_at >= start_utc,
                    Appointment.starts_at <= end_utc,
                )
                .order_by(Appointment.starts_at.asc())
            )
            svc = (filters.get("service_id") or "").strip()
            if svc:
                q = q.filter(Appointment.service == svc)

            appts = q.all()

            def _label_hm(dt: datetime) -> str:
                return dt.astimezone(tz).strftime("%H:%M")

            # week grid
            week = {"days": [], "rows": []}
            ws = range_from
            week["days"] = [
                {"label": f"{PT_WEEKDAYS_SHORT[i]} # {fmt_dmy(ws + timedelta(days=i))}"}
                for i in range(7)
            ]
            # map appointments by (day_index, hour)
            ap_map: dict[tuple[int, int], list[Appointment]] = {}
            for ap in appts:
                lt = ap.starts_at.astimezone(tz)
                day_idx = (lt.date() - ws).days
                if 0 <= day_idx <= 6:
                    ap_map.setdefault((day_idx, lt.hour), []).append(ap)
            for h in range(8, 18):
                cells = []
                for day_idx in range(7):
                    items = []
                    for ap in ap_map.get((day_idx, h), []):
                        items.append(
                            {
                                "client_name": "Aluno",
                                "service_name": ap.service,
                                "starts_at_local": _label_hm(ap.starts_at),
                                "ends_at_local": _label_hm(ap.ends_at),
                            }
                        )
                    state = "is-busy" if items else "is-free"
                    cells.append({"state": state, "items": items})
                week["rows"].append({"label": f"{h:02d}:00", "cells": cells})
            context["week"] = week

    # Fallback demo rendering if no real data was constructed
    if context["week"] is None:
        # build demo week using range_from
        context["week"] = _week_payload(range_from, demo)

    return render(request, "pages/professional/schedule.html", context)


@router.get("/professional/schedule", response_class=HTMLResponse)
def ui_professional_schedule(
    request: Request,
    current_user: User = Depends(require_roles(Role.PROFESSIONAL)),
    db: Session = Depends(get_db),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    service_id: str | None = Query(None),
    demo: bool = Query(False),
):
    filters = {"date_from": date_from, "date_to": date_to, "service_id": service_id}
    return _render_professional_schedule(request, current_user, db, filters, demo)


# Preview dev (sem auth)
@router.get("/__dev/professional/schedule", response_class=HTMLResponse)
def preview_professional_schedule(
    request: Request,
    date_str: str | None = Query(None, alias="date"),
    service_id: str | None = Query(None),
    demo: bool = Query(True),
):
    filters = {"date": date_str, "service_id": service_id}
    return _render_professional_schedule(request, None, None, filters, demo)


# --------------------------
# Render: REPORTS (profissional)
# --------------------------
def _render_professional_reports(
    request: Request,
    current_user: User,
    db: Session,
    *,
    date_from: str | None,
    date_to: str | None,
    group_by: str,
):
    from zoneinfo import ZoneInfo
    tz = ZoneInfo("America/Sao_Paulo")

    # Resolve professional linked to current user
    prof = (
        db.query(Professional)
        .filter(Professional.user_id == current_user.id)
        .one_or_none()
    )
    prof_id = prof.id if prof else None

    # Dates (defaults = current month)
    today = date.today()
    if not date_from:
        df = today.replace(day=1)
    else:
        try:
            df = date.fromisoformat(date_from)
        except Exception:
            df = today.replace(day=1)
    if not date_to:
        dt = today
    else:
        try:
            dt = date.fromisoformat(date_to)
        except Exception:
            dt = today

    start_dt = datetime.combine(df, time.min, tzinfo=tz).astimezone(UTC)
    end_dt = datetime.combine(dt, time.max, tzinfo=tz).astimezone(UTC)

    rows: list[dict] = []
    kpis = {"total": 0, "confirmed": 0, "canceled": 0, "attended": 0}

    if prof_id is not None:
        base = db.query(Appointment).filter(
            Appointment.professional_id == prof_id,
            Appointment.starts_at >= start_dt,
            Appointment.starts_at <= end_dt,
        )

        # KPIs
        kpis["total"] = base.count()
        kpis["confirmed"] = base.filter(
            Appointment.status == AppointmentStatus.CONFIRMED
        ).count()
        kpis["canceled"] = base.filter(
            Appointment.status == AppointmentStatus.CANCELLED
        ).count()
        kpis["attended"] = base.filter(
            Appointment.status == AppointmentStatus.DONE
        ).count()

        # Grouping
        if group_by == "day":
            dtexpr = func.date_trunc("day", Appointment.starts_at)
            rows_raw = (
                db.query(
                    dtexpr.label("label"),
                    func.sum(
                        case((Appointment.status == AppointmentStatus.SCHEDULED, 1), else_=0)
                    ).label("scheduled"),
                    func.sum(
                        case((Appointment.status == AppointmentStatus.CONFIRMED, 1), else_=0)
                    ).label("confirmed"),
                    func.sum(
                        case((Appointment.status == AppointmentStatus.DONE, 1), else_=0)
                    ).label("attended"),
                    func.sum(
                        case((Appointment.status == AppointmentStatus.CANCELLED, 1), else_=0)
                    ).label("canceled"),
                )
                .filter(
                    Appointment.professional_id == prof_id,
                    Appointment.starts_at >= start_dt,
                    Appointment.starts_at <= end_dt,
                )
                .group_by(dtexpr)
                .order_by(dtexpr)
                .all()
            )
            rows = [
                {
                    "label": r.label.astimezone(tz).date().strftime("%d/%m/%Y"),
                    "scheduled": int(r.scheduled or 0),
                    "confirmed": int(r.confirmed or 0),
                    "attended": int(r.attended or 0),
                    "canceled": int(r.canceled or 0),
                }
                for r in rows_raw
            ]
        else:  # service
            rows_raw = (
                db.query(
                    Appointment.service.label("label"),
                    func.sum(
                        case((Appointment.status == AppointmentStatus.SCHEDULED, 1), else_=0)
                    ).label("scheduled"),
                    func.sum(
                        case((Appointment.status == AppointmentStatus.CONFIRMED, 1), else_=0)
                    ).label("confirmed"),
                    func.sum(
                        case((Appointment.status == AppointmentStatus.DONE, 1), else_=0)
                    ).label("attended"),
                    func.sum(
                        case((Appointment.status == AppointmentStatus.CANCELLED, 1), else_=0)
                    ).label("canceled"),
                )
                .filter(
                    Appointment.professional_id == prof_id,
                    Appointment.starts_at >= start_dt,
                    Appointment.starts_at <= end_dt,
                )
                .group_by(Appointment.service)
                .order_by(Appointment.service)
                .all()
            )
            rows = [
                {
                    "label": r.label or "(sem descrição)",
                    "scheduled": int(r.scheduled or 0),
                    "confirmed": int(r.confirmed or 0),
                    "attended": int(r.attended or 0),
                    "canceled": int(r.canceled or 0),
                }
                for r in rows_raw
            ]

    ctx = {
        "current_user": current_user,
        "filters": {
            "date_from": df.isoformat(),
            "date_to": dt.isoformat(),
            "group_by": group_by,
        },
        "kpis": kpis,
        "rows": rows,
    }
    return render(request, "pages/professional/reports.html", ctx)


@router.get("/professional/reports", response_class=HTMLResponse)
def ui_professional_reports(
    request: Request,
    current_user: User = Depends(require_roles(Role.PROFESSIONAL)),
    db: Session = Depends(get_db),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    group_by: str = Query("day", pattern="^(day|service)$"),
):
    return _render_professional_reports(
        request,
        current_user,
        db,
        date_from=date_from,
        date_to=date_to,
        group_by=group_by,
    )
