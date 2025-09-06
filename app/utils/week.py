from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

DEFAULT_TZ = ZoneInfo("America/Sao_Paulo")


def monday_of_week(d: date, tz: ZoneInfo = DEFAULT_TZ) -> datetime:
    """Retorna o início (00:00) da segunda-feira da semana de d, na TZ dada."""
    # convert date->local midnight
    local_dt = datetime.combine(d, time.min).replace(tzinfo=tz)
    weekday = local_dt.weekday()  # Monday=0 .. Sunday=6
    start_local = local_dt - timedelta(days=weekday)
    return start_local


def week_bounds_local(d: date, tz: ZoneInfo = DEFAULT_TZ) -> tuple[datetime, datetime]:
    start_local = monday_of_week(d, tz)
    end_local = start_local + timedelta(days=7)
    return start_local, end_local
