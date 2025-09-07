from pydantic import BaseModel, Field, constr


class StudentCreateIn(BaseModel):
    name: constr(min_length=1, max_length=120)
    guardian_user_id: int | None = Field(
        None,
        description="Só COORDINATION pode informar; FAMILY ignora e usa o próprio id.",
    )


class StudentOut(BaseModel):
    id: int
    name: str
    guardian_user_id: int
