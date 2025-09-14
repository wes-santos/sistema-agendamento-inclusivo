# app/web/routes/coordination.py
from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, time, timedelta
from io import StringIO
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session

# Ajuste estes imports para o seu projeto
from app.db.session import get_db
from app.deps import require_roles
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
) -> HTMLResponse:
    today = date.today()
    kpis = {"to_confirm": 0, "today": 0, "week": 0, "canceled_7d": 0}
    queue: list[dict[str, Any]] = []

    if demo:
        items = demo_appointments(today)
        # Fila: scheduled a partir de hoje e próximos 7 dias
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

    ctx = {
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
):
    return _render_coordination_dashboard(request, current_user, db, demo)


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
    # Defaults
    today = date.today()
    default_from = today.replace(day=1)  # início do mês
    date_from = parse_iso(filters.get("date_from")) or default_from
    date_to = parse_iso(filters.get("date_to")) or today
    group_by = filters.get("group_by") or "day"
    service_id = filters.get("service_id") or None
    professional_id = filters.get("professional_id") or None
    status = filters.get("status") or None

    services = SERVICES
    professionals = PROS

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

    persist_query = build_persist_query(
        request,
        keep=[
            "date_from",
            "date_to",
            "group_by",
            "service_id",
            "professional_id",
            "status",
        ],
    )

    ctx = {
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
    # Mesmo filtro da tela:
    today = date.today()
    default_from = today.replace(day=1)
    df = parse_iso(date_from) or default_from
    dt = parse_iso(date_to) or today

    rows: list[dict[str, Any]] = []

    if demo:
        items = demo_appointments(today)
    else:
        items = []  # TODO: troque por sua query real

    items = filter_items(items, df, dt, service_id, professional_id, status)
    rows, totals = aggregate(items, group_by)

    # CSV
    buf = StringIO()
    buf.write("label,scheduled,confirmed,attended,canceled,no_show,amount\n")
    for r in rows:
        # amount no CSV vai numérico com ponto (sem R$)
        # r["amount"] é string R$ — vamos recalcular pelo totals de cada linha:
        # como r["amount"] veio formatado, precisamos somar de novo ou guardar bruto; mais simples: tira símbolos
        amt_str = (
            r["amount"].replace("R$", "").strip().replace(".", "").replace(",", ".")
        )
        buf.write(
            f'{r["label"]},{r["scheduled"]},{r["confirmed"]},{r["attended"]},{r["canceled"]},{r["no_show"]},{amt_str}\n'
        )

    filename = f'reports_{group_by}_{df.strftime("%Y%m%d")}_{dt.strftime("%Y%m%d")}.csv'
    headers = {
        "Content-Type": "text/csv; charset=utf-8",
        "Content-Disposition": f'attachment; filename="{filename}"',
    }
    return Response(content=buf.getvalue(), headers=headers)
