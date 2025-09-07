from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel

from app.models.appointment import AppointmentStatus


class CoordSummary(BaseModel):
    window_start_local: date
    window_end_local: date  # exclusivo (start + 7 dias padrão)
    timezone: str

    total_appointments: int
    count_by_status: dict[AppointmentStatus, int]
    cancel_rate: float  # 0..1

    professionals_active: int  # distintos com appt na janela
    families_active: int  # distintos com appt na janela

    today_upcoming: (
        int  # na TZ local, start >= hoje 00:00 e < 24:00 e status != CANCELLED
    )


class CoordSeriesDay(BaseModel):
    date_local: date
    count_total: int
    count_by_status: dict[AppointmentStatus, int]


class CoordTopProfessional(BaseModel):
    professional_id: int
    professional_name: str | None = None
    count: int


class CoordTopService(BaseModel):
    service: str
    count: int


class CoordRecentAppt(BaseModel):
    id: int
    service: str
    status: AppointmentStatus
    start_at_utc: datetime
    start_at_local: datetime
    professional_id: int
    professional_name: str | None = None
    student_id: int
    student_name: str | None = None


class CoordOverviewResponse(BaseModel):
    summary: CoordSummary
    series_daily: list[CoordSeriesDay]
    top_professionals: list[CoordTopProfessional]
    top_services: list[CoordTopService]
    recent: list[CoordRecentAppt]
