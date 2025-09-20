# scripts/seed.py
from __future__ import annotations

import os
import random
import zoneinfo
from collections.abc import Iterable
from datetime import UTC, datetime, time, timedelta

from sqlalchemy import select, text
from sqlalchemy.orm import Session
from sqlalchemy.exc import ProgrammingError

# --- Ajuste conforme seu projeto ---
# get_db é um generator do FastAPI; aqui usamos next(get_db()) pra obter uma Session
from app.core.security import hash_password
from app.db import get_db
from app.models.appointment import Appointment, AppointmentStatus
from app.models.availability import Availability
from app.models.professional import Professional
from app.models.student import Student
from app.models.user import Role, User

# ---------------- Configuráveis por ENV ----------------
BR_TZ = zoneinfo.ZoneInfo(os.getenv("SEED_TZ", "America/Sao_Paulo"))
SEED_BUSINESS_DAYS = int(os.getenv("SEED_DAYS", "10"))
SEED_PASSWORD = os.getenv("SEED_PASSWORD", "secret")

# ---------------- Dados de Exemplo ----------------
PROFESSIONALS_DATA = [
    {"name": "Dra. Ana Souza", "speciality": "Psicopedagogia"},
    {"name": "Dr. Bruno Lima", "speciality": "Fonoaudiologia"},
    {"name": "Dra. Carla Dias", "speciality": "Terapia Ocupacional"},
]

GUARDIANS_DATA = [
    "Marcos Lima",
    "Patrícia Alves",
    "Roberta Dias",
    "Carlos Nogueira",
    "Fernanda Pires",
]

STUDENTS_DATA = [
    "Alice Lima",
    "Bruno Alves",
    "Clara Dias",
    "Diego Nogueira",
    "Eduarda Pires",
]


# ---------------- Helpers ----------------
def _now_utc() -> datetime:
    return datetime.now(UTC)


def _get_password_hash(password: str = SEED_PASSWORD) -> str:
    # Em um projeto real, a senha NUNCA deveria ser fixa.
    # Para seed, usamos uma senha padrão para facilitar testes.
    return hash_password(password)


def get_session() -> Session:
    gen = get_db()
    session: Session = next(gen)
    return session


def _business_days(start_utc: datetime, n_days: int) -> Iterable[datetime]:
    d = start_utc.astimezone(BR_TZ).date()
    count = 0
    while count < n_days:
        if d.weekday() < 5:  # 0=Mon ... 6=Sun
            # Create datetime in BR_TZ and convert to UTC
            dt_br = datetime(d.year, d.month, d.day, tzinfo=BR_TZ)
            yield dt_br.astimezone(UTC)
        d += timedelta(days=1)
        count += 1


