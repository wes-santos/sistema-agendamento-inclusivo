from pydantic import BaseModel, constr


class ProfessionalCreateIn(BaseModel):
    name: constr(min_length=1, max_length=120)
    speciality: constr(max_length=120) | None = None
    is_active: bool | None = True


class ProfessionalOut(BaseModel):
    id: int
    name: str
    speciality: str | None = None
    is_active: bool
