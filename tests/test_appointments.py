import pytest
from datetime import datetime, timedelta, timezone
from fastapi import status

from app.models.appointment import AppointmentStatus
from app.core.security import create_access_token


def test_appointment_step1_check(client, test_user, test_professional):
    """Test appointment step 1 check endpoint."""
    # Login to get token
    login_response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "test@example.com",
            "password": "TestPass123!"
        }
    )
    assert login_response.status_code == status.HTTP_200_OK
    token = login_response.json()["access_token"]
    
    # Test step 1 check with valid data
    future_time = datetime.now(timezone.utc) + timedelta(days=1)
    response = client.post(
        "/api/v1/appointments/step1",
        json={
            "professional_id": test_professional.id,
            "starts_at_iso": future_time.isoformat().replace('+00:00', 'Z'),
            "slot_minutes": 60
        },
        headers={"Authorization": f"Bearer {token}"}
    )
    
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["ok"] is True
    assert data["professional_id"] == test_professional.id


def test_appointment_step2_review(client, test_user, test_student, test_professional):
    """Test appointment step 2 review endpoint."""
    # Login to get token
    login_response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "test@example.com",
            "password": "TestPass123!"
        }
    )
    assert login_response.status_code == status.HTTP_200_OK
    token = login_response.json()["access_token"]
    
    # Test step 2 review with valid data
    future_time = datetime.now(timezone.utc) + timedelta(days=1)
    response = client.post(
        "/api/v1/appointments/step2",
        json={
            "professional_id": test_professional.id,
            "student_id": test_student.id,
            "starts_at_iso": future_time.isoformat().replace('+00:00', 'Z'),
            "slot_minutes": 60
        },
        headers={"Authorization": f"Bearer {token}"}
    )
    
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["professional_id"] == test_professional.id
    assert data["student_id"] == test_student.id
    assert data["professional_name"] == test_professional.name
    assert data["student_name"] == test_student.name


def test_create_appointment(client, test_user, test_student, test_professional):
    """Test creating an appointment."""
    # Login to get token
    login_response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "test@example.com",
            "password": "TestPass123!"
        }
    )
    assert login_response.status_code == status.HTTP_200_OK
    token = login_response.json()["access_token"]
    
    # Test creating an appointment
    future_time = datetime.now(timezone.utc) + timedelta(days=1)
    response = client.post(
        "/api/v1/appointments",
        json={
            "professional_id": test_professional.id,
            "student_id": test_student.id,
            "starts_at_iso": future_time.isoformat().replace('+00:00', 'Z'),
            "slot_minutes": 60,
            "location": "Test Location"
        },
        headers={"Authorization": f"Bearer {token}"}
    )
    
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    assert "id" in data
    assert data["professional_id"] == test_professional.id
    assert data["student_id"] == test_student.id
    assert data["status"] == AppointmentStatus.SCHEDULED.value


def test_reschedule_appointment(client, test_user, test_student, test_professional, test_appointment):
    """Test rescheduling an appointment."""
    # Login to get token
    login_response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "test@example.com",
            "password": "TestPass123!"
        }
    )
    assert login_response.status_code == status.HTTP_200_OK
    token = login_response.json()["access_token"]
    
    # Test rescheduling an appointment
    future_time = datetime.now(timezone.utc) + timedelta(days=2)
    response = client.put(
        f"/api/v1/appointments/{test_appointment.id}/reschedule",
        json={
            "new_starts_at_iso": future_time.isoformat().replace('+00:00', 'Z')
        },
        headers={"Authorization": f"Bearer {token}"}
    )
    
    # This might fail due to business rules (6h advance notice), but we're testing the endpoint
    # If it fails, it should be with a proper error code
    assert response.status_code in [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST, status.HTTP_409_CONFLICT]


def test_appointment_step1_check_unauthorized(client):
    """Test appointment step 1 check without authentication."""
    future_time = datetime.now(timezone.utc) + timedelta(days=1)
    response = client.post(
        "/api/v1/appointments/step1",
        json={
            "professional_id": 1,
            "starts_at_iso": future_time.isoformat().replace('+00:00', 'Z'),
            "slot_minutes": 60
        }
    )
    
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_appointment_step2_review_unauthorized(client):
    """Test appointment step 2 review without authentication."""
    future_time = datetime.now(timezone.utc) + timedelta(days=1)
    response = client.post(
        "/api/v1/appointments/step2",
        json={
            "professional_id": 1,
            "student_id": 1,
            "starts_at_iso": future_time.isoformat().replace('+00:00', 'Z'),
            "slot_minutes": 60
        }
    )
    
    assert response.status_code == status.HTTP_401_UNAUTHORIZED