import uuid
from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated, Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.params import Query as QueryParam
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import and_, func, or_
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
from app.services.appointment_notify import (
    _make_link,
    create_tokens_for_appointment,
)

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
        dt = datetime.fromisoformat(date_to) if date_to else None
    except Exception:
        dt = None
    if df:
        q = q.filter(Appointment.starts_at >= df.astimezone(UTC))
    if dt:
        # dt + 1 dia para incluir todo o dia
        dt_end = dt + timedelta(days=1)
        q = q.filter(Appointment.starts_at < dt_end.astimezone(UTC))

    # serviços (usando DISTINCT na coluna service)
    try:
        svc_rows = (
            db.query(Appointment.service)
            .join(Student)
            .filter(Student.guardian_user_id == current_user.id)
            .distinct()
            .order_by(Appointment.service.asc())
            .all()
        )
        services = [
            {"id": s or "", "name": s or "(sem descrição)"} for (s,) in svc_rows if s
        ]
    except Exception:
        services = []

    # ordenação (mais recentes primeiro)
    q = q.order_by(Appointment.starts_at.desc())

    # paginação (opcional, por enquanto tudo)
    appts = []
    for ap, pr, st in q.all():
        starts_local = ap.starts_at.astimezone(tz)
        ends_local = ap.ends_at.astimezone(tz) if ap.ends_at else None
        appts.append(
            {
                "id": ap.id,
                "service_name": ap.service,
                "professional_name": pr.name or getattr(pr.user, "name", None),
                "starts_at_local": _fmt_local(starts_local, tz),
                "ends_at_local": _fmt_local(ends_local, tz) if ends_local else None,
                "status": _to_badge_status(ap.status),
                "confirm_url": None,
                "cancel_url": None,
            }
        )

    ctx = {
        "current_user": current_user,
        "appointments": appts,
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


# CREATE APPOINTMENT FORM
@router.get(
    "/family/appointments/new", 
    response_class=HTMLResponse, 
    name="family_new_appointment"
)
def ui_family_new_appointment(
    request: Request,
    current_user: User = Depends(require_roles(Role.FAMILY)),
    db: Session = Depends(get_db),
):
    # Get students for this family
    students = db.query(Student).filter(
        Student.guardian_user_id == current_user.id
    ).all()
    
    # Get available professionals and their services
    professionals = db.query(Professional).filter(
        Professional.is_active == True
    ).all()
    
    # Create a list of services from professionals
    services = []
    for prof in professionals:
        if prof.speciality and prof.speciality not in services:
            services.append(prof.speciality)
    
    # Format professionals for dropdown
    professional_options = [
        {
            "id": prof.id,
            "name": f"{prof.name} ({prof.speciality})" if prof.speciality else prof.name
        }
        for prof in professionals
    ]
    
    context = {
        "current_user": current_user,
        "students": students,
        "professionals": professional_options,
        "services": [{"id": s, "name": s} for s in services] if services else [],
    }
    
    return render(request, "pages/family/appointment_new.html", context)


# GET AVAILABLE SLOTS FOR A PROFESSIONAL ON A DATE
@router.get("/family/appointments/slots", response_class=HTMLResponse)
def ui_family_appointment_slots(
    professional_id: int,
    date: str,  # Now accepts DD/MM/YYYY format
    db: Session = Depends(get_db),
):
    """Get available time slots for a professional on a specific date"""
    try:
        print(f"Loading slots for professional_id={professional_id}, date={date}")
        
        from datetime import date as date_type
        from zoneinfo import ZoneInfo
        from app.api.v1.slots import get_slots_local
        
        # Parse DD/MM/YYYY format
        day, month, year = map(int, date.split('/'))
        date_obj = date_type(year, month, day)
        tz_local = "America/Sao_Paulo"
        
        print(f"Parsed date object: {date_obj}")
        
        # Get available slots
        slots_response = get_slots_local(
            professional_id=professional_id,
            date_local=date_obj,
            slot_minutes=60,  # 1 hour slots
            tz_local=tz_local,
            db=db
        )
        
        print(f"Slots response: {slots_response}")
        
        # Return just the time slots as JSON
        return JSONResponse(content={
            "slots": slots_response["slots"],
            "slots_iso": slots_response["slots_iso"]
        })
        
    except ValueError as e:
        print(f"ValueError parsing date: {e}")
        return JSONResponse(content={"slots": [], "error": "Formato de data inválido"}, status_code=400)
    except Exception as e:
        print(f"Error loading slots: {e}")
        return JSONResponse(content={"slots": [], "error": str(e)}, status_code=400)


# CREATE APPOINTMENT ACTION
@router.post(
    "/family/appointments", 
    response_class=HTMLResponse, 
    name="family_create_appointment"
)
def ui_family_create_appointment(
    request: Request,
    student_id: int = Form(...),
    professional_id: int = Form(...),
    service: str = Form(...),
    date_str: str = Form(..., alias="date"),  # Now accepts DD/MM/YYYY format
    time: str = Form(...),
    location: str = Form(None),
    current_user: User = Depends(require_roles(Role.FAMILY)),
    db: Session = Depends(get_db),
):
    try:
        # Validate form fields
        if not student_id:
            raise HTTPException(400, "Por favor, selecione um aluno.")
        
        if not professional_id:
            raise HTTPException(400, "Por favor, selecione um profissional.")
            
        if not service:
            raise HTTPException(400, "Por favor, informe o serviço.")
            
        if not date_str:
            raise HTTPException(400, "Por favor, informe a data.")
            
        if not time:
            raise HTTPException(400, "Por favor, informe o horário.")
        
        # Validate that the student belongs to this family
        student = db.query(Student).filter(
            Student.id == student_id,
            Student.guardian_user_id == current_user.id
        ).one_or_none()
        
        if not student:
            raise HTTPException(400, "Aluno não encontrado ou não pertence a esta família")
        
        # Validate that the professional exists and is active
        professional = db.query(Professional).filter(
            Professional.id == professional_id,
            Professional.is_active == True
        ).one_or_none()
        
        if not professional:
            raise HTTPException(400, "Profissional não encontrado ou inativo")
        
        # Parse date (DD/MM/YYYY format) and time
        tz = ZoneInfo("America/Sao_Paulo")
        try:
            # Parse DD/MM/YYYY format
            day, month, year = map(int, date_str.split('/'))
            appointment_date = date(year, month, day)
            appointment_time = datetime.strptime(time, "%H:%M").time()
            start_datetime_local = datetime.combine(appointment_date, appointment_time, tzinfo=tz)
            start_datetime_utc = start_datetime_local.astimezone(UTC)
            
            # End time (assume 1 hour duration)
            end_datetime_local = start_datetime_local + timedelta(hours=1)
            end_datetime_utc = start_datetime_utc + timedelta(hours=1)
        except ValueError:
            raise HTTPException(400, "Data ou hora inválida")
        
        # Check for conflicts (optional - you might want to implement this)
        # For now, we'll just create the appointment
        
        # Create the appointment
        appointment = Appointment(
            student_id=student_id,
            professional_id=professional_id,
            service=service,
            location=location,
            starts_at=start_datetime_utc,
            ends_at=end_datetime_utc,
            status=AppointmentStatus.SCHEDULED,
        )

        db.add(appointment)
        db.flush()

        confirm_token = cancel_token = None
        confirm_token, cancel_token = create_tokens_for_appointment(
            db, appointment, current_user.email
        )

        db.commit()
        db.refresh(appointment)

        # Send confirmation email
        try:
            _send_appointment_booking_email(
                db,
                appointment,
                current_user,
                confirm_token=confirm_token,
                cancel_token=cancel_token,
            )
        except Exception as email_error:
            # Log the error but don't fail the appointment creation
            print(f"Failed to send appointment booking email: {email_error}")
        
        # Redirect to appointment details or list
        return RedirectResponse(
            url=f"/family/appointments/{appointment.id}", 
            status_code=303
        )
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        # Return to form with error
        # Get data again for the form
        students = db.query(Student).filter(
            Student.guardian_user_id == current_user.id
        ).all()
        
        professionals = db.query(Professional).filter(
            Professional.is_active == True
        ).all()
        
        professional_options = [
            {
                "id": prof.id,
                "name": f"{prof.name} ({prof.speciality})" if prof.speciality else prof.name
            }
            for prof in professionals
        ]
        
        services = []
        for prof in professionals:
            if prof.speciality and prof.speciality not in services:
                services.append(prof.speciality)
        
        context = {
            "current_user": current_user,
            "students": students,
            "professionals": professional_options,
            "services": [{"id": s, "name": s} for s in services] if services else [],
            "error": f"Erro ao criar agendamento: {str(e)}. Por favor, tente novamente.",
            "form_data": {
                "student_id": student_id,
                "professional_id": professional_id,
                "service": service,
                "date": date_str,
                "time": time,
                "location": location,
            }
        }
        
        return render(request, "pages/family/appointment_new.html", context)


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


    return dt.astimezone(tz).strftime("%d/%m/%Y %H:%M")


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

    trail = [("/", "Início"), ("/family/appointments", "Meus agendamentos")]

    return render(
        request,
        "pages/family_appointments.html",  # novo template (abaixo)
        {
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


def _send_appointment_booking_email(
    db: Session,
    appointment: Appointment,
    guardian_user: User,
    *,
    confirm_token: uuid.UUID,
    cancel_token: uuid.UUID,
):
    """Send appointment booking confirmation email to guardian and professional"""
    from app.email.render import render as render_email
    from app.services.mailer import send_email
    from app.models.student import Student
    from app.models.professional import Professional
    from zoneinfo import ZoneInfo

    if not confirm_token or not cancel_token:
        print("Missing confirmation/cancellation tokens; skipping email notification.")
        return
    
    # Get related objects
    student = db.query(Student).filter(Student.id == appointment.student_id).first()
    professional = db.query(Professional).filter(Professional.id == appointment.professional_id).first()
    
    if not student or not professional:
        return
    
    # Format date for email
    tz = ZoneInfo("America/Sao_Paulo")
    starts_local = appointment.starts_at.astimezone(tz).strftime("%d/%m/%Y %H:%M")
    
    confirm_url = _make_link(f"/public/appointments/confirm/{confirm_token}")
    cancel_url = _make_link(f"/public/appointments/cancel/{cancel_token}")
    
    # Prepare email context for family
    family_ctx = {
        "guardian_name": guardian_user.name,
        "student_name": student.name,
        "professional_name": professional.name,
        "service_name": appointment.service,
        "starts_local": starts_local,
        "location": appointment.location or "Não especificado",
        "confirm_url": confirm_url,
        "cancel_url": cancel_url,
    }
    
    # Send email to guardian (family)
    try:
        family_html = render_email("appointment_booking_family.html").render(family_ctx)
        family_subject = f"[SAI] Agendamento realizado - {starts_local}"
        send_email(family_subject, [guardian_user.email], family_html, text=None)
    except Exception as e:
        print(f"Failed to send email to guardian: {e}")
    
    # Prepare email context for professional
    professional_ctx = {
        "professional_name": professional.name,
        "guardian_name": guardian_user.name,
        "student_name": student.name,
        "service_name": appointment.service,
        "starts_local": starts_local,
        "location": appointment.location or "Não especificado",
    }
    
    # Send email to professional
    if hasattr(professional, 'user') and professional.user and professional.user.email:
        try:
            professional_html = render_email("appointment_booking_professional.html").render(professional_ctx)
            professional_subject = f"[SAI] Novo agendamento - {starts_local}"
            send_email(professional_subject, [professional.user.email], professional_html, text=None)
        except Exception as e:
            print(f"Failed to send email to professional: {e}")
