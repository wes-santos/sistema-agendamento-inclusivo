# app/api/routes/students.py
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.audit.helpers import record_audit
from app.db import get_db
from app.deps import get_current_user, require_roles
from app.models.student import Student
from app.models.user import Role, User
from app.schemas.students import StudentCreateIn, StudentOut

router = APIRouter(prefix="/students", tags=["students"])


@router.post("", response_model=StudentOut, status_code=201)
def create_student(
    payload: StudentCreateIn,
    request: Request,
    current_user: Annotated[
        User, Depends(require_roles(Role.FAMILY, Role.COORDINATION))
    ],
    db: Session = Depends(get_db),
):
    # FAMILY sempre cria para si; COORDINATION pode escolher o responsável
    if current_user.role == Role.FAMILY:
        guardian_user_id = current_user.id
    else:
        if not payload.guardian_user_id:
            raise HTTPException(400, "guardian_user_id é obrigatório para coordenação.")
        guardian_user_id = payload.guardian_user_id

    # opcional: validar se guardian existe e é FAMILY
    from app.models.user import User as U

    guardian = db.get(U, guardian_user_id)
    if not guardian or guardian.role != Role.FAMILY:
        raise HTTPException(400, "Responsável inválido (deve ser um usuário FAMILY).")

    st = Student(name=payload.name.strip(), guardian_user_id=guardian_user_id)
    db.add(st)
    db.flush()

    # audit
    record_audit(
        db,
        request=request,
        user_id=current_user.id,
        action="CREATE",
        entity="student",
        entity_id=st.id,
    )

    db.commit()
    db.refresh(st)
    return StudentOut(id=st.id, name=st.name, guardian_user_id=st.guardian_user_id)


@router.get("", response_model=list[StudentOut])
def list_students(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Session = Depends(get_db),
    guardian_user_id: int | None = Query(
        None, ge=1, description="Filtro (apenas coordenação)"
    ),
):
    q = db.query(Student)
    if current_user.role == Role.FAMILY:
        q = q.filter(Student.guardian_user_id == current_user.id)
    elif current_user.role == Role.COORDINATION:
        if guardian_user_id:
            q = q.filter(Student.guardian_user_id == guardian_user_id)
    else:
        # profissionais não têm acesso por padrão (ajuste se quiser)
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Sem permissão")

    rows = q.order_by(Student.id.desc()).all()
    return [
        StudentOut(id=s.id, name=s.name, guardian_user_id=s.guardian_user_id)
        for s in rows
    ]


@router.get("/{student_id}", response_model=StudentOut)
def get_student(
    student_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    st = db.get(Student, student_id)
    if not st:
        raise HTTPException(404, "Aluno não encontrado")
    if current_user.role == Role.FAMILY and st.guardian_user_id != current_user.id:
        raise HTTPException(403, "Sem permissão")
    if current_user.role not in (Role.FAMILY, Role.COORDINATION):
        raise HTTPException(403, "Sem permissão")
    return StudentOut(id=st.id, name=st.name, guardian_user_id=st.guardian_user_id)
