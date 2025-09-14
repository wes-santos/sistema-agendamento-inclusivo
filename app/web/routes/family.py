from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends, Request
from fastapi.params import Query
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.core.settings import settings
from app.db.session import get_db
from app.deps import require_roles
from app.models.user import Role, User
from app.models.appointment import Appointment, AppointmentStatus
from app.models.student import Student
from app.models.professional import Professional
from app.web.templating import render

router = APIRouter()


def _to_badge_status(status: AppointmentStatus | str | None) -> str:
    if not status:
        return "scheduled"
    if isinstance(status, AppointmentStatus):
        s = status.value
    else:
        s = str(status)
    s = s.upper()
    if s == "DONE":
        return "past"
    if s in ("CANCELLED", "CANCELED"):
        return "canceled"
    if s == "CONFIRMED":
        return "confirmed"
    return "scheduled"


def _fmt_local(dt: datetime | None, tz: ZoneInfo) -> str | None:
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(tz).strftime("%d/%m/%Y %H:%M")


def _render_family_dashboard(
    request: Request,
    current_user: User | None,
    db: Session | None,
    demo: bool = False,
) -> HTMLResponse:
    ctx = {
        "request": request,
        "current_user": current_user,
        "app_version": getattr(settings, "APP_VERSION", "dev"),
        "next_appointment": None,
        "kpis": {
            "upcoming_30d": 0,
            "confirmed_30d": 0,
            "canceled_30d": 0,
            "total_month": 0,
            "month_label": "Este mês",
        },
        "recent_appointments": [],
        "recent_pagination": None,
    }

    tz = ZoneInfo("America/Sao_Paulo")
    now = datetime.now(UTC)

    if demo:
        ctx["next_appointment"] = {
            "id": "demo-1",
            "service_name": "Fonoaudiologia",
            "professional_name": "Dra. Ana",
            "starts_at_local": "14/09/2025 10:00",
            "ends_at_local": "14/09/2025 10:45",
            "starts_at_human": "Amanhã às 10:00",
            "location": "Sala 3",
            "status": "confirmed",
            "confirm_url": "/confirm/DEMO_TOKEN",
            "cancel_url": "/cancel/DEMO_TOKEN",
        }
    else:
        # Próximo agendamento do responsável (qualquer aluno)
        next_appt = (
            db.query(Appointment, Professional, Student)
            .join(Student, Student.id == Appointment.student_id)
            .join(Professional, Professional.id == Appointment.professional_id)
            .filter(
                Student.guardian_user_id == current_user.id,
                Appointment.starts_at >= now,
                Appointment.status.in_([
                    AppointmentStatus.SCHEDULED,
                    AppointmentStatus.CONFIRMED,
                ]),
            )
            .order_by(Appointment.starts_at.asc())
            .first()
        )
        if next_appt:
            ap, pr, st = next_appt
            ctx["next_appointment"] = {
                "id": ap.id,
                "service_name": ap.service,
                "professional_name": pr.name or getattr(pr.user, "name", None),
                "starts_at_local": _fmt_local(ap.starts_at, tz),
                "ends_at_local": _fmt_local(ap.ends_at, tz),
                "starts_at_human": _fmt_local(ap.starts_at, tz),
                "location": ap.location,
                "status": _to_badge_status(ap.status),
                "confirm_url": None,
                "cancel_url": None,
            }

    # KPIs simples
    start_30d_ago = now - timedelta(days=30)
    start_month_local = datetime.now(tz).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    start_month = start_month_local.astimezone(UTC)
    qbase = (
        db.query(Appointment)
        .join(Student, Student.id == Appointment.student_id)
        .filter(Student.guardian_user_id == current_user.id)
    )
    ctx["kpis"] = {
        "upcoming_30d": qbase.filter(Appointment.starts_at >= now).count(),
        "confirmed_30d": qbase.filter(
            Appointment.starts_at >= start_30d_ago,
            Appointment.status == AppointmentStatus.CONFIRMED,
        ).count(),
        "canceled_30d": qbase.filter(
            Appointment.starts_at >= start_30d_ago,
            Appointment.status == AppointmentStatus.CANCELLED,
        ).count(),
        "total_month": qbase.filter(Appointment.starts_at >= start_month).count(),
        "month_label": datetime.now(tz).strftime("%B").capitalize(),
    }

    # Recentes (últimos 10)
    recent = (
        db.query(Appointment, Professional)
        .join(Professional, Professional.id == Appointment.professional_id)
        .join(Student, Student.id == Appointment.student_id)
        .filter(Student.guardian_user_id == current_user.id)
        .order_by(Appointment.starts_at.desc())
        .limit(10)
        .all()
    )
    ctx["recent_appointments"] = [
        {
            "id": ap.id,
            "service_name": ap.service,
            "professional_name": pr.name or getattr(pr.user, "name", None),
            "starts_at_local": _fmt_local(ap.starts_at, tz),
            "status": _to_badge_status(ap.status),
            "cancel_url": None,
        }
        for (ap, pr) in recent
    ]

    return render(request, "pages/family/dashboard.html", ctx)


