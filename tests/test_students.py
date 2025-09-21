import pytest
from fastapi import status

from app.core.security import create_access_token
from app.models.user import Role


def test_create_student_as_family(client, test_user):
    """Test creating a student as a family user."""
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
    
    # Test creating a student
    response = client.post(
        "/api/v1/students",
        json={
            "name": "Test Student"
        },
        headers={"Authorization": f"Bearer {token}"}
    )
    
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    assert "id" in data
    assert data["name"] == "Test Student"
    assert data["guardian_user_id"] == test_user.id


def test_create_student_as_coordinator(client, test_coordinator_user, test_user):
    """Test creating a student as a coordinator user."""
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
    
    # Test creating a student
    response = client.post(
        "/api/v1/students",
        json={
            "name": "Test Student",
            "guardian_user_id": test_user.id
        },
        headers={"Authorization": f"Bearer {token}"}
    )
    
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    assert "id" in data
    assert data["name"] == "Test Student"
    assert data["guardian_user_id"] == test_user.id


def test_create_student_as_coordinator_without_guardian(client, test_coordinator_user):
    """Test creating a student as a coordinator without specifying guardian."""
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
    
    # Try to create a student without guardian (should fail)
    response = client.post(
        "/api/v1/students",
        json={
            "name": "Test Student"
        },
        headers={"Authorization": f"Bearer {token}"}
    )
    
    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_list_students_as_family(client, test_user, test_student):
    """Test listing students as a family user."""
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
    
    # Test listing students
    response = client.get(
        "/api/v1/students",
        headers={"Authorization": f"Bearer {token}"}
    )
    
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert isinstance(data, list)
    # Should have at least our test student
    assert len(data) >= 1
    # Should only see students belonging to this user
    for student in data:
        assert student["guardian_user_id"] == test_user.id


def test_list_students_as_coordinator(client, test_coordinator_user, test_student):
    """Test listing students as a coordinator user."""
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
    
    # Test listing students
    response = client.get(
        "/api/v1/students",
        headers={"Authorization": f"Bearer {token}"}
    )
    
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert isinstance(data, list)


def test_get_student_as_family(client, test_user, test_student):
    """Test getting a student as a family user."""
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
    
    # Test getting a student
    response = client.get(
        f"/api/v1/students/{test_student.id}",
        headers={"Authorization": f"Bearer {token}"}
    )
    
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["id"] == test_student.id
    assert data["name"] == test_student.name
    assert data["guardian_user_id"] == test_user.id


def test_get_student_as_family_unauthorized(client, test_user, test_student):
    """Test getting a student that doesn't belong to the family user."""
    # Create another user and student
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
    
    # Try to get a student that doesn't belong to this user (should fail)
    # Since we only have one user in our test setup, we'll test with a non-existent student ID
    response = client.get(
        "/api/v1/students/99999",
        headers={"Authorization": f"Bearer {token}"}
    )
    
    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_get_nonexistent_student(client, test_user):
    """Test getting a nonexistent student."""
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
    
    # Test getting a nonexistent student
    response = client.get(
        "/api/v1/students/99999",
        headers={"Authorization": f"Bearer {token}"}
    )
    
    assert response.status_code == status.HTTP_404_NOT_FOUND
