# scripts/seed.py
from __future__ import annotations

import os
import zoneinfo
from collections.abc import Iterable
from datetime import UTC, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

# --- Ajuste conforme seu projeto ---
# get_db é um generator do FastAPI; aqui usamos next(get_db()) pra obter uma Session
from app.db import get_db  # type: ignore

# Models do domínio
from app.models.appointment import Appointment, AppointmentStatus  # type: ignore
from app.models.professional import Professional  # type: ignore
from app.models.student import Student  # type: ignore

# Alguns projetos têm Role/User; trate como opcional
try:
    from app.models.user import Role, User  # type: ignore
except Exception:
    User = None  # type: ignore
    Role = None  # type: ignore


# ---------------- Configuráveis por ENV ----------------
BR_TZ = zoneinfo.ZoneInfo(os.getenv("SEED_TZ", "America/Sao_Paulo"))

# Dias úteis a semear (a partir de hoje)
SEED_BUSINESS_DAYS = int(os.getenv("SEED_DAYS", "5"))

# Janela diária (hora BR)
SEED_START_HOUR = int(os.getenv("SEED_START_HOUR", "9"))  # 09:00
SEED_END_HOUR = int(os.getenv("SEED_END_HOUR", "17"))  # 17:00 (exclusivo)
SEED_STEP_MIN = int(os.getenv("SEED_STEP_MIN", "60"))  # slots de 60min

PROF_NAME = os.getenv("SEED_PROF_NAME", "Dra. Ana Souza")
PROF_EMAIL = os.getenv("SEED_PROF_EMAIL", "ana.souza@example.com")

# Nomes falsos básicos
GUARDIANS = [
    "Marcos Lima",
    "Patrícia Alves",
    "Roberta Dias",
    "Carlos Nogueira",
    "Fernanda Pires",
    "Luciana Souza",
    "Daniel Rocha",
    "Beatriz Martins",
    "Rafael Costa",
    "Juliana Silva",
]
STUDENTS = [
    "Alice Lima",
    "Bruno Alves",
    "Clara Dias",
    "Diego Nogueira",
    "Eduarda Pires",
    "Felipe Souza",
    "Giovana Rocha",
    "Heitor Martins",
    "Isabela Costa",
    "João Silva",
]


# ---------------- Helpers ----------------
def _now_utc() -> datetime:
    return datetime.now(UTC)


def _br_dt(d: datetime, hh: int, mm: int = 0) -> datetime:
    """Cria datetime no fuso BR para a data 'd', retornando UTC (timezone-aware)."""
    base_br = datetime(d.year, d.month, d.day, hh, mm, tzinfo=BR_TZ)
    return base_br.astimezone(UTC)


def _business_days(start_utc: datetime, n_days: int) -> Iterable[datetime]:
    """Gera n dias úteis (UTC reference) a partir de start_utc (incluindo hoje se útil)."""
    d = start_utc.astimezone(BR_TZ).date()
    count = 0
    while count < n_days:
        # weekday(): 0=Mon ... 6=Sun
        if datetime(d.year, d.month, d.day, tzinfo=BR_TZ).weekday() < 5:
            yield datetime(d.year, d.month, d.day, tzinfo=BR_TZ).astimezone(UTC)
            count += 1
        d += timedelta(days=1)


def _hour_range(start_h: int, end_h: int, step_min: int) -> Iterable[time]:
    h = start_h
    while h < end_h:
        yield time(hour=h, minute=0, tzinfo=BR_TZ)
        h += step_min // 60


def get_session() -> Session:
    # Usa o provider do FastAPI
    gen = get_db()
    session: Session = next(gen)  # type: ignore
    return session


def ensure_professional(db: Session) -> Professional:
    q = db.execute(select(Professional).where(Professional.name == PROF_NAME))
    prof = q.scalar_one_or_none()
    if prof:
        return prof

    # tenta setar email se existir
    prof = Professional(name=PROF_NAME)
    if hasattr(Professional, "email"):
        setattr(prof, "email", PROF_EMAIL)

    db.add(prof)
    db.commit()
    db.refresh(prof)
    print(f"[seed] Professional: {prof.id} - {prof.name}")
    return prof


