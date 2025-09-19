# app/api/routes/professionals.py
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import and_
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


@router.put(
    "/{professional_id}/link-user/{user_id}", status_code=status.HTTP_204_NO_CONTENT
)
def link_user_to_professional(
    professional_id: int,
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(Role.COORDINATION)),
):
    prof = db.get(Professional, professional_id)
    if not prof:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Profissional não encontrado")
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuário não encontrado")
    if user.role != Role.PROFESSIONAL:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Usuário não possui papel PROFESSIONAL"
        )

    # já vinculado a outro?
    in_use = (
        db.query(Professional)
        .filter(
            and_(Professional.user_id == user_id, Professional.id != professional_id)
        )
        .first()
    )
    if in_use:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Este usuário já está vinculado a outro profissional",
        )

    prof.user_id = user_id
    db.add(prof)
    db.commit()
    return


@router.delete("/{professional_id}/link-user", status_code=status.HTTP_204_NO_CONTENT)
def unlink_user_from_professional(
    professional_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(Role.COORDINATION)),
):
    prof = db.get(Professional, professional_id)
    if not prof:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Profissional não encontrado")
    prof.user_id = None
    db.add(prof)
    db.commit()
    return
