# app/web/routes/coordination.py
from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, time, timedelta
from io import StringIO
from urllib.parse import urlencode
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session
from sqlalchemy import or_, func, case

# Ajuste estes imports para o seu projeto
from app.db.session import get_db
from app.deps import require_roles
from app.models.user import Role, User
from app.models.appointment import Appointment, AppointmentStatus
from app.models.student import Student
from app.models.professional import Professional
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


# ==========================
# Demo data (determinístico)
# ==========================
SERVICES = [
    {"id": "fono", "name": "Fonoaudiologia"},
    {"id": "psico", "name": "Psicopedagogia"},
    {"id": "neuro", "name": "Neuropsicologia"},
]
PROS = [
    {"id": "ana", "name": "Dra. Ana"},
    {"id": "marcos", "name": "Marcos"},
    {"id": "carla", "name": "Carla"},
]


def _svc_by_id(sid: str) -> str:
    for s in SERVICES:
        if s["id"] == sid:
            return s["name"]
    return sid


def _pro_by_id(pid: str) -> str:
    for p in PROS:
        if p["id"] == pid:
            return p["name"]
    return pid


def demo_appointments(anchor: date) -> list[dict[str, Any]]:
    """Cria uma lista de agendamentos em torno da data anchor (+/- alguns dias)."""
    # status: scheduled (aguarda confirmação), confirmed, attended, canceled, no_show
    base_times = [time(9, 0), time(10, 0), time(14, 0)]
    items: list[dict[str, Any]] = []
    data_spec = [
        (-2, "fono", "ana", "scheduled", 120.0, "Silva"),
        (-1, "psico", "marcos", "confirmed", 130.0, "Oliveira"),
        (0, "neuro", "carla", "attended", 150.0, "Souza"),
        (0, "fono", "ana", "canceled", 120.0, "Pereira"),
        (1, "psico", "marcos", "scheduled", 130.0, "Ferraz"),
        (2, "neuro", "carla", "confirmed", 150.0, "Melo"),
        (3, "fono", "ana", "no_show", 120.0, "Lima"),
        (4, "psico", "marcos", "scheduled", 130.0, "Gomes"),
        (5, "neuro", "carla", "scheduled", 150.0, "Dias"),
        (-5, "fono", "ana", "attended", 120.0, "Campos"),
        (-6, "psico", "marcos", "canceled", 130.0, "Teixeira"),
        (-7, "neuro", "carla", "attended", 150.0, "Almeida"),
    ]
    for i, (offset, svc, pro, status, amount, fam_last) in enumerate(data_spec):
        d = anchor + timedelta(days=offset)
        starts = datetime.combine(d, base_times[i % len(base_times)])
        ends = starts + timedelta(minutes=45)
        items.append(
            {
                "id": f"demo-{i+1}",
                "date": d,
                "starts_at": starts,
                "ends_at": ends,
                "starts_at_local": f"{fmt_dmy(d)} {fmt_hm(starts.time())}",
                "ends_at_local": f"{fmt_dmy(d)} {fmt_hm(ends.time())}",
                "family_name": f"Família {fam_last}",
                "service_id": svc,
                "service_name": _svc_by_id(svc),
                "professional_id": pro,
                "professional_name": _pro_by_id(pro),
                "status": status,
                "amount": amount,
                # URLs de ação (exemplos)
                "confirm_url": "/confirm/DEMO" if status == "scheduled" else None,
                "remind_url": "/remind/DEMO" if status == "scheduled" else None,
                "cancel_url": "/cancel/DEMO"
                if status in ("scheduled", "confirmed")
                else None,
            }
        )
    return items


# ==========================
# Agregação de relatórios
# ==========================
def filter_items(
    items: list[dict[str, Any]],
    date_from: date | None,
    date_to: date | None,
    service_id: str | None,
    professional_id: str | None,
    status: str | None,
) -> list[dict[str, Any]]:
    def ok(it: dict[str, Any]) -> bool:
        if date_from and it["date"] < date_from:
            return False
        if date_to and it["date"] > date_to:
            return False
        if service_id and it["service_id"] != service_id:
            return False
        if professional_id and it["professional_id"] != professional_id:
            return False
        if status and it["status"] != status:
            return False
        return True

    return [it for it in items if ok(it)]


