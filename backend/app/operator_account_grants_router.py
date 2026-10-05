"""Management of explicit internal grants to Mercado Libre accounts.

These grants are administrative data until every commercial endpoint enforces
account scope. They do not, by themselves, grant access to a route.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.identity import OperatorAccountGrant, OperatorUser
from app.identity_policy import Role, can_manage_user
from app.operator_auth import request_identity, require_permission
from app.persistence import MercadoLibreAccount

router = APIRouter(prefix="/api/operator-account-grants", tags=["operator-account-grants"])


class GrantReplacement(BaseModel):
    account_ids: list[uuid.UUID]


def _manager(db: Session, request: Request, user_id: uuid.UUID) -> OperatorUser:
    actor, _ = request_identity(db, request)
    require_permission(actor.role, "manage_users")
    target = db.get(OperatorUser, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Usuario inexistente")
    if not can_manage_user(Role(actor.role), Role(target.role)):
        raise HTTPException(status_code=403, detail="No podés administrar las cuentas de este usuario")
    return target


@router.get("/accounts")
def available_accounts(request: Request, db: Session = Depends(get_db)):
    actor, _ = request_identity(db, request)
    require_permission(actor.role, "manage_users")
    return [
        {"id": str(account.id), "nickname": account.nickname, "active": account.active}
        for account in db.scalars(select(MercadoLibreAccount).order_by(MercadoLibreAccount.nickname))
    ]


@router.get("/{user_id}")
def read_grants(user_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    _manager(db, request, user_id)
    return {"user_id": str(user_id), "account_ids": [
        str(account_id) for account_id in db.scalars(
            select(OperatorAccountGrant.account_id).where(OperatorAccountGrant.user_id == user_id)
        )
    ]}


@router.put("/{user_id}")
def replace_grants(
    user_id: uuid.UUID, payload: GrantReplacement, request: Request, db: Session = Depends(get_db)
):
    # Serialize against disabling a user, privilege escalation and concurrent grant changes.
    target = db.scalar(select(OperatorUser).where(OperatorUser.id == user_id).with_for_update())
    if target is None:
        raise HTTPException(status_code=404, detail="Usuario inexistente")
    _manager(db, request, user_id)
    account_ids = set(payload.account_ids)
    if len(account_ids) != len(payload.account_ids):
        raise HTTPException(status_code=422, detail="No repitas cuentas en la asignación")
    known = set(db.scalars(
        select(MercadoLibreAccount.id).where(MercadoLibreAccount.id.in_(account_ids))
    )) if account_ids else set()
    if known != account_ids:
        raise HTTPException(status_code=422, detail="Una o más cuentas Mercado Libre no existen")
    # Serialized by locked operator row; an empty assignment intentionally means no accounts.
    db.execute(delete(OperatorAccountGrant).where(OperatorAccountGrant.user_id == user_id))
    db.add_all(OperatorAccountGrant(user_id=user_id, account_id=account_id) for account_id in account_ids)
    db.commit()
    return {"user_id": str(user_id), "account_ids": sorted(str(value) for value in account_ids)}
