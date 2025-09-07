from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit.helpers import record_audit
from app.db import get_db
from app.deps import require_roles
from app.models.appointment import Appointment, AppointmentStatus
from app.models.professional import Professional
from app.models.student import Student
from app.models.user import Role, User
from app.schemas.appointments import (
    AppointmentOut,
    CreateAppointmentIn,
    Step1CheckIn,
    Step1CheckOut,
    Step2ReviewIn,
    Step2ReviewOut,
)
from app.services.slot_validator import validate_slot
from app.utils.tz import iso_utc

router = APIRouter(prefix="/appointments", tags=["appointments"])


def _parse_start(payload_iso: str) -> datetime:
    try:
        dt = datetime.fromisoformat(payload_iso.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            # se vier sem TZ, interpretamos como UTC (evitar erro duro pra UI básica)
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except Exception:
        raise HTTPException(
            400,
            detail="starts_at_iso inválido (use ISO-8601, ex.: 2025-09-10T14:00:00Z)",
        ) from Exception


def _ensure_family_permission(db: Session, user: User, student_id: int):
    st = db.get(Student, student_id)
    if not st:
        raise HTTPException(404, "Aluno não encontrado")
    if user.role == Role.FAMILY and st.guardian_user_id != user.id:
        raise HTTPException(403, "Você não pode agendar para este aluno")
    return st


def _load_professional(db: Session, professional_id: int) -> Professional:
    prof = db.get(Professional, professional_id)
    if not prof:
        raise HTTPException(404, "Profissional não encontrado")
    if not prof.is_active:
        raise HTTPException(400, "Profissional inativo")
    return prof


# ------- Passo 1: escolher/validar horário -------
@router.post("/step1", response_model=Step1CheckOut)
def step1_check(
    payload: Step1CheckIn,
    current_user: Annotated[
        User, Depends(require_roles(Role.FAMILY, Role.COORDINATION))
    ],
    db: Session = Depends(get_db),
):
    _load_professional(db, payload.professional_id)
    start_utc = _parse_start(payload.starts_at_iso)
    ok, reason = validate_slot(
        db, payload.professional_id, start_utc, payload.slot_minutes
    )
    return Step1CheckOut(
        ok=ok,
        professional_id=payload.professional_id,
        starts_at=iso_utc(start_utc),
        ends_at=iso_utc(start_utc + timedelta(minutes=payload.slot_minutes)),
        slot_minutes=payload.slot_minutes,
        reason=None if ok else reason,
    )


# ------- Passo 2: revisar dados -------
@router.post("/step2", response_model=Step2ReviewOut)
def step2_review(
    payload: Step2ReviewIn,
    current_user: Annotated[
        User, Depends(require_roles(Role.FAMILY, Role.COORDINATION))
    ],
    db: Session = Depends(get_db),
):
    prof = _load_professional(db, payload.professional_id)
    student = _ensure_family_permission(db, current_user, payload.family_id)

    start_utc = _parse_start(payload.starts_at_iso)
    ok, reason = validate_slot(
        db, payload.professional_id, start_utc, payload.slot_minutes
    )
    if not ok:
        raise HTTPException(status.HTTP_409_CONFLICT, reason or "Horário indisponível")

    return Step2ReviewOut(
        professional_id=prof.id,
        professional_name=prof.name,
        student_id=student.id,
        student_name=student.name,
        starts_at=iso_utc(start_utc),
        ends_at=iso_utc(start_utc + timedelta(minutes=payload.slot_minutes)),
        slot_minutes=payload.slot_minutes,
    )


# ------- Passo 3: confirmar (cria) -------
@router.post("", response_model=AppointmentOut, status_code=201)
def create_appointment(
    payload: CreateAppointmentIn,
    request: Request,
    current_user: Annotated[
        User, Depends(require_roles(Role.FAMILY, Role.COORDINATION))
    ],
    db: Session = Depends(get_db),
):
    prof = _load_professional(db, payload.professional_id)
    student = _ensure_family_permission(db, current_user, payload.student_id)

    start_utc = _parse_start(payload.starts_at_iso)
    end_utc = start_utc + timedelta(minutes=payload.slot_minutes)

    # valida antes de criar (pode ainda ocorrer corrida)
    ok, reason = validate_slot(
        db, payload.professional_id, start_utc, payload.slot_minutes
    )
    if not ok:
        raise HTTPException(status.HTTP_409_CONFLICT, reason or "Horário indisponível")

    ap = Appointment(
        student_id=student.id,
        professional_id=prof.id,
        starts_at=start_utc,
        ends_at=end_utc,
        status=AppointmentStatus.SCHEDULED,
        location=payload.location,
    )
    db.add(ap)
    db.flush()  # tenta obter id cedo

    # audit junto na mesma transação
    record_audit(
        db,
        request=request,
        user_id=current_user.id,
        action="CREATE",
        entity="appointment",
        entity_id=ap.id,
    )

    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        # corrida: unique do par (professional_id, starts_at)
        if "uq_appt_prof_start" in str(e.orig) or "unique" in str(e.orig).lower():
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Ops, o horário acabou de ser reservado por outra pessoa. Atualize os horários e escolha outro.",
            ) from Exception
        raise

    db.refresh(ap)
    return AppointmentOut(
        id=ap.id,
        professional_id=ap.professional_id,
        student_id=ap.student_id,
        starts_at=iso_utc(ap.starts_at),
        ends_at=iso_utc(ap.ends_at),
        status=ap.status.value,
    )