def aggregate(
    items: list[dict[str, Any]], group_by: str
) -> tuple[list[dict[str, Any]], dict[str, float]]:
    """Retorna (rows, totals) com campos: scheduled, confirmed, attended, canceled, no_show, amount."""
    buckets: dict[str, dict[str, float]] = {}

    def bucket_key(it: dict[str, Any]) -> str:
        if group_by == "day":
            return fmt_dmy(it["date"])
        if group_by == "service":
            return it["service_name"]
        if group_by == "professional":
            return it["professional_name"]
        return "TOTAL"

    for it in items:
        key = bucket_key(it)
        b = buckets.setdefault(
            key,
            {
                "scheduled": 0,
                "confirmed": 0,
                "attended": 0,
                "canceled": 0,
                "no_show": 0,
                "amount": 0.0,
            },
        )
        b[it["status"]] = b.get(it["status"], 0) + 1
        # Valor: aqui estou somando o valor de "attended" e "confirmed" (ajuste se sua regra for diferente)
        if it["status"] in ("attended", "confirmed"):
            b["amount"] += it["amount"]

    rows = []
    totals = {
        "scheduled": 0,
        "confirmed": 0,
        "attended": 0,
        "canceled": 0,
        "no_show": 0,
        "amount": 0.0,
    }
    for label, agg in sorted(buckets.items()):
        for k in totals:
            totals[k] += agg[k]
        rows.append(
            {
                "label": label,
                "scheduled": int(agg["scheduled"]),
                "confirmed": int(agg["confirmed"]),
                "attended": int(agg["attended"]),
                "canceled": int(agg["canceled"]),
                "no_show": int(agg["no_show"]),
                "amount": format_brl(agg["amount"]),
            }
        )
    return rows, totals


