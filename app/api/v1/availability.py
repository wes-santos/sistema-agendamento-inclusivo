from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.audit.helpers import record_audit
from app.db import get_db
from app.deps import get_current_user, require_roles
from app.models.availability import Availability
from app.models.professional import Professional
from app.models.user import Role, User
from app.schemas.availability import (
    AvailabilityBulkIn,
    AvailabilityItemIn,
    AvailabilityOut,
    AvailabilitySetWeekIn,
)

router = APIRouter(prefix="/availability", tags=["availability"])

# ---------- helpers TZ/parse ----------

_REF_MONDAY = datetime(
    2025, 1, 6, tzinfo=ZoneInfo("UTC")
)  # segunda-feira (estável p/ cálculo)


def _time_local_to_utc_time_for_weekday(
    t_local: time, weekday: int, tz: ZoneInfo
) -> time:
    """
    Converte um horário local (HH:MM) para um horário UTC (HH:MM) 'representativo' para aquele weekday.
    Usamos uma segunda-feira de referência (_REF_MONDAY) + offset do weekday para fixar o offset da TZ.
    (No BR hoje não há DST; mesmo com DST, a referência mantém consistência semanal.)
    """
    base = _REF_MONDAY + timedelta(days=weekday)
    dt_local = datetime(
        base.year, base.month, base.day, t_local.hour, t_local.minute, tzinfo=tz
    )
    dt_utc = dt_local.astimezone(ZoneInfo("UTC"))
    return time(dt_utc.hour, dt_utc.minute)


def _time_to_str(t: time) -> str:
    return f"{t.hour:02d}:{t.minute:02d}"


def _str_to_time(s: str) -> time:
    h, m = map(int, s.split(":"))
    return time(h, m)


def _ensure_professional(db: Session, professional_id: int) -> Professional:
    p = db.get(Professional, professional_id)
    if not p:
        raise HTTPException(404, "Profissional não encontrado")
    if not p.is_active:
        raise HTTPException(400, "Profissional inativo")
    return p


def _check_overlap(
    existing: list[tuple[time, time]], new_start: time, new_end: time
) -> bool:
    # horários em UTC (time). Checa sobreposição no mesmo dia.
    for s, e in existing:
        if not (new_end <= s or new_start >= e):
            return True
    return False


def _list_day_windows(
    db: Session, professional_id: int, weekday: int
) -> list[tuple[time, time]]:
    rows: list[Availability] = (
        db.query(Availability)
        .filter(
            and_(
                Availability.professional_id == professional_id,
                Availability.weekday == weekday,
            )
        )
        .order_by(Availability.starts_utc.asc())
        .all()
    )
    return [(r.starts_utc, r.ends_utc) for r in rows]


# ---------- GET ----------


