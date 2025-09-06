from __future__ import annotations

from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

BR_TZ = ZoneInfo("America/Sao_Paulo")
UTC = UTC


def ensure_aware_utc(dt: datetime) -> datetime:
    """
    Garante que dt é timezone-aware em UTC.
    - Se já vier aware: converte para UTC.
    - Se vier naive: ERRO (evita gravar errado).
    """
    if dt.tzinfo is None:
        raise ValueError(
            "Datetime naive recebido. Sempre use datetimes timezone-aware."
        )
    return dt.astimezone(UTC)


def to_utc(dt: datetime, tz: ZoneInfo | None = None) -> datetime:
    """
    Converte um datetime (naive ou aware) para UTC.
    - Naive: assume tz fornecida (padrão BR).
    - Aware: só converte para UTC.
    """
    tz = tz or BR_TZ
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt.astimezone(UTC)


def to_local(dt_utc: datetime, tz: ZoneInfo | None = None) -> datetime:
    """
    Converte um datetime UTC (aware) para TZ local (aware).
    """
    tz = tz or BR_TZ
    if dt_utc.tzinfo is None:
        raise ValueError("Esperava datetime UTC timezone-aware.")
    return dt_utc.astimezone(tz)


def combine_local_to_utc(d: date, t: time, tz: ZoneInfo | None = None) -> datetime:
    """
    Combina uma data+hora interpretadas na TZ local e retorna em UTC (aware).
    Útil para criar agendamentos a partir de inputs locais.
    """
    tz = tz or BR_TZ
    if t.tzinfo is not None:
        # se alguém passou um time aware, normalize para naive e use TZ alvo
        t = time(t.hour, t.minute, t.second, t.microsecond)
    local_dt = datetime.combine(d, t).replace(tzinfo=tz)
    return local_dt.astimezone(UTC)


def split_utc_to_local(dtu: datetime, tz: ZoneInfo | None = None) -> tuple[date, time]:
    """
    Quebra um datetime UTC em (data_local, hora_local) na TZ escolhida.
    Útil para exibir campos de formulário locais.
    """
    tz = tz or BR_TZ
    if dtu.tzinfo is None:
        raise ValueError("Esperava datetime UTC timezone-aware.")
    loc = dtu.astimezone(tz)
    return loc.date(), loc.timetz()  # time aware com tzinfo=tz


def iso_utc(dt: datetime) -> str:
    """
    Serializa em ISO 8601 sempre em UTC com sufixo 'Z'.
    """
    return ensure_aware_utc(dt).astimezone(UTC).isoformat().replace("+00:00", "Z")
