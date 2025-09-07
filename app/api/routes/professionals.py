# app/api/routes/professionals.py
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.audit.helpers import record_audit
from app.db import get_db
from app.deps import get_current_user, require_roles
from app.models.professional import Professional
from app.models.user import Role, User
from app.schemas.professionals import ProfessionalCreateIn, ProfessionalOut

router = APIRouter(prefix="/professionals", tags=["professionals"])


@router.post("", response_model=ProfessionalOut, status_code=201)
def create_professional(
    payload: ProfessionalCreateIn,
    request: Request,
    current_user: Annotated[User, Depends(require_roles(Role.COORDINATION))],
    db: Session = Depends(get_db),
):
    p = Professional(
        name=payload.name.strip(),
        speciality=(payload.speciality or None),
        is_active=bool(payload.is_active) if payload.is_active is not None else True,
    )
    db.add(p)
    db.flush()
    # audit
    record_audit(
        db,
        request=request,
        user_id=current_user.id,
        action="CREATE",
        entity="professional",
        entity_id=p.id,
    )
    db.commit()
    db.refresh(p)
    return ProfessionalOut(
        id=p.id, name=p.name, speciality=p.speciality, is_active=p.is_active
    )


@router.get("", response_model=list[ProfessionalOut])
def list_professionals(
    current_user: Annotated[User, Depends(get_current_user)],
    include_inactive: bool = Query(False),
    q: str | None = Query(None, description="Busca por nome/especialidade (contém)"),
    db: Session = Depends(get_db),
):
    qs = db.query(Professional)
    if not include_inactive:
        qs = qs.filter(Professional.is_active == True)  # noqa: E712
    if q:
        like = f"%{q.strip()}%"
        from sqlalchemy import or_

        qs = qs.filter(
            or_(Professional.name.ilike(like), Professional.speciality.ilike(like))
        )
    rows = qs.order_by(Professional.name.asc()).all()
    return [
        ProfessionalOut(
            id=p.id, name=p.name, speciality=p.speciality, is_active=p.is_active
        )
        for p in rows
    ]


@router.get("/{professional_id}", response_model=ProfessionalOut)
def get_professional(
    professional_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    p = db.get(Professional, professional_id)
    if not p:
        raise HTTPException(404, "Profissional não encontrado")
    return ProfessionalOut(
        id=p.id, name=p.name, speciality=p.speciality, is_active=p.is_active
    )