@router.get("", response_model=list[AvailabilityOut])
def list_availability(
    professional_id: int = Query(..., ge=1),
    tz_local: str = Query("America/Sao_Paulo"),
    db: Session = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    try:
        tz = ZoneInfo(tz_local)
    except Exception:
        raise HTTPException(400, "Timezone inválida")

    _ensure_professional(db, professional_id)
    rows: list[Availability] = (
        db.query(Availability)
        .filter(Availability.professional_id == professional_id)
        .order_by(Availability.weekday.asc(), Availability.starts_utc.asc())
        .all()
    )
    out: list[AvailabilityOut] = []
    for r in rows:
        # converter HH:MM (UTC) de volta para local para exibir
        base = _REF_MONDAY + timedelta(days=r.weekday)
        dt_start = datetime(
            base.year,
            base.month,
            base.day,
            r.starts_utc.hour,
            r.starts_utc.minute,
            tzinfo=ZoneInfo("UTC"),
        ).astimezone(tz)
        dt_end = datetime(
            base.year,
            base.month,
            base.day,
            r.ends_utc.hour,
            r.ends_utc.minute,
            tzinfo=ZoneInfo("UTC"),
        ).astimezone(tz)
        out.append(
            AvailabilityOut(
                professional_id=r.professional_id,
                weekday=r.weekday,
                start_utc=_time_to_str(r.starts_utc),
                end_utc=_time_to_str(r.ends_utc),
                start_local=_time_to_str(dt_start.timetz()),
                end_local=_time_to_str(dt_end.timetz()),
                tz_local=tz.key,
            )
        )
    return out


# ---------- POST (uma janela) ----------


@router.post("", response_model=AvailabilityOut, status_code=201)
def create_availability(
    payload: AvailabilityItemIn,
    request: Request,
    db: Session = Depends(get_db),
    current_user: Annotated[User, Depends(require_roles(Role.COORDINATION))] = None,
):
    tz = ZoneInfo(payload.tz_local)
    _ensure_professional(db, payload.professional_id)

    start_local = _str_to_time(payload.start)
    end_local = _str_to_time(payload.end)

    start_utc_t = _time_local_to_utc_time_for_weekday(start_local, payload.weekday, tz)
    end_utc_t = _time_local_to_utc_time_for_weekday(end_local, payload.weekday, tz)
    if end_utc_t <= start_utc_t:
        raise HTTPException(400, "Janela inválida após conversão para UTC")

    existing = _list_day_windows(db, payload.professional_id, payload.weekday)
    if _check_overlap(existing, start_utc_t, end_utc_t):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Sobreposição com janela existente"
        )

    row = Availability(
        professional_id=payload.professional_id,
        weekday=payload.weekday,
        starts_utc=start_utc_t,
        ends_utc=end_utc_t,
    )
    db.add(row)
    db.flush()
    record_audit(
        db,
        request=request,
        user_id=current_user.id,
        action="CREATE",
        entity="availability",
        entity_id=None,
    )
    db.commit()
    db.refresh(row)

    return AvailabilityOut(
        professional_id=row.professional_id,
        weekday=row.weekday,
        start_utc=_time_to_str(row.starts_utc),
        end_utc=_time_to_str(row.ends_utc),
        start_local=payload.start,
        end_local=payload.end,
        tz_local=payload.tz_local,
    )


# ---------- POST /bulk (várias janelas) ----------


@router.post("/bulk", response_model=list[AvailabilityOut], status_code=201)
def create_availability_bulk(
    payload: AvailabilityBulkIn,
    request: Request,
    db: Session = Depends(get_db),
    current_user: Annotated[User, Depends(require_roles(Role.COORDINATION))] = None,
):
    if not payload.items:
        return []

    # validar todos os itens antes
    tz_cache: dict[str, ZoneInfo] = {}

    def tz_of(tzname: str) -> ZoneInfo:
        if tzname not in tz_cache:
            tz_cache[tzname] = ZoneInfo(tzname)
        return tz_cache[tzname]

    # group by (professional_id, weekday)
    grouped: dict[tuple[int, int], list[tuple[time, time, str, str, str]]] = {}
    for it in payload.items:
        tz = tz_of(it.tz_local)
        _ensure_professional(db, it.professional_id)
        s_loc = _str_to_time(it.start)
        e_loc = _str_to_time(it.end)
        s_utc = _time_local_to_utc_time_for_weekday(s_loc, it.weekday, tz)
        e_utc = _time_local_to_utc_time_for_weekday(e_loc, it.weekday, tz)
        if e_utc <= s_utc:
            raise HTTPException(
                400, f"Janela inválida (weekday={it.weekday} {it.start}-{it.end})"
            )
        grouped.setdefault((it.professional_id, it.weekday), []).append(
            (s_utc, e_utc, it.start, it.end, it.tz_local)
        )

    # se replace=True, apaga existentes dos weekdays envolvidos
    if payload.replace:
        for pid, wd in grouped.keys():
            db.query(Availability).filter(
                and_(Availability.professional_id == pid, Availability.weekday == wd)
            ).delete()

    # checar overlap interno e contra existentes
    out: list[AvailabilityOut] = []
    for (pid, wd), windows in grouped.items():
        # ordena por início
        windows.sort(key=lambda x: (x[0].hour, x[0].minute))
        # overlap dentro do batch
        for i in range(1, len(windows)):
            prev_s, prev_e = windows[i - 1][0], windows[i - 1][1]
            cur_s, cur_e = windows[i][0], windows[i][1]
            if not (cur_s >= prev_e):
                raise HTTPException(409, f"Sobreposição no payload (weekday={wd})")

        # overlap com banco
        existing = _list_day_windows(db, pid, wd)
        for s_utc, e_utc, s_loc, e_loc, tzname in windows:
            if _check_overlap(existing, s_utc, e_utc):
                raise HTTPException(
                    409, f"Sobreposição com janela existente (weekday={wd})"
                )

        # inserir
        for s_utc, e_utc, s_loc, e_loc, tzname in windows:
            row = Availability(
                professional_id=pid, weekday=wd, starts_utc=s_utc, ends_utc=e_utc
            )
            db.add(row)
            out.append(
                AvailabilityOut(
                    professional_id=pid,
                    weekday=wd,
                    start_utc=_time_to_str(s_utc),
                    end_utc=_time_to_str(e_utc),
                    start_local=s_loc,
                    end_local=e_loc,
                    tz_local=tzname,
                )
            )

    record_audit(
        db,
        request=request,
        user_id=current_user.id,
        action="BULK_CREATE",
        entity="availability",
        entity_id=None,
    )
    db.commit()
    return out


