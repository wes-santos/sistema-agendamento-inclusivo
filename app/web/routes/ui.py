from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated, Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session, joinedload

from app.db import get_db
from app.deps import require_roles
from app.models.appointment import Appointment, AppointmentStatus
from app.models.professional import Professional
from app.models.student import Student
from app.models.user import Role, User
from app.schemas.dashboard_family import StudentApptItem, StudentApptSummary

router = APIRouter(prefix="/ui", tags=["ui"])

templates = Jinja2Templates(directory="app/web/templates")
templates.env.globals.update(now=lambda: datetime.now(ZoneInfo("America/Sao_Paulo")))
templates.env.globals.update(Role=Role)
templates.env.add_extension("jinja2.ext.do")
templates.env.auto_reload = True
templates.env.cache = {}


# -------- helpers


def _ensure_tz(tz_local: str):
    from zoneinfo import ZoneInfo

    try:
        tz = ZoneInfo(tz_local)
    except Exception:
        from zoneinfo import ZoneInfo as _ZI

        tz = _ZI("America/Sao_Paulo")
    return tz


def _week_bounds_local(anchor: date, tz) -> tuple[datetime, datetime]:
    # segunda às 00:00 até segunda seguinte 00:00
    start_local_date = anchor - timedelta(days=anchor.weekday())
    start_local = datetime.combine(start_local_date, time.min, tzinfo=tz)
    end_local = start_local + timedelta(days=7)
    return start_local, end_local


def _fmt_period(d: date) -> str:
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


# -------- login (mínimo)
@router.get("/login")
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


