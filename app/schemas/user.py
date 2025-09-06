from __future__ import annotations

from pydantic import BaseModel, EmailStr

from app.models.user import Role


class UserOut(BaseModel):
    id: int
    email: EmailStr
    role: Role
    is_active: bool


class Config:
    from_attributes = True


class UserCreate(BaseModel):
    email: EmailStr
    password: str
    role: Role
