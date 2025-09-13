from __future__ import annotations

from pydantic import BaseModel, Field


class Step1CheckIn(BaseModel):
    professional_id: int = Field(..., ge=1)
    starts_at_iso: str = Field(..., description="ISO-8601; preferir UTC com sufixo Z")
    slot_minutes: int = Field(30, ge=5, le=240)


class Step1CheckOut(BaseModel):
    ok: bool
    professional_id: int
    starts_at: str
    ends_at: str
    slot_minutes: int
    reason: str | None = None  # quando ok=false


class Step2ReviewIn(BaseModel):
    professional_id: int = Field(..., ge=1)
    starts_at_iso: str
    slot_minutes: int = Field(30, ge=5, le=240)
    student_id: int = Field(..., ge=1)


class Step2ReviewOut(BaseModel):
    professional_id: int
    professional_name: str
    student_id: int
    student_name: str
    starts_at: str
    ends_at: str
    slot_minutes: int


class CreateAppointmentIn(BaseModel):
    professional_id: int = Field(..., ge=1)
    student_id: int = Field(..., ge=1)
    starts_at_iso: str
    slot_minutes: int = Field(30, ge=5, le=240)
    location: str | None = None


class AppointmentOut(BaseModel):
    id: int
    professional_id: int
    student_id: int
    starts_at: str
    ends_at: str
    status: str


class RescheduleIn(BaseModel):
    new_starts_at_iso: str = Field(
        ...,
        description="ISO-8601; preferir UTC com sufixo Z (ex.: 2025-09-15T13:00:00Z)",
    )