def ensure_guardian_user(db: Session, full_name: str, index: int) -> int | None:
    """Cria um User com Role.FAMILY (se existir). Retorna user_id ou None."""
    if not User or not Role:
        return None

    # tenta achar por email (derivado do nome)
    email = f"guardian{index+1}@example.com".lower()
    q = db.execute(select(User).where(getattr(User, "email") == email))
    usr = q.scalar_one_or_none()
    if usr:
        return getattr(usr, "id")

    # cria novo user com role FAMILY se suportado
    kwargs = {}
    if hasattr(User, "name"):
        kwargs["name"] = full_name
    if hasattr(User, "email"):
        kwargs["email"] = email
    if hasattr(User, "role"):
        kwargs["role"] = getattr(Role, "FAMILY", None) or getattr(Role, "family", None)

    usr = User(**kwargs)  # type: ignore
    # se o modelo exigir senha/hashed_password, preenche algo dummy (opcional)
    for field in ("hashed_password", "password_hash", "password"):
        if hasattr(User, field):
            setattr(usr, field, "not-set-seed")

    db.add(usr)
    db.commit()
    db.refresh(usr)
    print(f"[seed] User (guardian): {getattr(usr, 'id', None)} - {full_name} ({email})")
    return getattr(usr, "id", None)


def ensure_students_with_guardians(db: Session) -> list[Student]:
    created: list[Student] = []
    for i, (g_name, s_name) in enumerate(zip(GUARDIANS, STUDENTS)):
        # student lookup by name
        q = db.execute(select(Student).where(Student.name == s_name))
        st = q.scalar_one_or_none()
        if st:
            created.append(st)
            continue

        st_kwargs = {"name": s_name}

        # cria/atribui responsável se o modelo suportar
        guardian_user_id = ensure_guardian_user(db, g_name, i)
        if guardian_user_id is not None:
            # tenta atributos mais comuns
            for candidate_attr in ("guardian_user_id", "guardian_id", "family_user_id"):
                if hasattr(Student, candidate_attr):
                    st_kwargs[candidate_attr] = guardian_user_id
                    break

        st = Student(**st_kwargs)  # type: ignore
        db.add(st)
        db.commit()
        db.refresh(st)
        print(f"[seed] Student: {st.id} - {st.name}")
        created.append(st)
    return created


def ensure_appointments_grid(
    db: Session,
    *,
    prof: Professional,
    students: list[Student],
    days: int,
    start_hour: int,
    end_hour: int,
    step_min: int,
) -> None:
    """
    Cria 'appointments' distribuídos entre os students para o professional,
    respeitando o unique constraint (professional_id, starts_at).
    """

    # util para distribuir alunos
    def pick_student(slot_idx: int) -> Student:
        return students[slot_idx % len(students)]

    today = _now_utc()
    slot_idx = 0
    for day in _business_days(today, days):
        # gera slots em BR, converte para UTC
        for t in _hour_range(start_hour, end_hour, step_min):
            start_br = datetime(
                day.astimezone(BR_TZ).year,
                day.astimezone(BR_TZ).month,
                day.astimezone(BR_TZ).day,
                t.hour,
                t.minute,
                tzinfo=BR_TZ,
            )
            start_utc = start_br.astimezone(UTC)
            end_utc = (start_br + timedelta(minutes=step_min)).astimezone(UTC)

            # verifica se já existe (unique: professional_id + starts_at)
            q = db.execute(
                select(Appointment).where(
                    Appointment.professional_id == getattr(prof, "id"),
                    Appointment.starts_at == start_utc,
                )
            )
            exists = q.scalar_one_or_none()
            if exists:
                continue

            # cria appointment (status SCHEDULED) com um aluno
            st = pick_student(slot_idx)
            slot_idx += 1

            ap = Appointment(
                student_id=getattr(st, "id"),
                professional_id=getattr(prof, "id"),
                service="Atendimento Pedagógico",  # ajuste se quiser variar
                location="Sala 1",  # opcional
                status=AppointmentStatus.SCHEDULED,
                starts_at=start_utc,
                ends_at=end_utc,
            )

            # se o modelo tiver campos extras, ajuste aqui com hasattr(...)
            db.add(ap)

        db.commit()  # commit por dia para não segurar transação gigante


def main():
    print("[seed] Iniciando seed…")
    db = get_session()

    # 1) Profissional
    prof = ensure_professional(db)

    # 2) 10 responsáveis + alunos
    students = ensure_students_with_guardians(db)

    # 3) Grade de horários -> cria appointments SCHEDULED
    ensure_appointments_grid(
        db,
        prof=prof,
        students=students,
        days=SEED_BUSINESS_DAYS,
        start_hour=SEED_START_HOUR,
        end_hour=SEED_END_HOUR,
        step_min=SEED_STEP_MIN,
    )

    print("[seed] Concluído!")


if __name__ == "__main__":
    main()
