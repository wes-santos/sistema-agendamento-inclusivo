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
from app.models.audit_log import AuditLog
from app.core.security import hash_password


# Create an in-memory SQLite database for testing
@pytest.fixture(scope="function")
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


@pytest.fixture(scope="function")
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
        original_post = client.post

        def post_with_allow_redirects(*args, **kwargs):
            if "allow_redirects" in kwargs and "follow_redirects" not in kwargs:
                kwargs["follow_redirects"] = kwargs.pop("allow_redirects")
            return original_post(*args, **kwargs)

        client.post = post_with_allow_redirects  # type: ignore[assignment]
        yield client
    
    # Clear overrides after test
    app.dependency_overrides.clear()


@pytest.fixture
def test_user(db_session):
    """Create a test user for authentication tests."""
    existing = db_session.query(User).filter_by(email="test@example.com").first()
    if existing:
        return existing

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
    existing = (
        db_session.query(User)
        .filter_by(email="professional@example.com")
        .first()
    )
    if existing:
        return existing

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
    existing = (
        db_session.query(User)
        .filter_by(email="coordinator@example.com")
        .first()
    )
    if existing:
        return existing

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
    professional = (
        db_session.query(Professional)
        .filter_by(user_id=test_professional_user.id)
        .first()
    )
    if professional:
        return professional

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
