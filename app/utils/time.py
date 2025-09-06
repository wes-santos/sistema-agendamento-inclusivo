from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

SAO_PAULO = ZoneInfo("America/Sao_Paulo")


def to_local(dt_utc: datetime, tz: ZoneInfo = SAO_PAULO) -> datetime:
    if dt_utc is None:
        return None
    # assume dt_utc timezone-aware (UTC). Se vier naive, trate aqui conforme seu padrão.
    return dt_utc.astimezone(tz)
