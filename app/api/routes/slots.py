from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.appointment import Appointment, AppointmentStatus
from app.models.availability import Availability

router = APIRouter(prefix="/slots", tags=["slots"])


def _overlaps(
    a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime
) -> bool:
    # intervalo [start, end) — fim exclusivo
    return not (a_end <= b_start or a_start >= b_end)


@router.get("")
def get_slots(
    professional_id: int = Query(..., ge=1),
    date_local: date = Query(..., alias="date"),  # data no fuso local
    slot_minutes: int = Query(30, ge=5, le=240),
    tz_local: str = Query("America/Sao_Paulo"),
    db: Session = Depends(get_db),
):
    """
    Devolve slots livres para 'professional_id' no dia 'date' (interpretação local),
    considerando availability (semanal, UTC) menos appointments (≠ CANCELLED).
    Resposta: apenas horários (UTC), sem dados sensíveis.
    """
    try:
        tz = ZoneInfo(tz_local)
    except Exception:
        raise HTTPException(400, detail="Timezone inválida") from Exception

    # Janela do DIA (local) -> UTC
    start_local = datetime.combine(date_local, datetime.min.time()).replace(tzinfo=tz)
    end_local = start_local + timedelta(days=1)
    start_utc = start_local.astimezone(ZoneInfo("UTC"))
    end_utc = end_local.astimezone(ZoneInfo("UTC"))

    # Availability do profissional (tudo; filtramos por weekday em UTC durante a geração)
    avails: list[Availability] = (
        db.query(Availability)
        .filter(Availability.professional_id == professional_id)
        .all()
    )
    by_weekday: dict[int, list[tuple]] = {}
    for a in avails:
        by_weekday.setdefault(a.weekday, []).append(
            (a.start_utc, a.end_utc)
        )  # times (UTC) daquele weekday

    # Appointments que colidem com a janela (exceto CANCELLED)
    appts = (
        db.query(Appointment)
        .filter(
            and_(
                Appointment.professional_id == professional_id,
                Appointment.starts_at < end_utc,
                Appointment.ends_at > start_utc,
                Appointment.status != AppointmentStatus.CANCELLED,
            )
        )
        .all()
    )
    busy = [(ap.starts_at_utc, ap.ends_at_utc) for ap in appts]

    # Geração de slots (em UTC), step = slot_minutes
    step = timedelta(minutes=slot_minutes)
    slots_utc: list[str] = []
    cur = start_utc
    while cur + step <= end_utc:
        wd = cur.weekday()  # 0=segunda ... 6=domingo (UTC)
        day_avails = by_weekday.get(wd, [])
        cur_t = cur.time()
        end_t = (cur + step).time()

        # 1) Cabe em alguma janela de availability do dia (UTC)?
        fits_avail = any(
            (cur_t >= a_start and end_t <= a_end) for (a_start, a_end) in day_avails
        )

        if fits_avail:
            # 2) Não colide com nenhum intervalo ocupado?
            collides = any(_overlaps(cur, cur + step, b0, b1) for (b0, b1) in busy)
            if not collides:
                # Serializa em ISO-8601 UTC com sufixo Z (sem micros)
                iso = (
                    cur.replace(microsecond=0, tzinfo=UTC)
                    .isoformat()
                    .replace("+00:00", "Z")
                )
                slots_utc.append(iso)

        cur += step

    return {
        "professional_id": professional_id,
        "date": date_local.isoformat(),
        "slot_minutes": slot_minutes,
        "timezone": "UTC",
        "slots": slots_utc,  # somente horários (UTC)
    }


@router.get("/local")
def get_slots_local(
    professional_id: int = Query(..., ge=1),
    date_local: date = Query(..., alias="date"),  # data interpretada na TZ local
    slot_minutes: int = Query(30, ge=5, le=240),
    tz_local: str = Query("America/Sao_Paulo"),
    db: Session = Depends(get_db),
):
    """
    Slots livres para 'professional_id' no dia 'date' (na TZ local),
    considerando availability (semanal, UTC) − appointments (≠ CANCELLED).

    Retorna os horários **em local-time** (HH:mm) e também em ISO local (com offset).
    Sem dados sensíveis.
    """
    # valida/resolve TZ
    try:
        tz = ZoneInfo(tz_local)
    except Exception:
        raise HTTPException(400, detail="Timezone inválida") from Exception

    # janela do dia (LOCAL) -> UTC
    start_local = datetime.combine(date_local, datetime.min.time()).replace(tzinfo=tz)
    end_local = start_local + timedelta(days=1)
    start_utc = start_local.astimezone(ZoneInfo("UTC"))
    end_utc = end_local.astimezone(ZoneInfo("UTC"))

    # availability do profissional (times em UTC por weekday)
    avails: list[Availability] = (
        db.query(Availability)
        .filter(Availability.professional_id == professional_id)
        .all()
    )
    by_weekday: dict[int, list[tuple]] = {}
    for a in avails:
        by_weekday.setdefault(a.weekday, []).append(
            (a.start_utc, a.end_utc)
        )  # time/time em UTC

    # compromissos que colidem com a janela (exceto CANCELLED)
    appts = (
        db.query(Appointment)
        .filter(
            and_(
                Appointment.professional_id == professional_id,
                Appointment.starts_at < end_utc,
                Appointment.ends_at > start_utc,
                Appointment.status != AppointmentStatus.CANCELLED,
            )
        )
        .all()
    )
    busy = [(ap.starts_at_utc, ap.ends_at_utc) for ap in appts]

    def overlaps(a0: datetime, a1: datetime, b0: datetime, b1: datetime) -> bool:
        # intervalo [start, end) — fim exclusivo
        return not (a1 <= b0 or a0 >= b1)

    # gerar slots (base em UTC) e converter para local
    step = timedelta(minutes=slot_minutes)
    slots_hhmm: list[str] = []
    slots_iso_local: list[str] = []

    cur = start_utc
    while cur + step <= end_utc:
        wd = cur.weekday()  # 0=segunda ... 6=domingo (UTC)
        day_avails = by_weekday.get(wd, [])
        cur_t = cur.time()
        end_t = (cur + step).time()

        fits_avail = any(
            (cur_t >= a_start and end_t <= a_end) for (a_start, a_end) in day_avails
        )
        if fits_avail:
            collides = any(overlaps(cur, cur + step, b0, b1) for (b0, b1) in busy)
            if not collides:
                loc = cur.astimezone(tz).replace(microsecond=0)
                slots_hhmm.append(loc.strftime("%H:%M"))
                slots_iso_local.append(loc.isoformat())

        cur += step

    return {
        "professional_id": professional_id,
        "date": date_local.isoformat(),
        "slot_minutes": slot_minutes,
        "timezone": tz_local,
        "slots": slots_hhmm,  # ex.: ["08:00","08:30",...]
        "slots_iso": slots_iso_local,  # ex.: ["2025-09-10T08:00:00-03:00", ...]
    }