# ---------------- Funções de Seed ----------------
def ensure_user(
    db: Session, *, name: str, email: str, role: Role, password: str
) -> User:
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if user:
        return user

    user = User(
        name=name,
        email=email,
        role=role,
        password_hash=_get_password_hash(password),
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    print(f"[Seed] User criado: {user.name} ({user.email}) - Role: {user.role.value}")
    return user


def ensure_coordination_user(db: Session) -> User:
    return ensure_user(
        db,
        name="Coordenação",
        email="coordenacao@example.com",
        role=Role.COORDINATION,
        password=SEED_PASSWORD,
    )


def ensure_professionals(db: Session) -> list[Professional]:
    professionals = []
    for i, prof_data in enumerate(PROFESSIONALS_DATA):
        email = f"prof{i + 1}@example.com"
        user = ensure_user(
            db,
            name=prof_data["name"],
            email=email,
            role=Role.PROFESSIONAL,
            password=SEED_PASSWORD,
        )

        professional = db.execute(
            select(Professional).where(Professional.user_id == user.id)
        ).scalar_one_or_none()

        if not professional:
            professional = Professional(
                name=prof_data["name"],
                speciality=prof_data["speciality"],
                user_id=user.id,
                is_active=True,
            )
            db.add(professional)
            db.commit()
            db.refresh(professional)
            print(f"[Seed] Professional criado: {professional.name}")
        elif professional.name != prof_data["name"] or professional.speciality != prof_data["speciality"]:
            # Update professional info if it changed
            professional.name = prof_data["name"]
            professional.speciality = prof_data["speciality"]
            db.commit()
            db.refresh(professional)
            print(f"[Seed] Professional atualizado: {professional.name}")
        professionals.append(professional)
    return professionals


def ensure_availability(db: Session, professionals: list[Professional]):
    # Ex: Seg/Qua/Sex das 9h às 12h, Ter/Qui das 14h às 17h (horário de Brasília)
    availability_slots = [
        # Manhã
        (0, time(9), time(12)),  # Segunda
        (2, time(9), time(12)),  # Quarta
        (4, time(9), time(12)),  # Sexta
        # Tarde
        (1, time(14), time(17)),  # Terça
        (3, time(14), time(17)),  # Quinta
    ]

    for prof in professionals:
        for weekday, start_br, end_br in availability_slots:
            # Create datetime objects with BR_TZ and convert to UTC
            today = datetime.now(BR_TZ).date()
            # Find the most recent date for this weekday
            days_ahead = weekday - today.weekday()
            if days_ahead <= 0:  # Target day already happened this week
                days_ahead += 7
            target_date = today + timedelta(days_ahead)
            
            # Create datetime in BR_TZ and convert to UTC
            start_dt_br = datetime.combine(target_date, start_br, tzinfo=BR_TZ)
            end_dt_br = datetime.combine(target_date, end_br, tzinfo=BR_TZ)
            
            start_utc = start_dt_br.astimezone(UTC).time()
            end_utc = end_dt_br.astimezone(UTC).time()

            existing = db.execute(
                select(Availability).where(
                    Availability.professional_id == prof.id,
                    Availability.weekday == weekday,
                    Availability.starts_utc == start_utc,
                )
            ).scalar_one_or_none()

            if not existing:
                avail = Availability(
                    professional_id=prof.id,
                    weekday=weekday,
                    starts_utc=start_utc,
                    ends_utc=end_utc,
                )
                db.add(avail)
    db.commit()
    print("[Seed] Janelas de disponibilidade criadas para os profissionais.")


def ensure_students_with_guardians(db: Session) -> list[Student]:
    students = []
    for i, (guardian_name, student_name) in enumerate(
        zip(GUARDIANS_DATA, STUDENTS_DATA)
    ):
        email = f"family{i + 1}@example.com"
        user = ensure_user(
            db,
            name=guardian_name,
            email=email,
            role=Role.FAMILY,
            password=SEED_PASSWORD,
        )

        student = db.execute(
            select(Student).where(Student.name == student_name)
        ).scalar_one_or_none()
        if not student:
            student = Student(name=student_name, guardian_user_id=user.id)
            db.add(student)
            db.commit()
            db.refresh(student)
            print(f"[Seed] Aluno criado: {student.name}")
        students.append(student)
    return students


def ensure_appointments(
    db: Session,
    professionals: list[Professional],
    students: list[Student],
    days_to_seed: int,
):
    print("[Seed] Gerando agendamentos...")
    today = _now_utc()
    total_appointments = 0

    for day in _business_days(today, days_to_seed):
        weekday = day.weekday()

        for prof in professionals:
            availabilities = db.execute(
                select(Availability).where(
                    Availability.professional_id == prof.id,
                    Availability.weekday == weekday,
                )
            ).scalars()

            for avail in availabilities:
                start_utc = datetime.combine(day.date(), avail.starts_utc, tzinfo=UTC)
                end_utc = start_utc + timedelta(hours=1)  # Slots de 1h

                # Verifica se já existe um agendamento para este slot
                if db.execute(
                    select(Appointment).where(
                        Appointment.professional_id == prof.id,
                        Appointment.starts_at == start_utc,
                    )
                ).scalar_one_or_none():
                    continue

                # Cria agendamento com ~70% de chance
                if random.random() > 0.3:
                    student = random.choice(students)
                    status = random.choice(
                        [
                            AppointmentStatus.SCHEDULED,
                            AppointmentStatus.CONFIRMED,
                            AppointmentStatus.DONE,
                            AppointmentStatus.CANCELLED,
                        ]
                    )

                    appointment = Appointment(
                        professional_id=prof.id,
                        student_id=student.id,
                        starts_at=start_utc,
                        ends_at=end_utc,
                        service=prof.speciality or "Atendimento",
                        status=status,
                        confirmed_at=(
                            _now_utc()
                            if status == AppointmentStatus.CONFIRMED
                            else None
                        ),
                        cancellation_reason=(
                            "Cancelado via seed"
                            if status == AppointmentStatus.CANCELLED
                            else None
                        ),
                    )
                    db.add(appointment)
                    total_appointments += 1
    db.commit()
    print(f"[Seed] {total_appointments} agendamentos criados.")


def check_tables_exist(db: Session) -> bool:
    """Check if all required tables exist in the database."""
    required_tables = ["users", "professionals", "students", "availability", "appointments"]
    
    try:
        for table in required_tables:
            db.execute(text(f"SELECT 1 FROM {table} LIMIT 1"))
        return True
    except ProgrammingError as e:
        if "does not exist" in str(e):
            return False
        else:
            raise
    except Exception:
        # Any other exception means tables might exist but are empty
        return True


def main():
    print("[Seed] Iniciando seed do banco de dados...")
    db = None
    try:
        db = get_session()
        
        # Check if tables exist
        if not check_tables_exist(db):
            print("[Seed] Erro: As tabelas do banco de dados ainda não foram criadas.")
            print("[Seed] Instruções para resolver:")
            print("  1. Certifique-se de que o container do banco de dados está em execução:")
            print("     make up")
            print("  2. Execute as migrações do banco de dados:")
            print("     make migrate")
            print("  3. Depois execute o seed novamente:")
            print("     make seed")
            return

        # 1. Usuário de Coordenação
        ensure_coordination_user(db)

        # 2. Profissionais e seus usuários
        professionals = ensure_professionals(db)

        # 3. Disponibilidade dos profissionais
        ensure_availability(db, professionals)

        # 4. Responsáveis e Alunos
        students = ensure_students_with_guardians(db)

        # 5. Agendamentos
        ensure_appointments(db, professionals, students, SEED_BUSINESS_DAYS)

        print("\n[Seed] Concluído!")
        print("-------------------------------------------------")
        print("Usuários criados (senha padrão: 'secret'):")
        print("- coordenacao@example.com (Coordenação)")
        for i in range(len(PROFESSIONALS_DATA)):
            print(f"- prof{i + 1}@example.com (Profissional)")
        for i in range(len(GUARDIANS_DATA)):
            print(f"- family{i + 1}@example.com (Família)")
        print("-------------------------------------------------")
    except Exception as e:
        print(f"[Seed] Erro durante o seed: {e}")
        raise
    finally:
        if db:
            db.close()


if __name__ == "__main__":
    main()
