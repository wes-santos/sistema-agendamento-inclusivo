import pytest
from fastapi import status
from sqlalchemy.orm import Session

from app.models.user import User
from app.core.security import hash_password


def test_login_success(client, test_user):
    """Test successful user login."""
    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "test@example.com",
            "password": "TestPass123!"
        }
    )
    
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"


def test_login_invalid_credentials(client):
    """Test login with invalid credentials."""
    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "test@example.com",
            "password": "wrongpassword"
        }
    )
    
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    data = response.json()
    assert "detail" in data
    assert data["detail"] == "Credenciais inválidas"


def test_login_nonexistent_user(client):
    """Test login with nonexistent user."""
    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "nonexistent@example.com",
            "password": "password"
        }
    )
    
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    data = response.json()
    assert "detail" in data
    assert data["detail"] == "Credenciais inválidas"


def test_login_inactive_user(client, db_session: Session):
    """Test login with inactive user."""
    # Create an inactive user
    inactive_user = User(
        name="Inactive User",
        email="inactive@example.com",
        password_hash=hash_password("TestPass123!"),
        role="FAMILY",
        is_active=False
    )
    db_session.add(inactive_user)
    db_session.commit()
    
    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "inactive@example.com",
            "password": "TestPass123!"
        }
    )
    
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    data = response.json()
    assert "detail" in data
    assert data["detail"] == "Credenciais inválidas"


def test_me_endpoint_authenticated(client, test_user):
    """Test /me endpoint with valid authentication."""
    # First login to get a token
    login_response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "test@example.com",
            "password": "TestPass123!"
        }
    )
    assert login_response.status_code == status.HTTP_200_OK
    token = login_response.json()["access_token"]
    
    # Test /me endpoint
    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"}
    )
    
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["id"] == test_user.id
    assert data["email"] == "test@example.com"
    assert data["name"] == "Test User"
    assert data["role"] == "FAMILY"
    assert data["is_active"] is True


def test_me_endpoint_unauthenticated(client):
    """Test /me endpoint without authentication."""
    response = client.get("/api/v1/auth/me")
    
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_logout(client):
    """Test logout endpoint."""
    response = client.post("/api/v1/auth/logout")
    
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data == {"ok": True}


def test_refresh_token(client, test_user):
    """Test refresh token endpoint."""
    # First login to get tokens
    login_response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "test@example.com",
            "password": "TestPass123!"
        }
    )
    assert login_response.status_code == status.HTTP_200_OK
    refresh_token = login_response.json()["refresh_token"]
    
    # Test refresh endpoint
    response = client.post(
        "/api/v1/auth/refresh",
        headers={"Authorization": f"Bearer {refresh_token}"}
    )
    
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"


def test_refresh_token_missing(client):
    """Test refresh token endpoint without token."""
    response = client.post("/api/v1/auth/refresh")
    
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    data = response.json()
    assert "detail" in data
    assert data["detail"] == "Refresh token ausente"


def test_refresh_token_invalid(client):
    """Test refresh token endpoint with invalid token."""
    response = client.post(
        "/api/v1/auth/refresh",
        headers={"Authorization": "Bearer invalidtoken"}
    )
    
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    data = response.json()
    assert "detail" in data
    assert data["detail"] == "Refresh token inválido"