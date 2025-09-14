from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

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


def build_nav_urls(base_path: str, base_date: date, view: str) -> dict[str, str]:
    prev = base_date - timedelta(days=1 if view == "day" else 7)
    next_ = base_date + timedelta(days=1 if view == "day" else 7)
    today = date.today()
    return {
        "prev_url": f"{base_path}?date={prev.isoformat()}&view={view}",
        "next_url": f"{base_path}?date={next_.isoformat()}&view={view}",
        "today_url": f"{base_path}?date={today.isoformat()}&view={view}",
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
    view = filters.get("view") or "week"
    try:
        base_date = date.fromisoformat(filters.get("date") or date.today().isoformat())
    except Exception:
        base_date = date.today()

    services = [
        {"id": "fono", "name": "Fonoaudiologia"},
        {"id": "psico", "name": "Psicopedagogia"},
        {"id": "neuro", "name": "Neuropsicologia"},
    ]

    nav = build_nav_urls("/professional/schedule", base_date, view)

    context = {
        "request": request,
        "current_user": current_user,
        "app_version": getattr(settings, "APP_VERSION", "dev"),
        "filters": {
            "date": base_date.isoformat(),
            "view": view,
            "service_id": filters.get("service_id", ""),
        },
        "services": services,
        "nav": nav,
        "day_rows": None,
        "week": None,
    }

    if view == "day":
        context["day_rows"] = _day_payload(base_date, demo)
    else:
        context["week"] = _week_payload(base_date, demo)

    return render(request, "pages/professional/schedule.html", context)


@router.get("/professional/schedule", response_class=HTMLResponse)
def ui_professional_schedule(
    request: Request,
    current_user: User = Depends(require_roles(Role.PROFESSIONAL)),
    db: Session = Depends(get_db),
    date_str: str | None = Query(None, alias="date"),
    view: str = Query("week", pattern="^(day|week)$"),
    service_id: str | None = Query(None),
    demo: bool = Query(False),
):
    filters = {"date": date_str, "view": view, "service_id": service_id}
    return _render_professional_schedule(request, current_user, db, filters, demo)


# Preview dev (sem auth)
@router.get("/__dev/professional/schedule", response_class=HTMLResponse)
def preview_professional_schedule(
    request: Request,
    date_str: str | None = Query(None, alias="date"),
    view: str = Query("week", pattern="^(day|week)$"),
    service_id: str | None = Query(None),
    demo: bool = Query(True),
):
    filters = {"date": date_str, "view": view, "service_id": service_id}
    return _render_professional_schedule(request, None, None, filters, demo)