# ---------- PUT /set-week (substitui a semana do prof) ----------


@router.put("/set-week", response_model=list[AvailabilityOut])
def set_week(
    payload: AvailabilitySetWeekIn,
    request: Request,
    db: Session = Depends(get_db),
    current_user: Annotated[User, Depends(require_roles(Role.COORDINATION))] = None,
):
    tz = ZoneInfo(payload.tz_local)
    _ensure_professional(db, payload.professional_id)

    # remove tudo do profissional
    db.query(Availability).filter(
        Availability.professional_id == payload.professional_id
    ).delete()

    out: list[AvailabilityOut] = []
    # para cada weekday em 'week'
    for wd_str, lst in payload.week.items():
        weekday = int(wd_str)
        if weekday < 0 or weekday > 6:
            raise HTTPException(400, f"weekday inválido: {weekday}")
        # normalizar e checar overlaps
        win = []
        for item in lst:
            s = item["start"]
            e = item["end"]
            s_loc = _str_to_time(s)
            e_loc = _str_to_time(e)
            s_utc = _time_local_to_utc_time_for_weekday(s_loc, weekday, tz)
            e_utc = _time_local_to_utc_time_for_weekday(e_loc, weekday, tz)
            if e_utc <= s_utc:
                raise HTTPException(400, f"Janela inválida ({weekday} {s}-{e})")
            win.append((s_utc, e_utc, s, e))
        win.sort(key=lambda x: (x[0].hour, x[0].minute))
        for i in range(1, len(win)):
            if not (win[i][0] >= win[i - 1][1]):
                raise HTTPException(409, f"Sobreposição no dia {weekday}")

        # inserir
        for s_utc, e_utc, s, e in win:
            row = Availability(
                professional_id=payload.professional_id,
                weekday=weekday,
                starts_utc=s_utc,
                ends_utc=e_utc,
            )
            db.add(row)
            out.append(
                AvailabilityOut(
                    professional_id=payload.professional_id,
                    weekday=weekday,
                    start_utc=_time_to_str(s_utc),
                    end_utc=_time_to_str(e_utc),
                    start_local=s,
                    end_local=e,
                    tz_local=payload.tz_local,
                )
            )

    record_audit(
        db,
        request=request,
        user_id=current_user.id,
        action="REPLACE",
        entity="availability",
        entity_id=None,
    )
    db.commit()
    return out


# ---------- DELETE (uma janela) ----------


@router.delete("", status_code=204)
def delete_availability(
    professional_id: int = Query(..., ge=1),
    weekday: int = Query(..., ge=0, le=6),
    start: str = Query(
        ..., description="Start LOCAL HH:MM ou UTC HH:MM se tz_local='UTC'"
    ),
    tz_local: str = Query("America/Sao_Paulo"),
    request: Request = None,
    db: Session = Depends(get_db),
    current_user: Annotated[User, Depends(require_roles(Role.COORDINATION))] = None,
):
    tz = ZoneInfo(tz_local)
    s_loc = _str_to_time(start)
    s_utc = _time_local_to_utc_time_for_weekday(s_loc, weekday, tz)

    row = (
        db.query(Availability)
        .filter(
            and_(
                Availability.professional_id == professional_id,
                Availability.weekday == weekday,
                Availability.starts_utc == s_utc,
            )
        )
        .first()
    )
    if not row:
        raise HTTPException(404, "Janela não encontrada")

    db.delete(row)
    record_audit(
        db,
        request=request,
        user_id=current_user.id,
        action="DELETE",
        entity="availability",
        entity_id=None,
    )
    db.commit()
    return