def _demo_family_appts(base: datetime):
    base = base.replace(hour=10, minute=0, second=0, microsecond=0)
    items = [
        {
            "id": "a1",
            "service_name": "Psicopedagogia",
            "professional_name": "Marcos",
            "starts_at_local": (base - timedelta(days=2)).strftime("%d/%m/%Y %H:%M"),
            "ends_at_local": (
                base - timedelta(days=2) + timedelta(minutes=45)
            ).strftime("%d/%m/%Y %H:%M"),
            "status": "scheduled",
            "location": "Sala 1",
            "confirm_url": "/family/appointments/a1/confirm",
            "cancel_url": "/family/appointments/a1/cancel",
        },
        {
            "id": "a2",
            "service_name": "Neuropsicologia",
            "professional_name": "Carla",
            "starts_at_local": (base - timedelta(days=4)).strftime("%d/%m/%Y %H:%M"),
            "ends_at_local": (
                base - timedelta(days=4) + timedelta(minutes=45)
            ).strftime("%d/%m/%Y %H:%M"),
            "status": "canceled",
            "location": "Sala 3",
            "confirm_url": None,
            "cancel_url": None,
        },
    ]
    return items


# LISTA
@router.get(
    "/family/appointments", response_class=HTMLResponse, name="family_appointments"
)
def ui_family_appointments(
    request: Request,
    current_user: User = Depends(require_roles(Role.FAMILY)),
    demo: bool = Query(False),
    status: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    service_id: str | None = Query(None),
    db: Session = Depends(get_db),
):
    if demo:
        appts = _demo_family_appts(datetime.now())
        return render(
            request,
            "pages/family/appointments.html",
            {
                "current_user": current_user,
                "appointments": appts,
                "filters": {},
                "pagination": None,
            },
        )

    tz = ZoneInfo("America/Sao_Paulo")
    q = (
        db.query(Appointment, Professional, Student)
        .join(Student, Student.id == Appointment.student_id)
        .join(Professional, Professional.id == Appointment.professional_id)
        .filter(Student.guardian_user_id == current_user.id)
    )
    # filtros
    if status:
        st = status.lower()
        if st == "past":
            q = q.filter(Appointment.status == AppointmentStatus.DONE)
        elif st.startswith("cancel"):
            q = q.filter(Appointment.status == AppointmentStatus.CANCELLED)
        elif st == "confirmed":
            q = q.filter(Appointment.status == AppointmentStatus.CONFIRMED)
        elif st == "scheduled":
            q = q.filter(Appointment.status == AppointmentStatus.SCHEDULED)
    # datas
    try:
        df = datetime.fromisoformat(date_from) if date_from else None
    except Exception:
        df = None
    try:
        dt_ = datetime.fromisoformat(date_to) if date_to else None
    except Exception:
        dt_ = None
    if df:
        if df.tzinfo is None:
            df = df.replace(tzinfo=UTC)
        q = q.filter(Appointment.starts_at >= df)
    if dt_:
        if dt_.tzinfo is None:
            dt_ = dt_.replace(tzinfo=UTC)
        q = q.filter(Appointment.starts_at < dt_)

    # filtro por serviço
    if service_id:
        q = q.filter(Appointment.service == service_id)

    rows = q.order_by(Appointment.starts_at.desc()).all()

    def _to_item(ap: Appointment, prof: Professional, stud: Student) -> dict:
        return {
            "id": ap.id,
            "service_name": ap.service,
            "professional_name": prof.name or getattr(prof.user, "name", None),
            "starts_at_local": _fmt_local(ap.starts_at, tz),
            "ends_at_local": _fmt_local(ap.ends_at, tz),
            "status": _to_badge_status(ap.status),
            "confirm_url": None,
            "cancel_url": None,
        }

    items = [_to_item(ap, pr, st) for (ap, pr, st) in rows]
    # services options (distinct)
    services = [
        {"id": s, "name": s}
        for (s,) in (
            db.query(Appointment.service)
            .join(Student, Student.id == Appointment.student_id)
            .filter(Student.guardian_user_id == current_user.id)
            .distinct()
            .order_by(Appointment.service.asc())
            .all()
        )
    ]
    ctx = {
        "current_user": current_user,
        "appointments": items,
        "filters": {
            "status": status or "",
            "date_from": date_from or "",
            "date_to": date_to or "",
            "service_id": service_id or "",
        },
        "services": services,
        "pagination": None,
    }
    return render(request, "pages/family/appointments.html", ctx)


