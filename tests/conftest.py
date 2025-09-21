import sys
import os

# Add the current directory to Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base_class import Base
# Import all models to ensure their tables are created
from app.models.user import User, Role
from app.models.student import Student
from app.models.professional import Professional
from app.models.appointment import Appointment, AppointmentStatus
from app.models.availability import Availability
from app.core.security import hash_password


# Patch the audit_log module to use String instead of INET for SQLite compatibility
import app.models.audit_log
from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String as SQLString
from sqlalchemy.orm import Mapped, mapped_column, relationship

# Replace the AuditLog class with a SQLite-compatible version
# Create a new Base for testing to avoid conflicts with existing metadata
from sqlalchemy.orm import registry

# Create a new registry for testing
testing_registry = registry()

class MockAuditLog(testing_registry.generate_base()):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_timestamp_utc", "timestamp_utc"),
        Index("ix_audit_user_id", "user_id"),
        {'extend_existing': True}
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    action: Mapped[str] = mapped_column(
        SQLString(80), nullable=False
    )  # e.g. "CREATE","UPDATE","LOGIN"
    entity: Mapped[str] = mapped_column(
        SQLString(80), nullable=False
    )  # e.g. "appointment","student"
    entity_id: Mapped[int | None] = mapped_column(Integer)
    timestamp_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    ip: Mapped[str | None] = mapped_column(SQLString(45))  # Use String instead of INET

    user = relationship("User")

# Replace the AuditLog class in the module
app.models.audit_log.AuditLog = MockAuditLog


# Create an in-memory SQLite database for testing
@pytest.fixture(scope="session")
def engine():
    """Create an in-memory SQLite database for testing."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="session")
def TestingSessionLocal(engine):
    """Create a session factory for the test database."""
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


# Override the database dependency to use our test database
@pytest.fixture
def override_get_db(TestingSessionLocal):
    """Override the database dependency to use our test database."""
    def _override_get_db():
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()
    return _override_get_db


@pytest.fixture
def db_session(TestingSessionLocal):
    """Create a database session for each test."""
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(override_get_db):
    """Create a test client for API tests."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.db import get_db
    
    # Override the database dependency
    app.dependency_overrides[get_db] = override_get_db
    
    with TestClient(app) as client:
        yield client
    
    # Clear overrides after test
    app.dependency_overrides.clear()


@pytest.fixture
def test_user(db_session):
    """Create a test user for authentication tests."""
    user = User(
        name="Test User",
        email="test@example.com",
        password_hash=hash_password("TestPass123!"),
        role=Role.FAMILY,
        is_active=True
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def test_professional_user(db_session):
    """Create a test professional user."""
    user = User(
        name="Professional User",
        email="professional@example.com",
        password_hash=hash_password("TestPass123!"),
        role=Role.PROFESSIONAL,
        is_active=True
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def test_coordinator_user(db_session):
    """Create a test coordinator user."""
    user = User(
        name="Coordinator User",
        email="coordinator@example.com",
        password_hash=hash_password("TestPass123!"),
        role=Role.COORDINATION,
        is_active=True
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def test_student(db_session, test_user):
    """Create a test student."""
    student = Student(
        name="Test Student",
        guardian_user_id=test_user.id
    )
    db_session.add(student)
    db_session.commit()
    db_session.refresh(student)
    return student


@pytest.fixture
def test_professional(db_session, test_professional_user):
    """Create a test professional."""
    professional = Professional(
        name="Test Professional",
        speciality="Test Speciality",
        is_active=True,
        user_id=test_professional_user.id  # Link to the professional user
    )
    db_session.add(professional)
    db_session.commit()
    db_session.refresh(professional)
    return professional


@pytest.fixture
def test_appointment(db_session, test_student, test_professional):
    """Create a test appointment."""
    now = datetime.now(timezone.utc)
    appointment = Appointment(
        student_id=test_student.id,
        professional_id=test_professional.id,
        service="Test Service",
        starts_at=now,
        ends_at=now.replace(hour=now.hour + 1),
        status=AppointmentStatus.SCHEDULED
    )
    db_session.add(appointment)
    db_session.commit()
    db_session.refresh(appointment)
    return appointment