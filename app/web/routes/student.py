from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session, joinedload

from app.db import get_db
from app.deps import require_roles
from app.models.appointment import Appointment, AppointmentStatus
from app.models.student import Student
from app.models.user import Role, User
from app.web.templating import render

router = APIRouter()


@router.get("/student/dashboard", response_class=HTMLResponse, name="student_dashboard")
def student_dashboard(
    request: Request,
    current_user: User = Depends(require_roles(Role.STUDENT)),
    db: Session = Depends(get_db),
):
    student = (
        db.query(Student)
        .options(joinedload(Student.guardian))
        .filter(Student.user_id == current_user.id)
        .first()
    )
    if not student:
        raise HTTPException(status_code=404, detail="Perfil de aluno não encontrado.")

    tz = ZoneInfo("America/Sao_Paulo")
    now = datetime.now(UTC)

    appointments = (
        db.query(Appointment)
        .options(joinedload(Appointment.professional))
        .filter(
            Appointment.student_id == student.id,
            Appointment.starts_at >= now,
            Appointment.status.in_(
                [AppointmentStatus.SCHEDULED, AppointmentStatus.CONFIRMED]
            ),
        )
        .order_by(Appointment.starts_at.asc())
        .all()
    )

    upcoming = []
    for ap in appointments:
        starts_local = ap.starts_at.astimezone(tz)
        ends_local = ap.ends_at.astimezone(tz) if ap.ends_at else None
        upcoming.append(
            {
                "id": ap.id,
                "service": ap.service,
                "location": ap.location,
                "professional": getattr(ap.professional, "name", ""),
                "starts_at": starts_local.strftime("%d/%m/%Y %H:%M"),
                "ends_at": ends_local.strftime("%H:%M") if ends_local else "",
                "status": ap.status.value if isinstance(ap.status, AppointmentStatus) else ap.status,
            }
        )

    ctx = {
        "current_user": current_user,
        "student": student,
        "upcoming": upcoming,
        "trail": [("/", "Início"), ("/student/dashboard", "Meu painel")],
    }

    return render(request, "pages/student/dashboard.html", ctx)
