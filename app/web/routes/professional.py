from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated, Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import and_, case, func, or_
from sqlalchemy.orm import Session, joinedload

from app.core.settings import settings
from app.db import get_db
from app.deps import require_roles
from app.models.appointment import Appointment, AppointmentStatus
from app.models.professional import Professional
from app.models.student import Student
from app.models.user import Role, User
from app.schemas.dashboard_family import StudentApptItem, StudentApptSummary
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


def parse_date_filter(raw: str | None) -> date | None:
    if not raw:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except Exception:
            continue
    return None


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
    current_user: User,
    db: Session,
    *,
    tz_local: str = "America/Sao_Paulo",
):
    try:
        tz = ZoneInfo(tz_local)
    except Exception:
        tz = ZoneInfo("America/Sao_Paulo")
    today = date.today()
    week_start = start_of_week(today)

    next_session = None
    kpis = {"today": 0, "week": 0, "attended_30d": 0, "no_show_30d": 0}
    today_sessions: list[dict[str, Any]] = []

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
                "starts_at_human": ap.starts_at.astimezone(tz).strftime("%d/%m %H:%M"),
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
        start_today = datetime.combine(today, time.min, tzinfo=tz).astimezone(UTC)
        end_today = datetime.combine(today, time.max, tzinfo=tz).astimezone(UTC)
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
        start_week = datetime.combine(ws, time.min, tzinfo=tz).astimezone(UTC)
        end_week = datetime.combine(we, time.max, tzinfo=tz).astimezone(UTC)
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
):
    return _render_professional_dashboard(request, current_user, db)


# --------------------------
# Render: SCHEDULE (day/week)
# --------------------------
def _render_professional_schedule(
    request: Request,
    current_user: User,
    db: Session,
    filters: dict[str, Any],
) -> HTMLResponse:
    view = "week"

    df_str = (filters.get("date_from") or "").strip()
    dt_str = (filters.get("date_to") or "").strip()

    def _parse_date(value: str | None, fallback: date) -> date:
        try:
            return date.fromisoformat(value) if value else fallback
        except Exception:
            return fallback

    today_d = date.today()
    if df_str and dt_str:
        range_from = _parse_date(df_str, today_d)
        range_to = _parse_date(dt_str, range_from + timedelta(days=6))
    else:
        ws = start_of_week(today_d)
        range_from, range_to = ws, ws + timedelta(days=6)

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
            "date_from": range_from.strftime("%Y-%m-%d"),  # Formato ISO para campos date do HTML
            "date_to": (range_to.strftime("%Y-%m-%d") if range_to else ""),
            "view": view,
            "service_id": filters.get("service_id", ""),
        },
        "services": [],
        "nav": nav,
        "day_rows": None,
        "week": _empty_week_payload(range_from),
    }

    tz = ZoneInfo("America/Sao_Paulo")
    prof = (
        db.query(Professional)
        .filter(Professional.user_id == current_user.id)
        .one_or_none()
    )
    prof_id = prof.id if prof else None

    services: list[dict[str, str]] = []

    if prof_id is not None:
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

        week_start = start_of_week(range_from)
        start_local = datetime.combine(week_start, time.min, tzinfo=tz)
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

        def _label_hm(dt_obj: datetime) -> str:
            return dt_obj.astimezone(tz).strftime("%H:%M")

        week = {"days": [], "rows": []}
        week["days"] = [
            {"label": f"{PT_WEEKDAYS_SHORT[i]} # {fmt_dmy(week_start + timedelta(days=i))}"}
            for i in range(7)
        ]

        ap_map: dict[tuple[int, int], list[Appointment]] = {}
        for ap in appts:
            lt = ap.starts_at.astimezone(tz)
            day_idx = (lt.date() - week_start).days
            if 0 <= day_idx <= 6:
                ap_map.setdefault((day_idx, lt.hour), []).append(ap)

        for hour in range(8, 18):
            cells = []
            for day_idx in range(7):
                items = []
                for ap in ap_map.get((day_idx, hour), []):
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
            week["rows"].append({"label": f"{hour:02d}:00", "cells": cells})

        context["week"] = week

    context["services"] = services

    return render(request, "pages/professional/schedule.html", context)