# -------- Detalhe do agendamento (profissional/coordenação)
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
        base_week = str(request.url_for("ui_professional_week"))
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

    return templates.TemplateResponse(
        "appointment_detail.html",
        {
            "request": request,
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
    tz = _ensure_tz(tz_local)

    # Fallback de colunas (starts_at/ends_at ou *_utc)
    START_COL = Appointment.starts_at

    # Momento agora em UTC-aware para comparação
    now_utc = datetime.now(UTC)

    qbase = (
        db.query(Appointment)
        .join(Student, Appointment.student_id == Student.id)
        .options(joinedload(Appointment.student), joinedload(Appointment.professional))
        .filter(Student.guardian_user_id == current_user.id)
    )

    # Filtro de período
    if range == "upcoming":
        qbase = qbase.filter(START_COL >= now_utc)
    elif range == "past":
        qbase = qbase.filter(START_COL < now_utc)

    # Status (aceita Enum ou str)
    if status:
        try:
            st = AppointmentStatus(status)
            qbase = qbase.filter(Appointment.status == st)
        except Exception:
            qbase = qbase.filter(
                func.lower(func.cast(Appointment.status, func.TEXT)).like(
                    f"%{status.lower()}%"
                )
            )

    # Date range (se vierem naive, assume UTC-naive)
    if date_from:
        if date_from.tzinfo is None:
            date_from = date_from.replace(tzinfo=UTC)
        qbase = qbase.filter(START_COL >= date_from)
    if date_to:
        if date_to.tzinfo is None:
            date_to = date_to.replace(tzinfo=UTC)
        qbase = qbase.filter(START_COL < date_to)

    # Busca (serviço/local) – CORRIGIDO o like
    if q:
        like = f"%{q.strip()}%"
        parts = []
        if hasattr(Appointment, "service"):
            parts.append(Appointment.service.ilike(like))
        if hasattr(Appointment, "location"):
            parts.append(Appointment.location.ilike(like))
        if parts:
            qbase = qbase.filter(or_(*parts))

    qbase = qbase.order_by(START_COL.asc())

    # Paginação
    total_items = qbase.count()
    page = max(1, page)
    page_size = max(1, min(100, page_size))
    items = qbase.offset((page - 1) * page_size).limit(page_size).all()
    total_pages = max(1, (total_items + page_size - 1) // page_size)

    # Contagem por status (do guardião, sem janela de tempo)
    rows = (
        db.query(Appointment.status, func.count(Appointment.id))
        .join(Student, Appointment.student_id == Student.id)
        .filter(Student.guardian_user_id == current_user.id)
        .group_by(Appointment.status)
        .all()
    )
    count_by_status = {
        (s.name if hasattr(s, "name") else str(s)): int(c) for (s, c) in rows
    }

    # Próximo agendamento (não cancelado)
    next_appt = (
        db.query(Appointment)
        .join(Student, Appointment.student_id == Student.id)
        .filter(
            Student.guardian_user_id == current_user.id,
            START_COL >= now_utc,
            Appointment.status != AppointmentStatus.CANCELLED,
        )
        .order_by(START_COL.asc())
        .first()
    )

    next_appt_dt = next_appt.starts_at if next_appt else None
    next_appt_str = _fmt_local(next_appt_dt, tz) if next_appt_dt else None

    # Builders auxiliares
    def _to_item(ap: Appointment) -> StudentApptItem:
        starts_utc = getattr(ap, "starts_at", getattr(ap, "starts_at_utc", None))
        ends_utc = getattr(ap, "ends_at", getattr(ap, "ends_at_utc", None))
        prof_name = None
        try:
            prof = getattr(ap, "professional", None)
            if prof is not None:
                prof_name = getattr(prof, "name", None) or getattr(prof, "email", None)
        except Exception:
            pass
        return StudentApptItem(
            id=ap.id,
            service=getattr(ap, "service", None),
            status=ap.status,
            start_at_utc=starts_utc,
            end_at_utc=ends_utc,
            start_at_local=(starts_utc.astimezone(tz) if (tz and starts_utc) else None),
            end_at_local=(ends_utc.astimezone(tz) if (tz and ends_utc) else None),
            location=getattr(ap, "location", None),
            professional_id=ap.professional_id,
            professional_name=prof_name,
        )

    summary = StudentApptSummary(
        total_upcoming=int(
            count_by_status.get("SCHEDULED", 0) + count_by_status.get("CONFIRMED", 0)
        ),
        total_past=int(count_by_status.get("DONE", 0)),
        total_cancelled=int(count_by_status.get("CANCELLED", 0)),
        next_appointment_start_utc=(
            getattr(next_appt, "starts_at", getattr(next_appt, "starts_at_utc", None))
            if next_appt
            else None
        ),
        next_appointment_service=(
            getattr(next_appt, "service", None) if next_appt else None
        ),
    )

    # URLs de paginação e limpar
    base_path = str(request.url_for("ui_family_appointments"))
    base_params = {
        "range": range,
        "status": status or "",
        "q": q or "",
        "page_size": page_size,
        "tz_local": tz.key,
    }
    page_prev_url = (
        _build_url(base_path, {**base_params, "page": page - 1}) if page > 1 else None
    )
    page_next_url = (
        _build_url(base_path, {**base_params, "page": page + 1})
        if page < total_pages
        else None
    )
    clear_filters_url = _build_url(
        base_path,
        {"range": "upcoming", "page": 1, "page_size": page_size, "tz_local": tz.key},
    )

    trail = [("/", "Início"), ("/ui/family/appointments", "Meus agendamentos")]

    return templates.TemplateResponse(
        "family_appointments.html",  # novo template (abaixo)
        {
            "request": request,
            "current_user": current_user,
            "items": [_to_item(ap) for ap in items],
            "summary": summary,
            "next_appt_str": next_appt_str,
            "page": page,
            "page_size": page_size,
            "total_items": total_items,
            "total_pages": total_pages,
            "page_prev_url": page_prev_url,
            "page_next_url": page_next_url,
            "clear_filters_url": clear_filters_url,
            "range": range,
            "status": status,
            "q": q or "",
            "trail": trail,
        },
    )


# -------- Profissional: semana
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
    # --- TZ local
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
            return templates.TemplateResponse(
                "professional_link_missing.html",
                {
                    "request": request,
                    "current_user": current_user,
                    "link_request_url": "/ui/coordination/link-request",
                    "support_email": "coordenacao@suaescola.com.br",
                },
                status_code=403,
            )
    else:  # COORDINATION
        if professional_id is None:
            raise HTTPException(400, "Informe professional_id")
        prof_id = int(professional_id)

    # --- Janela local -> UTC
    today_local = datetime.now(tz).date()
    start_local = start or (
        today_local - timedelta(days=today_local.weekday())
    )  # segunda
    start_dt_local = datetime.combine(start_local, time.min, tzinfo=tz)
    end_dt_local = start_dt_local + timedelta(days=days)
    start_utc = start_dt_local.astimezone(UTC)
    end_utc = end_dt_local.astimezone(UTC)

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

    trail = [("/", "Início"), ("/ui/professional/week", "Minha agenda")]

    return templates.TemplateResponse(
        "professional_week.html",
        {
            "request": request,
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


# -------- Coordenação: overview
@router.get("/coordination/overview", name="ui_coordination_overview")
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
        start_local.astimezone(datetime.timezone.utc)
        if hasattr(datetime, "timezone")
        else start_local
    )
    end_utc = (
        end_local.astimezone(datetime.timezone.utc)
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
    base_path = str(request.url_for("ui_coordination_overview"))
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
        ("/ui/coordination/overview", "Coordenação — Visão geral"),
    ]

    def jinja_url_for(name: str, **params) -> str:
        return str(request.url_for(name, **params))

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
            "prev_url": prev_url,
            "next_url": next_url,
            "clear_filters_url": clear_filters_url,
            "trail": trail,
            "url_for": jinja_url_for,
            "csp_nonce": getattr(request.state, "csp_nonce", None),
        },
    )
