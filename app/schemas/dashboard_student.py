from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.models.appointment import AppointmentStatus


class StudentApptItem(BaseModel):
    id: int
    service: str
    status: AppointmentStatus
    start_at_utc: datetime
    end_at_utc: datetime
    start_at_local: datetime | None = None
    end_at_local: datetime | None = None
    location: str | None = None
    professional_id: int | None = None
    professional_name: str | None = None


class StudentApptSummary(BaseModel):
    total_upcoming: int
    total_past: int
    total_cancelled: int
    next_appointment_start_utc: datetime | None = None
    next_appointment_service: str | None = None


class StudentApptResponse(BaseModel):
    summary: StudentApptSummary
    page: int
    page_size: int
    total_items: int
    items: list[StudentApptItem]