# ==========================
# Dashboard (fila + KPIs)
# ==========================
def _render_coordination_dashboard(
    request: Request,
    current_user: User | None,
    db: Session | None,
    demo: bool,
    *,
    q: str | None = None,
    status: str | None = None,
) -> HTMLResponse:
    today = date.today()
    kpis = {"to_confirm": 0, "today": 0, "week": 0, "canceled_7d": 0}
    queue: list[dict[str, Any]] = []

    if demo:
        items = demo_appointments(today)
        # Fila e KPIs usando dados fake
        queue = [
            {
                "id": it["id"],
                "family_name": it["family_name"],
                "service_name": it["service_name"],
                "professional_name": it["professional_name"],
                "starts_at_local": it["starts_at_local"],
                "status": it["status"],
                "confirm_url": it["confirm_url"],
                "remind_url": it["remind_url"],
                "cancel_url": it["cancel_url"],
            }
            for it in items
            if it["status"] == "scheduled"
            and today <= it["date"] <= today + timedelta(days=7)
        ]
        kpis["to_confirm"] = sum(1 for it in items if it["status"] == "scheduled")
        kpis["today"] = sum(
            1
            for it in items
            if it["date"] == today
            and it["status"] in ("scheduled", "confirmed", "attended")
        )
        week_start = start_of_week(today)
        week_end = end_of_week(today)
        kpis["week"] = sum(
            1
            for it in items
            if week_start <= it["date"] <= week_end
            and it["status"] in ("scheduled", "confirmed", "attended")
        )
        seven_days_ago = today - timedelta(days=7)
        kpis["canceled_7d"] = sum(
            1
            for it in items
            if it["status"] == "canceled" and seven_days_ago <= it["date"] <= today
        )
    else:
        # Dados reais do banco
        from datetime import UTC, datetime
        from zoneinfo import ZoneInfo

        tz = ZoneInfo("America/Sao_Paulo")
        now = datetime.now(UTC)

        # Fila: próximos 7 dias com status SCHEDULED
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
        # filtros
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
                "family_name": g.name if g else getattr(st.guardian, "name", "Família"),
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
            for (ap, st, pr, g) in rows
        ]

        # KPIs
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
        ws = start_of_week(today)
        we = end_of_week(today)
        start_week = datetime.combine(ws, time.min, tzinfo=tz).astimezone(UTC)
        end_week = datetime.combine(we, time.max, tzinfo=tz).astimezone(UTC)
        kpis["week"] = (
            db.query(Appointment)
            .filter(
                Appointment.starts_at >= start_week,
                Appointment.starts_at <= end_week,
                Appointment.status.in_([
                    AppointmentStatus.SCHEDULED,
                    AppointmentStatus.CONFIRMED,
                    AppointmentStatus.DONE,
                ]),
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
    demo: bool = Query(False),
    q: str | None = Query(None),
    status: str | None = Query(None),
):
    return _render_coordination_dashboard(request, current_user, db, demo, q=q, status=status)


# Preview dev
@router.get("/__dev/coordination/dashboard", response_class=HTMLResponse)
def preview_coordination_dashboard(request: Request, demo: bool = Query(True)):
    return _render_coordination_dashboard(request, None, None, demo)


# ==========================
# Reports (filtros + tabela)
# ==========================
def _render_coordination_reports(
    request: Request,
    current_user: User | None,
    db: Session | None,
    filters: dict[str, Any],
    demo: bool,
) -> HTMLResponse:
    # Defaults + quick ranges
    today = date.today()
    default_from = today.replace(day=1)  # início do mês
    quick = (filters.get("range") or "").lower()
    if quick == "today":
        date_from = today
        date_to = today
    elif quick == "week":
        date_from = start_of_week(today)
        date_to = end_of_week(today)
    elif quick == "month":
        date_from = default_from
        # fim do mês: pega início do próximo mês - 1 dia
        from calendar import monthrange

        last_day = monthrange(today.year, today.month)[1]
        date_to = today.replace(day=last_day)
    else:
        date_from = parse_iso(filters.get("date_from")) or default_from
        date_to = parse_iso(filters.get("date_to")) or today
    group_by = filters.get("group_by") or "day"
    service_id = filters.get("service_id") or None
    professional_id = filters.get("professional_id") or None
    status = filters.get("status") or None

    # Opções de filtro
    if demo:
        services = SERVICES
        professionals = PROS
    else:
        services = [
            {"id": s or "(sem descrição)", "name": s or "(sem descrição)"}
            for (s,) in db.query(Appointment.service).distinct().order_by(Appointment.service).all()
        ]
        professionals = [
            {"id": p.id, "name": p.name or getattr(p.user, "name", None) or f"Profissional {p.id}"}
            for p in db.query(Professional).order_by(Professional.name).all()
        ]

    rows: list[dict[str, Any]] = []
    kpis = {"total": 0, "confirmed": 0, "canceled": 0, "attendance_rate": 0.0}

    if demo:
        items = demo_appointments(today)
        items = filter_items(
            items, date_from, date_to, service_id, professional_id, status
        )
        rows, totals = aggregate(items, group_by)

        total_all = (
            totals["scheduled"]
            + totals["confirmed"]
            + totals["attended"]
            + totals["canceled"]
            + totals["no_show"]
        )
        attended = totals["attended"]
        kpis = {
            "total": int(total_all),
            "confirmed": int(totals["confirmed"]),
            "canceled": int(totals["canceled"]),
            "attendance_rate": round((attended / total_all * 100.0), 1)
            if total_all
            else 0.0,
        }
    else:
        # Dados reais
        from sqlalchemy import func, case
        from datetime import UTC, datetime
        from zoneinfo import ZoneInfo

        tz = ZoneInfo("America/Sao_Paulo")
        start_dt = datetime.combine(date_from, time.min, tzinfo=tz).astimezone(UTC)
        end_dt = datetime.combine(date_to, time.max, tzinfo=tz).astimezone(UTC)

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

        # KPIs
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

        # Agrupamento
        if group_by == "day":
            dtexpr = func.date_trunc("day", Appointment.starts_at).label("d")
            rows_raw = (
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
                .filter(Appointment.starts_at >= start_dt, Appointment.starts_at <= end_dt)
                .group_by(dtexpr)
                .order_by(dtexpr)
                .all()
            )
            rows = [
                {
                    "label": r.d.astimezone(tz).date().strftime("%d/%m/%Y"),
                    "scheduled": int(r.scheduled or 0),
                    "confirmed": int(r.confirmed or 0),
                    "attended": int(r.attended or 0),
                    "canceled": int(r.canceled or 0),
                    "no_show": 0,
                }
                for r in rows_raw
            ]
        elif group_by == "service":
            rows_raw = (
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
                    "no_show": 0,
                }
                for r in rows_raw
            ]
        else:  # professional
            rows_raw = (
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
                .group_by(Professional.name)
                .order_by(Professional.name)
                .all()
            )
            rows = [
                {
                    "label": r.label or "(Profissional)",
                    "scheduled": int(r.scheduled or 0),
                    "confirmed": int(r.confirmed or 0),
                    "attended": int(r.attended or 0),
                    "canceled": int(r.canceled or 0),
                    "no_show": 0,
                }
                for r in rows_raw
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
        "kpis": kpis,
        "report_rows": rows,
        "persist_query": persist_query,
        # (opcional) pagination: None por enquanto
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
    demo: bool = Query(False),
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
    return _render_coordination_reports(request, current_user, db, filters, demo)


# Preview dev
@router.get("/__dev/coordination/reports", response_class=HTMLResponse)
def preview_coordination_reports(
    request: Request,
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    group_by: str = Query("day", pattern="^(day|service|professional)$"),
    service_id: str | None = Query(None),
    professional_id: str | None = Query(None),
    status: str | None = Query(None),
    demo: bool = Query(True),
):
    filters = {
        "date_from": date_from,
        "date_to": date_to,
        "group_by": group_by,
        "service_id": service_id,
        "professional_id": professional_id,
        "status": status,
    }
    return _render_coordination_reports(request, None, None, filters, demo)


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
    demo: bool = Query(False),
):
    # Mesmo filtro da tela (real data)
    today = date.today()
    default_from = today.replace(day=1)
    df = parse_iso(date_from) or default_from
    dt = parse_iso(date_to) or today

    from datetime import UTC, datetime
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("America/Sao_Paulo")
    start_dt = datetime.combine(df, time.min, tzinfo=tz).astimezone(UTC)
    end_dt = datetime.combine(dt, time.max, tzinfo=tz).astimezone(UTC)

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
    buf.write("label,scheduled,confirmed,attended,canceled,no_show\n")

    if group_by == "day":
        dtexpr = func.date_trunc("day", Appointment.starts_at)
        rows = (
            db.query(
                dtexpr.label("label"),
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
            .group_by(dtexpr)
            .order_by(dtexpr)
            .all()
        )
        for r in rows:
            label = r.label.astimezone(tz).date().isoformat()
            buf.write(
                f"{label},{int(r.scheduled or 0)},{int(r.confirmed or 0)},{int(r.attended or 0)},{int(r.canceled or 0)},0\n"
            )
    elif group_by == "service":
        rows = (
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
            .group_by(Appointment.service)
            .order_by(Appointment.service)
            .all()
        )
        for r in rows:
            label = r.label or "(sem descrição)"
            buf.write(
                f"{label},{int(r.scheduled or 0)},{int(r.confirmed or 0)},{int(r.attended or 0)},{int(r.canceled or 0)},0\n"
            )
    else:  # professional
        rows = (
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
            .group_by(Professional.name)
            .order_by(Professional.name)
            .all()
        )
        for r in rows:
            label = r.label or "(Profissional)"
            buf.write(
                f"{label},{int(r.scheduled or 0)},{int(r.confirmed or 0)},{int(r.attended or 0)},{int(r.canceled or 0)},0\n"
            )

    filename = f'reports_{group_by}_{df.strftime("%Y%m%d")}_{dt.strftime("%Y%m%d")}.csv'
    headers = {
        "Content-Type": "text/csv; charset=utf-8",
        "Content-Disposition": f'attachment; filename="{filename}"',
    }
    return Response(content=buf.getvalue(), headers=headers)
