import pytest
from datetime import timedelta

from app.core.security import (
    hash_password,
    verify_password,
    validate_password_policy,
    create_access_token,
    create_refresh_token,
    decode_token,
)
from app.core.settings import settings


def test_password_hashing():
    """Test password hashing and verification."""
    password = "TestPass123!"
    hashed = hash_password(password)
    
    # Verify the hashed password matches the original
    assert verify_password(password, hashed) is True
    
    # Verify an incorrect password doesn't match
    assert verify_password("WrongPassword", hashed) is False


def test_password_policy_valid():
    """Test that valid passwords pass the policy."""
    valid_passwords = [
        "TestPass123!",
        "MySecurePassword1@",
        "Password123#",
        "StrongPass!2023"
    ]
    
    for password in valid_passwords:
        # Should not raise an exception
        validate_password_policy(password)


def test_password_policy_invalid():
    """Test that invalid passwords fail the policy."""
    invalid_passwords = [
        "short",           # too short
        "nouppercase1!",   # no uppercase
        "NOLOWERCASE1!",   # no lowercase
        "NoDigits!",       # no digits
        "NoSpecialChars1", # no special characters
        "NoSpecial1",      # no special characters
        "ALLUPPERCASE1!",  # no lowercase
        "alllowercase1!",  # no uppercase
    ]
    
    for password in invalid_passwords:
        with pytest.raises(ValueError):
            validate_password_policy(password)


def test_create_access_token():
    """Test creating an access token."""
    user_id = "123"
    token = create_access_token(user_id)
    
    assert isinstance(token, str)
    assert len(token) > 0


def test_create_refresh_token():
    """Test creating a refresh token."""
    user_id = "123"
    token = create_refresh_token(user_id)
    
    assert isinstance(token, str)
    assert len(token) > 0


def test_decode_valid_access_token():
    """Test decoding a valid access token."""
    user_id = "123"
    token = create_access_token(user_id)
    payload = decode_token(token, "access")
    
    assert payload["sub"] == user_id
    assert payload["type"] == "access"


def test_decode_valid_refresh_token():
    """Test decoding a valid refresh token."""
    user_id = "123"
    token = create_refresh_token(user_id)
    payload = decode_token(token, "refresh")
    
    assert payload["sub"] == user_id
    assert payload["type"] == "refresh"


def test_decode_invalid_token_type():
    """Test decoding a token with wrong expected type."""
    user_id = "123"
    token = create_access_token(user_id)
    
    with pytest.raises(ValueError):
        decode_token(token, "refresh")


def test_decode_invalid_token():
    """Test decoding an invalid token."""
    invalid_token = "invalid.token.string"
    
    with pytest.raises(ValueError):
        decode_token(invalid_token, "access")