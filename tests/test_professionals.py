import pytest
from fastapi import status

from app.core.security import create_access_token
from app.models.user import Role


def test_create_professional(client, test_coordinator_user):
    """Test creating a professional."""
    # Login as coordinator to get token
    login_response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "coordinator@example.com",
            "password": "TestPass123!"
        }
    )
    assert login_response.status_code == status.HTTP_200_OK
    token = login_response.json()["access_token"]
    
    # Test creating a professional
    response = client.post(
        "/api/v1/professionals",
        json={
            "name": "Dr. Smith",
            "speciality": "Pediatrics",
            "is_active": True
        },
        headers={"Authorization": f"Bearer {token}"}
    )
    
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    assert "id" in data
    assert data["name"] == "Dr. Smith"
    assert data["speciality"] == "Pediatrics"
    assert data["is_active"] is True


def test_create_professional_unauthorized(client, test_user):
    """Test creating a professional without proper authorization."""
    # Login as regular user to get token
    login_response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "test@example.com",
            "password": "TestPass123!"
        }
    )
    assert login_response.status_code == status.HTTP_200_OK
    token = login_response.json()["access_token"]
    
    # Try to create a professional (should fail)
    response = client.post(
        "/api/v1/professionals",
        json={
            "name": "Dr. Smith",
            "speciality": "Pediatrics",
            "is_active": True
        },
        headers={"Authorization": f"Bearer {token}"}
    )
    
    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_list_professionals(client, test_professional, test_user):
    """Test listing professionals."""
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
    
    # Test listing professionals
    response = client.get(
        "/api/v1/professionals",
        headers={"Authorization": f"Bearer {token}"}
    )
    
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert isinstance(data, list)
    # Should have at least our test professional
    assert len(data) >= 1


def test_get_professional(client, test_professional, test_user):
    """Test getting a specific professional."""
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
    
    # Test getting a professional
    response = client.get(
        f"/api/v1/professionals/{test_professional.id}",
        headers={"Authorization": f"Bearer {token}"}
    )
    
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["id"] == test_professional.id
    assert data["name"] == test_professional.name
    assert data["speciality"] == test_professional.speciality


def test_get_nonexistent_professional(client, test_user):
    """Test getting a nonexistent professional."""
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
    
    # Test getting a nonexistent professional
    response = client.get(
        "/api/v1/professionals/99999",
        headers={"Authorization": f"Bearer {token}"}
    )
    
    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_link_user_to_professional(client, test_coordinator_user, test_professional_user, test_professional):
    """Test linking a user to a professional."""
    # Login as coordinator to get token
    login_response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "coordinator@example.com",
            "password": "TestPass123!"
        }
    )
    assert login_response.status_code == status.HTTP_200_OK
    token = login_response.json()["access_token"]
    
    # Test linking user to professional
    response = client.put(
        f"/api/v1/professionals/{test_professional.id}/link-user/{test_professional_user.id}",
        headers={"Authorization": f"Bearer {token}"}
    )
    
    assert response.status_code == status.HTTP_204_NO_CONTENT


def test_link_user_to_professional_unauthorized(client, test_user, test_professional_user, test_professional):
    """Test linking a user to a professional without proper authorization."""
    # Login as regular user to get token
    login_response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "test@example.com",
            "password": "TestPass123!"
        }
    )
    assert login_response.status_code == status.HTTP_200_OK
    token = login_response.json()["access_token"]
    
    # Try to link user to professional (should fail)
    response = client.put(
        f"/api/v1/professionals/{test_professional.id}/link-user/{test_professional_user.id}",
        headers={"Authorization": f"Bearer {token}"}
    )
    
    assert response.status_code == status.HTTP_403_FORBIDDEN