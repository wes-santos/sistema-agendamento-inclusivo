import pytest
from datetime import datetime, timedelta, timezone
from fastapi import status

from app.core.security import create_access_token
from app.models.user import Role
from app.models.appointment import AppointmentStatus


def test_list_family_dashboard_appointments(client, test_user, test_student, test_appointment):
    """Test listing appointments in the family dashboard."""
    # Login as family user to get token
    login_response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "test@example.com",
            "password": "TestPass123!"
        }
    )
    assert login_response.status_code == status.HTTP_200_OK
    token = login_response.json()["access_token"]
    
    # Test listing appointments
    response = client.get(
        "/api/v1/dashboard/student/appointments",
        headers={"Authorization": f"Bearer {token}"}
    )
    
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert "summary" in data
    assert "items" in data
    assert isinstance(data["items"], list)


def test_list_family_dashboard_appointments_upcoming(client, test_user, test_student, test_appointment):
    """Test listing upcoming appointments in the family dashboard."""
    # Login as family user to get token
    login_response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "test@example.com",
            "password": "TestPass123!"
        }
    )
    assert login_response.status_code == status.HTTP_200_OK
    token = login_response.json()["access_token"]
    
    # Test listing upcoming appointments
    response = client.get(
        "/api/v1/dashboard/student/appointments?range=upcoming",
        headers={"Authorization": f"Bearer {token}"}
    )
    
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert "summary" in data
    assert "items" in data


def test_list_family_dashboard_appointments_past(client, test_user, test_student, test_appointment):
    """Test listing past appointments in the family dashboard."""
    # Login as family user to get token
    login_response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "test@example.com",
            "password": "TestPass123!"
        }
    )
    assert login_response.status_code == status.HTTP_200_OK
    token = login_response.json()["access_token"]
    
    # Test listing past appointments
    response = client.get(
        "/api/v1/dashboard/student/appointments?range=past",
        headers={"Authorization": f"Bearer {token}"}
    )
    
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert "summary" in data
    assert "items" in data


def test_list_family_dashboard_appointments_with_status_filter(client, test_user, test_student, test_appointment):
    """Test listing appointments with status filter in the family dashboard."""
    # Login as family user to get token
    login_response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "test@example.com",
            "password": "TestPass123!"
        }
    )
    assert login_response.status_code == status.HTTP_200_OK
    token = login_response.json()["access_token"]
    
    # Test listing appointments with status filter
    response = client.get(
        "/api/v1/dashboard/student/appointments?status=SCHEDULED",
        headers={"Authorization": f"Bearer {token}"}
    )
    
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert "summary" in data
    assert "items" in data


def test_list_family_dashboard_appointments_unauthorized(client, test_professional_user):
    """Test accessing family dashboard as unauthorized user."""
    # Login as professional user to get token
    login_response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "professional@example.com",
            "password": "TestPass123!"
        }
    )
    assert login_response.status_code == status.HTTP_200_OK
    token = login_response.json()["access_token"]
    
    # Try to access family dashboard (should fail)
    response = client.get(
        "/api/v1/dashboard/student/appointments",
        headers={"Authorization": f"Bearer {token}"}
    )
    
    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_list_family_dashboard_appointments_date_filter(client, test_user, test_student, test_appointment):
    """Test listing appointments with date filters in the family dashboard."""
    # Login as family user to get token
    login_response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "test@example.com",
            "password": "TestPass123!"
        }
    )
    assert login_response.status_code == status.HTTP_200_OK
    token = login_response.json()["access_token"]
    
    # Test listing appointments with date filters
    now = datetime.now(timezone.utc)
    date_from = (now - timedelta(days=1)).isoformat().replace('+00:00', 'Z')
    date_to = (now + timedelta(days=1)).isoformat().replace('+00:00', 'Z')
    
    response = client.get(
        f"/api/v1/dashboard/student/appointments?date_from={date_from}&date_to={date_to}",
        headers={"Authorization": f"Bearer {token}"}
    )
    
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert "summary" in data
    assert "items" in data