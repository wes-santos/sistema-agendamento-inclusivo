from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel

from app.models.appointment import AppointmentStatus


class ProApptItem(BaseModel):
    id: int
    family_id: int | None = None
    family_name: str | None = None  # se houver relationship/nome disponível
    service: str
    status: AppointmentStatus
    location: str | None = None
    start_at_utc: datetime
    end_at_utc: datetime
    start_at_local: datetime
    end_at_local: datetime


class ProDaySchedule(BaseModel):
    date_local: date  # YYYY-MM-DD (na TZ local)
    items: list[ProApptItem]


class ProWeekSummary(BaseModel):
    week_start_local: date
    week_end_local: date  # exclusivo (start + 7 dias)
    count_by_status: dict[AppointmentStatus, int]
    total_week: int


class ProWeekResponse(BaseModel):
    summary: ProWeekSummary
    days: list[
        ProDaySchedule
    ]  # sempre 7 posições (seg → dom), vazias quando não houver itens
