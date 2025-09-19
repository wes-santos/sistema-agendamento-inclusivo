from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy import and_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit.helpers import record_audit
from app.db import get_db
from app.deps import require_roles
from app.models.appointment import Appointment, AppointmentStatus
from app.models.availability import Availability
from app.models.professional import Professional
from app.models.student import Student
from app.models.user import Role, User
from app.schemas.appointments import (
    AppointmentOut,
    CreateAppointmentIn,
    RescheduleIn,
    Step1CheckIn,
    Step1CheckOut,
    Step2ReviewIn,
    Step2ReviewOut,
)
from app.services.appointment_notify import (
    create_tokens_for_appointment,
    send_confirmation_email_bg,
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


def _ensure_can_manage_appointment(db: Session, user: User, ap: Appointment):
    # COORDINATION pode tudo; FAMILY só se for o responsável do aluno
    if user.role == Role.COORDINATION:
        return
    if user.role == Role.FAMILY:
        # lazy: ap.student já está mapeado no modelo
        if not ap.student or ap.student.guardian_user_id != user.id:
            raise HTTPException(403, "Você não pode remarcar este atendimento.")
        return
    # Outros perfis não podem (ex.: PROFESSIONAL) — ajuste se quiser permitir
    raise HTTPException(403, "Perfil sem permissão para remarcar.")


def _fits_availability(
    db: Session, professional_id: int, start_utc: datetime, minutes: int
) -> bool:
    end_utc = start_utc + timedelta(minutes=minutes)
    avs = (
        db.query(Availability)
        .filter(Availability.professional_id == professional_id)
        .all()
    )
    day_avs = [
        (a.starts_utc, a.ends_utc) for a in avs if a.weekday == start_utc.weekday()
    ]
    if not day_avs:
        return False
    s_t, e_t = start_utc.time(), end_utc.time()
    return any(s_t >= a0 and e_t <= a1 for (a0, a1) in day_avs)


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
    student = _ensure_family_permission(db, current_user, payload.student_id)

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
    background_tasks: BackgroundTasks,
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
        service=prof.speciality,
    )
    db.add(ap)
    try:
        db.flush()  # tenta obter id cedo
    except Exception as e:
        if (
            "uq_appt_prof_start" in str(e.orig)
            or "unique" in str(e.orig).lower()
            or getattr(getattr(e, "orig", None), "pgcode", None) == "23505"
        ):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Ops, o horário acabou de ser reservado por outra pessoa. Atualize os horários e escolha outro.",
            ) from IntegrityError
        raise

    guardian = db.get(User, student.guardian_user_id)

    confirm_token, cancel_token = create_tokens_for_appointment(
        db, ap, email=guardian.email, hours=48
    )

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
        if (
            "uq_appt_prof_start" in str(e.orig)
            or "unique" in str(e.orig).lower()
            or getattr(getattr(e, "orig", None), "pgcode", None) == "23505"
        ):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Ops, o horário acabou de ser reservado por outra pessoa. Atualize os horários e escolha outro.",
            ) from IntegrityError
        raise

    db.refresh(ap)

    background_tasks.add_task(
        send_confirmation_email_bg,
        ap.id,
        guardian.id,
        str(confirm_token),
        str(cancel_token),
    )

    return AppointmentOut(
        id=ap.id,
        professional_id=ap.professional_id,
        student_id=ap.student_id,
        starts_at=iso_utc(ap.starts_at),
        ends_at=iso_utc(ap.ends_at),
        status=ap.status.value,
    )


@router.put("/{appointment_id}/reschedule", response_model=AppointmentOut)
def reschedule_appointment(
    appointment_id: int,
    payload: RescheduleIn,
    request: Request,
    current_user: User = Depends(require_roles(Role.FAMILY, Role.COORDINATION)),
    db: Session = Depends(get_db),
):
    ap = db.get(Appointment, appointment_id)
    if not ap:
        raise HTTPException(404, "Agendamento não encontrado")

    _ensure_can_manage_appointment(db, current_user, ap)

    # Regra: mínimo 6h de antecedência
    new_start = _parse_start(
        payload.new_starts_at_iso
    )  # mesma função usada no agendamento
    min_allowed = datetime.now(UTC) + timedelta(hours=6)
    if new_start < min_allowed:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Remarcação deve ocorrer com antecedência mínima de 6h.",
        )

    # Mantém a mesma duração
    slot_minutes = int((ap.ends_at - ap.starts_at).total_seconds() // 60)
    if slot_minutes <= 0:
        raise HTTPException(400, "Duração inválida do atendimento atual.")

    # 1) Disponibilidade do profissional no dia/horário (não mexe na tua tabela)
    if not _fits_availability(db, ap.professional_id, new_start, slot_minutes):
        raise HTTPException(409, "Fora do horário de atendimento do profissional.")

    new_end = new_start + timedelta(minutes=slot_minutes)

    # 2) Conflito com OUTROS agendamentos (ignora o próprio)
    conflict = (
        db.query(Appointment.id)
        .filter(
            and_(
                Appointment.professional_id == ap.professional_id,
                Appointment.status != AppointmentStatus.CANCELLED,
                Appointment.id != ap.id,
                Appointment.starts_at < new_end,
                Appointment.ends_at > new_start,
            )
        )
        .first()
    )
    if conflict:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Horário indisponível (conflito com outro atendimento).",
        )

    # Atualiza horários (status permanece); updated_at é onupdate
    ap.starts_at = new_start
    ap.ends_at = new_end

    record_audit(
        db,
        request=request,
        user_id=current_user.id,
        action="RESCHEDULE",
        entity="appointment",
        entity_id=ap.id,
    )

    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        # Se outra corrida ganhar, mantemos 409 (mesmo padrão do create)
        if "unique" in str(e.orig).lower() or "uq_appt_prof_start" in str(e.orig):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Ops, o horário acabou de ser reservado por outra pessoa. Atualize e escolha outro.",
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