def _empty_week_payload(base_date: date) -> dict[str, Any]:
    week_start = start_of_week(base_date)
    days = [
        {"label": f"{PT_WEEKDAYS_SHORT[i]} # {fmt_dmy(week_start + timedelta(days=i))}"}
        for i in range(7)
    ]
    rows = []
    for hour in range(8, 18):
        rows.append(
            {
                "label": f"{hour:02d}:00",
                "cells": [{"state": "is-free", "items": []} for _ in range(7)],
            }
        )
    return {"days": days, "rows": rows}

@router.get("/professional/schedule", response_class=HTMLResponse)
def ui_professional_schedule(
    request: Request,
    current_user: User = Depends(require_roles(Role.PROFESSIONAL)),
    db: Session = Depends(get_db),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    service_id: str | None = Query(None),
):
    filters = {"date_from": date_from, "date_to": date_to, "service_id": service_id}
    return _render_professional_schedule(request, current_user, db, filters)


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
    df = parse_date_filter(date_from) or today.replace(day=1)
    dt = parse_date_filter(date_to) or today

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
            rows = []
            for r in rows_raw:
                local_date = r.label.astimezone(tz).date()
                label = local_date.strftime("%d/%m/%Y")
                rows.append(
                    {
                        "label": label,
                        "scheduled": int(r.scheduled or 0),
                        "confirmed": int(r.confirmed or 0),
                        "attended": int(r.attended or 0),
                        "canceled": int(r.canceled or 0),
                    }
                )
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
            rows = []
            for r in rows_raw:
                label = r.label or "(sem descrição)"
                rows.append(
                    {
                        "label": label,
                        "scheduled": int(r.scheduled or 0),
                        "confirmed": int(r.confirmed or 0),
                        "attended": int(r.attended or 0),
                        "canceled": int(r.canceled or 0),
                    }
                )

    ctx = {
        "current_user": current_user,
        "filters": {
            "date_from": df.strftime("%d/%m/%Y"),
            "date_to": dt.strftime("%d/%m/%Y"),
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


# --------------------------
# Appointment Details Route
# --------------------------

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


def _status_key(s) -> str:
    # Normaliza o status para STRING UPPER (compatível com template)
    try:
        # Enum: usa .name (SCHEDULED, CONFIRMED, DONE, CANCELLED...)
        return s.name.upper()
    except Exception:
        return str(s or "").strip().upper()


def _get_col(model, *names):
    for n in names:
        if hasattr(model, n):
            return getattr(model, n)
    return None


def _make_url_factory(request: Request, page_param: str = "page"):
    def make_url(
        path: str,
        params: Mapping[str, Any] | None = None,
        *,
        keep: Iterable[str] | None = None,
        **kwargs,
    ) -> str:
        base = str(request.base_url).rstrip("/")
        query = {}

        if keep:
            current = dict(request.query_params)
            query.update({k: v for k, v in current.items() if k in set(keep)})

        if params:
            query.update({k: v for k, v in params.items() if v is not None})

        if kwargs:
            query.update({k: v for k, v in kwargs.items() if v is not None})

        qs = ("?" + urlencode(query, doseq=True)) if query else ""
        return f"{base}{path}{qs}"

    return make_url


def _fmt_dt_local(dt: datetime | None, tz: ZoneInfo) -> str:
    if not dt:
        return "-"
    d = dt.astimezone(tz)
    # Ex.: 02/09/2025 14:30
    return d.strftime("%d/%m/%Y %H:%M")


def _period_str(d: date) -> str:
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


@router.get("/appointments/{id}", name="appointments_detail")
def appointments_detail(
    request: Request,
    current_user: Annotated[
        User, Depends(require_roles(Role.PROFESSIONAL, Role.COORDINATION))
    ],
    db: Annotated[Session, Depends(get_db)],
    id: int = Path(..., ge=1),
    tz_local: str = Query(default="America/Sao_Paulo"),
    return_url: str | None = Query(
        default=None, description="URL para voltar (opcional)"
    ),
):
    tz = _ensure_tz(tz_local)

    # Carrega o agendamento + aluno (se existir relação)
    ap: Appointment | None = (
        db.query(Appointment)
        .options(joinedload(getattr(Appointment, "student", None)))
        .filter(Appointment.id == id)
        .one_or_none()
    )
    if not ap:
        raise HTTPException(status_code=404, detail="Agendamento não encontrado.")

    # Gate de autorização: PROF só vê os seus
    if current_user.role == Role.PROFESSIONAL:
        prof = (
            db.query(Professional)
            .filter(Professional.user_id == current_user.id)
            .one_or_none()
        )
        if not prof or ap.professional_id != prof.id:
            raise HTTPException(
                status_code=403, detail="Sem permissão para este agendamento."
            )

    # Datas/hora
    s_utc = ap.starts_at
    e_utc = ap.ends_at
    starts_at_str = _fmt_local(s_utc, tz)
    ends_at_str = _fmt_local(e_utc, tz)

    # Duração (min)
    duration_min = None
    if isinstance(s_utc, datetime) and isinstance(e_utc, datetime):
        s = s_utc if s_utc.tzinfo else s_utc.replace(tzinfo=UTC)
        e = e_utc if e_utc.tzinfo else e_utc.replace(tzinfo=UTC)
        duration_min = int((e - s).total_seconds() // 60)

    # Nomes
    student_name = getattr(getattr(ap, "student", None), "name", None)
    # Se quiser exibir nome do profissional, pode buscar por join/lookup de User:
    # professional_name = db.query(User).get(ap.professional_id)?.name (ajuste conforme seu modelo)

    # Voltar: se veio return_url use-o; senão, volta para a semana do agendamento
    if return_url and return_url.startswith("/"):
        back_url = return_url
    else:
        # Note: We'll need to adjust this to reference the new route name without /ui prefix
        try:
            base_week = str(request.url_for("ui_professional_week"))
        except:
            # Fallback if the old route name doesn't exist
            base_week = "/professional/week"
        # calcula a semana do agendamento (no fuso local)
        if isinstance(s_utc, datetime):
            s_local = s_utc if s_utc.tzinfo else s_utc.replace(tzinfo=UTC)
            s_local = s_local.astimezone(tz)
            week_start = (
                s_local.date() - timedelta(days=s_local.date().weekday())
            ).isoformat()
        else:
            # fallback: volta para a semana atual
            week_start = datetime.now(tz).date().isoformat()

        params = {"start": week_start, "tz_local": tz.key}
        # Se for coordenação e a UI usa professional_id na query, preserve:
        if current_user.role == Role.COORDINATION:
            params["professional_id"] = ap.professional_id
        back_url = _build_url(base_week, params)

    # Mapeia status → badge
    raw_status = getattr(ap, "status", None)
    st_lower = (str(raw_status) or "").lower()
    if "confirm" in st_lower:
        status_label = "Confirmado"
        status_kind = "confirmado"
    elif "cancel" in st_lower:
        status_label = "Cancelado"
        status_kind = "cancelado"
    elif any(k in st_lower for k in ("realiz", "done", "complet")):
        status_label = "Realizado"
        status_kind = "realizado"
    else:
        status_label = "Pendente"
        status_kind = "pendente"

    # Campos opcionais
    notes = getattr(ap, "notes", None)
    service = getattr(ap, "service", None)
    location = getattr(ap, "location", None)
    created_at = _fmt_local(getattr(ap, "created_at", None), tz)
    updated_at = _fmt_local(getattr(ap, "updated_at", None), tz)

    return render(
        request,
        "pages/appointment_detail.html",
        {
            "csp_nonce": getattr(request.state, "csp_nonce", None),
            "appointment": {
                "id": ap.id,
                "status_label": status_label,
                "status_kind": status_kind,  # para badge
                "service": service,
                "location": location,
                "student_name": student_name,
                "professional_id": ap.professional_id,
                "starts_at_str": starts_at_str,
                "ends_at_str": ends_at_str,
                "duration_min": duration_min,
                "created_at": created_at,
                "updated_at": updated_at,
                "raw_status": str(raw_status),
            },
            "back_url": back_url,
        },
    )


# ---------------------------
# Professional Week Route
# ---------------------------

@router.get("/professional/week")
def ui_professional_week(
    request: Request,
    current_user: Annotated[
        "User", Depends(require_roles(Role.PROFESSIONAL, Role.COORDINATION))
    ],
    db: Annotated[Session, Depends(get_db)],
    start: date | None = Query(
        default=None, description="YYYY-MM-DD (início da semana local)"
    ),
    days: int = Query(default=7, ge=1, le=14),
    professional_id: int | None = Query(default=None, ge=1),
    status: str | None = Query(default=None),
    q: str | None = Query(default=None),
    tz_local: str = "America/Sao_Paulo",
):
    # --- Janela local -> UTC
    try:
        tz = ZoneInfo(tz_local)
    except Exception:
        tz = ZoneInfo("America/Sao_Paulo")  # fallback seguro

    # --- Resolve professional_id
    if current_user.role == Role.PROFESSIONAL:
        prof = (
            db.query(Professional)
            .filter(Professional.user_id == current_user.id)
            .one_or_none()
        )
        prof_id = prof.id if prof else None
        if prof_id is None:
            # página amigável se não estiver vinculado
            return render(
                request,
                "pages/professional_link_missing.html",
                {
                    "current_user": current_user,
                    "link_request_url": "/coordination/link-request",
                    "support_email": "coordenacao@suaescola.com.br",
                },
                status_code=403,
            )
    else:  # COORDINATION
        if professional_id is None:
            raise HTTPException(400, "Informe professional_id")
        prof_id = int(professional_id)

    today_local = datetime.now(tz).date()
    start_local = (
        today_local - timedelta(days=today_local.weekday())
    )  # segunda
    start_dt_local = datetime.combine(start_local, time.min, tzinfo=tz)
    end_dt_local = start_dt_local + timedelta(days=days)
    start_utc = start_dt_local.astimezone(ZoneInfo("UTC"))
    end_utc = end_dt_local.astimezone(ZoneInfo("UTC"))

    # --- Colunas de data com fallback
    START_COL = (
        Appointment.starts_at
        if hasattr(Appointment, "starts_at")
        else getattr(Appointment, "starts_at_utc", None)
    )
    END_COL = (
        Appointment.ends_at
        if hasattr(Appointment, "ends_at")
        else getattr(Appointment, "ends_at_utc", None)
    )

    if START_COL is None or END_COL is None:
        raise RuntimeError(
            "Appointment precisa ter starts_at/ends_at (ou starts_at_utc/ends_at_utc)."
        )

    # --- Query base
    base = (
        db.query(Appointment)
        .options(joinedload(Appointment.student))
        .filter(
            Appointment.professional_id == prof_id,
            START_COL >= start_utc,
            START_COL < end_utc,
        )
    )

    # status (tenta interpretar pelo Enum; se falhar, ignora silenciosamente)
    if status:
        try:
            st = AppointmentStatus(status)
            base = base.filter(Appointment.status == st)
        except Exception:
            # fallback por string
            base = base.filter(
                func.lower(func.cast(Appointment.status, func.TEXT)).like(
                    f"%{status.lower()}%"
                )
            )

    # busca (aluno, serviço, local)
    if q:
        like = f"%{q.strip()}%"
        parts = []
        if hasattr(Appointment, "service"):
            parts.append(Appointment.service.ilike(like))
        if hasattr(Appointment, "location"):
            parts.append(Appointment.location.ilike(like))
        base = base.join(Student, Student.id == Appointment.student_id).filter(
            or_(*(parts + [Student.name.ilike(like)]))
            if parts
            else Student.name.ilike(like)
        )

    base = base.order_by(START_COL.asc())
    rows = base.all()

    # --- Contagem por status (em toda a janela)
    rows_counts = (
        db.query(Appointment.status, func.count(Appointment.id))
        .filter(
            Appointment.professional_id == prof_id,
            START_COL >= start_utc,
            START_COL < end_utc,
        )
        .group_by(Appointment.status)
        .all()
    )

    def _k(s):
        return s.value if hasattr(s, "value") else str(s)

    count_by_status_map = {_k(s): int(c) for (s, c) in rows_counts}

    # Agregados amigáveis (Confirmados/Cancelados/Realizados)
    confirmados = sum(
        c for (k, c) in count_by_status_map.items() if _status_matches(k, ["confirm"])
    )
    cancelados = sum(
        c for (k, c) in count_by_status_map.items() if _status_matches(k, ["cancel"])
    )
    realizados = sum(
        c
        for (k, c) in count_by_status_map.items()
        if _status_matches(k, ["realiz", "done", "complet"])
    )

    counts = {
        "total": len(rows),
        "confirmados": confirmados,
        "cancelados": cancelados,
        "realizados": realizados,
    }

    # --- Itens para o template
    def _get_dt(obj, *names):
        for n in names:
            if hasattr(obj, n):
                return getattr(obj, n)
        return None

    appointments = []
    for ap in rows:
        s_utc = _get_dt(ap, "starts_at_utc", "starts_at")
        e_utc = _get_dt(ap, "ends_at_utc", "ends_at", "end_at")
        appointments.append(
            {
                "id": ap.id,
                "student_name": getattr(ap.student, "name", None),
                "status": getattr(ap, "status", None),
                "service": getattr(ap, "service", None),
                "location": getattr(ap, "location", None),
                "starts_at_str": _fmt_dt_local(s_utc, tz) if s_utc else "-",
                "ends_at_str": _fmt_dt_local(e_utc, tz) if e_utc else "-",
            }
        )

    # --- Navegação semanal (URLs)
    # Garante query params persistentes (status, q, days, professional_id quando coordenação)

    route_name = request.scope["route"].name
    path_params = getattr(request, "path_params", {}) or {}
    base_path = str(request.url_for(route_name, **path_params))

    base_params = {"days": days}

    if status:
        base_params["status"] = status

    if q:
        base_params["q"] = q

    if current_user.role == Role.COORDINATION:
        base_params["professional_id"] = int(prof_id)

    prev_start = (start_local - timedelta(days=days)).isoformat()
    next_start = (start_local + timedelta(days=days)).isoformat()

    prev_url = _build_url(base_path, {**base_params, "start": prev_start})
    next_url = _build_url(base_path, {**base_params, "start": next_start})

    # Limpar filtros (mantém janela/ids)
    clear_params = {"days": days, "start": start_local.isoformat()}
    if current_user.role == Role.COORDINATION:
        clear_params["professional_id"] = int(prof_id)
    clear_filters_url = _build_url(base_path, clear_params)

    # --- Status options para o <select>
    status_options = []
    try:
        # Tenta usar o Enum (ordem estável)
        for m_name, m_val in getattr(AppointmentStatus, "__members__", {}).items():
            label = m_name.capitalize().replace("_", " ")
            status_options.append(
                (m_val.value if hasattr(m_val, "value") else str(m_val), label)
            )
    except Exception:
        # Fallback: usa chaves já vistas nesta janela
        for k in sorted(count_by_status_map.keys()):
            status_options.append((k, k.capitalize()))

    # --- Período (strings legíveis)
    period_start_str = _period_str(start_dt_local.date())
    period_end_str = _period_str(
        (end_dt_local - timedelta(days=1)).date()
    )  # fim inclusivo na UI

    trail = [("/", "Início"), ("/professional/week", "Minha agenda")]

    return render(
        request,
        "pages/professional_week.html",
        {
            "csp_nonce": request.state.csp_nonce,
            "current_user": current_user,
            # Navegação + período
            "prev_url": prev_url,
            "next_url": next_url,
            "period_start_str": period_start_str,
            "period_end_str": period_end_str,
            # Filtros
            "status_options": status_options,
            "current_status": status,
            "q": q or "",
            "clear_filters_url": clear_filters_url,
            # Sumário e lista
            "counts": counts,
            "appointments": appointments,
            # (opcionais para debug/uso futuro)
            "professional_id": int(prof_id),
            "start": start_local.isoformat(),
            "days": days,
            "summary": {
                "total": counts["total"],
                "by_status": count_by_status_map,
                "window": {
                    "start_local": start_dt_local.isoformat(),
                    "end_local": end_dt_local.isoformat(),
                    "tz_local": tz.key,
                },
            },
            "trail": trail,
        },
    )