# DETALHE
@router.get(
    "/family/appointments/{appt_id}",
    response_class=HTMLResponse,
    name="family_appointment_detail",
)
def ui_family_appointment_detail(
    appt_id: int,
    request: Request,
    current_user: User = Depends(require_roles(Role.FAMILY)),
    demo: bool = Query(False),
    db: Session = Depends(get_db),
):
    tz = ZoneInfo("America/Sao_Paulo")

    if demo:
        appts = _demo_family_appts(datetime.now())
        appt = next((a for a in appts if str(a["id"]) == str(appt_id)), None)
        if not appt:
            from fastapi.responses import RedirectResponse

            return RedirectResponse("/family/appointments", status_code=303)
        return render(
            request,
            "pages/family/appointment_detail.html",
            {"current_user": current_user, "appointment": appt},
        )

    row = (
        db.query(Appointment, Professional, Student)
        .join(Student, Student.id == Appointment.student_id)
        .join(Professional, Professional.id == Appointment.professional_id)
        .filter(
            Appointment.id == appt_id,
            Student.guardian_user_id == current_user.id,
        )
        .one_or_none()
    )
    if not row:
        from fastapi.responses import RedirectResponse

        return RedirectResponse("/family/dashboard", status_code=303)

    ap, pr, st = row
    appt_ctx = {
        "id": ap.id,
        "service_name": ap.service,
        "professional_name": pr.name or getattr(pr.user, "name", None),
        "starts_at_local": _fmt_local(ap.starts_at, tz),
        "ends_at_local": _fmt_local(ap.ends_at, tz),
        "location": ap.location,
        "status": _to_badge_status(ap.status),
        "confirm_url": None,
        "cancel_url": None,
    }

    return render(
        request,
        "pages/family/appointment_detail.html",
        {"current_user": current_user, "appointment": appt_ctx},
    )


@router.get("/__dev/family/dashboard", response_class=HTMLResponse)
def preview_family_dashboard(request: Request, demo: bool = True):
    # Reusa a lógica acima mas sem require_roles
    return _render_family_dashboard(request, current_user=None, db=None, demo=demo)


@router.get("/family/dashboard", response_class=HTMLResponse)
def ui_family_dashboard(
    request: Request,
    current_user: User = Depends(require_roles(Role.FAMILY)),
    db: Session = Depends(get_db),
    demo: bool = False,  # ?demo=1 para ver conteúdo fake
):
    return _render_family_dashboard(request, current_user, db, demo)
