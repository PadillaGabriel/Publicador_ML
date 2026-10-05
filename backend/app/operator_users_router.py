"""Administrator/supervisor operator lifecycle API.

Only ADMIN may manage an existing ADMIN or assign ADMIN, and the last active
administrator cannot be deactivated. Account grants and product leases are
intentionally not exposed until all consuming operations enforce their scope.
"""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.time import utcnow
from app.identity import OperatorSession, OperatorUser
from app.identity_policy import Role, can_assign_role, can_manage_user
from app.operator_auth import hash_password, normalize_username, request_identity, require_permission

router = APIRouter(prefix="/api/operator-users", tags=["operator-users"])


class NewOperator(BaseModel):
    username: str = Field(min_length=3, max_length=120)
    display_name: str = Field(min_length=1, max_length=160)
    password: str = Field(min_length=12, max_length=1024)
    role: Literal["ADMIN", "SUPERVISOR", "OPERATOR"]


class UpdateOperator(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=160)
    role: Literal["ADMIN", "SUPERVISOR", "OPERATOR"] | None = None
    active: bool | None = None
    password: str | None = Field(default=None, min_length=12, max_length=1024)


def _actor(db: Session, request: Request) -> OperatorUser:
    actor, _ = request_identity(db, request)
    require_permission(actor.role, "manage_users")
    return actor


def _public(user: OperatorUser) -> dict:
    return {
        "id": str(user.id), "username": user.username,
        "display_name": user.display_name, "role": user.role,
        "active": user.active, "created_at": user.created_at,
    }


def _check_target(actor: OperatorUser, target: OperatorUser, new_role: str | None = None) -> None:
    if not can_manage_user(Role(actor.role), Role(target.role)):
        raise HTTPException(status_code=403, detail="No podés administrar este usuario")
    if new_role is not None and not can_assign_role(Role(actor.role), Role(new_role)):
        raise HTTPException(status_code=403, detail="No podés asignar ese rol")


@router.get("")
def list_users(request: Request, db: Session = Depends(get_db)):
    actor = _actor(db, request)
    query = select(OperatorUser).order_by(OperatorUser.username)
    if actor.role != Role.ADMIN:
        query = query.where(OperatorUser.role != Role.ADMIN)
    return [_public(user) for user in db.scalars(query)]


@router.post("", status_code=201)
def create_user(payload: NewOperator, request: Request, db: Session = Depends(get_db)):
    actor = _actor(db, request)
    if not can_assign_role(Role(actor.role), Role(payload.role)):
        raise HTTPException(status_code=403, detail="No podés asignar ese rol")
    username = normalize_username(payload.username)
    if not username or any(ch.isspace() for ch in username):
        raise HTTPException(status_code=422, detail="Nombre de usuario inválido")
    if db.scalar(select(OperatorUser.id).where(OperatorUser.username == username)):
        raise HTTPException(status_code=409, detail="El nombre de usuario ya existe")
    user = OperatorUser(username=username, display_name=payload.display_name.strip(),
                        password_hash=hash_password(payload.password), role=payload.role, active=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    return _public(user)


@router.patch("/{user_id}")
def update_user(user_id: uuid.UUID, payload: UpdateOperator, request: Request,
                db: Session = Depends(get_db)):
    actor = _actor(db, request)
    # Lock the target row to serialize concurrent updates and administrator removal.
    target = db.scalar(select(OperatorUser).where(OperatorUser.id == user_id).with_for_update())
    if target is None:
        raise HTTPException(status_code=404, detail="Usuario inexistente")
    _check_target(actor, target, payload.role)
    if target.id == actor.id and (payload.active is False or (payload.role is not None and payload.role != target.role)):
        raise HTTPException(status_code=409, detail="No podés desactivarte ni cambiar tu propio rol")
    if target.role == Role.ADMIN and (payload.active is False or (payload.role is not None and payload.role != Role.ADMIN)) and target.active:
        active_admins = db.scalar(select(func.count(OperatorUser.id)).where(
            OperatorUser.role == Role.ADMIN, OperatorUser.active.is_(True)))
        if active_admins <= 1:
            raise HTTPException(status_code=409, detail="No se puede eliminar el último Administrador activo")
    if payload.display_name is not None:
        target.display_name = payload.display_name.strip()
    if payload.role is not None:
        target.role = payload.role
    if payload.active is not None:
        target.active = payload.active
    if payload.password is not None:
        target.password_hash = hash_password(payload.password)
    if payload.active is False or payload.password is not None or payload.role is not None:
        # Current sessions no longer convey the old credentials or privileges.
        db.query(OperatorSession).filter(OperatorSession.user_id == target.id,
                                         OperatorSession.revoked_at.is_(None)).update(
            {OperatorSession.revoked_at: utcnow()}, synchronize_session=False)
    db.commit()
    db.refresh(target)
    return _public(target)
