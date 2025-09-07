from __future__ import annotations

from pydantic import BaseModel, Field, constr, model_validator

TimeStr = constr(pattern=r"^\d{2}:\d{2}$")  # "HH:MM"


class AvailabilityItemIn(BaseModel):
    professional_id: int = Field(..., ge=1)
    weekday: int = Field(..., ge=0, le=6, description="0=segunda ... 6=domingo")
    start: TimeStr  # type: ignore # local HH:MM (por padrão America/Sao_Paulo)
    end: TimeStr  # type: ignore
    tz_local: str = Field("America/Sao_Paulo")

    @model_validator(mode="after")
    def _check_times(self):
        sh, sm = map(int, self.start.split(":"))
        eh, em = map(int, self.end.split(":"))
        if (eh, em) <= (sh, sm):
            raise ValueError("end deve ser maior que start")
        return self


class AvailabilityOut(BaseModel):
    professional_id: int
    weekday: int
    start_utc: str  # "HH:MM"
    end_utc: str  # "HH:MM"
    start_local: str
    end_local: str
    tz_local: str


class AvailabilityBulkIn(BaseModel):
    items: list[AvailabilityItemIn]
    replace: bool = Field(
        False, description="Se true, substitui janelas dos weekdays informados"
    )


class AvailabilitySetWeekIn(BaseModel):
    professional_id: int = Field(..., ge=1)
    tz_local: str = Field("America/Sao_Paulo")
    # ex.: {"0":[{"start":"08:00","end":"12:00"},{"start":"13:00","end":"17:00"}], "1":[...]}
    week: dict[str, list[dict]]
