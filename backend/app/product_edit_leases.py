"""Exclusive, expiring product leases and creator checks.

The product-master row is locked to serialize competing lease acquisitions even
when the lease record does not yet exist. Operations commit before returning.
"""

import uuid
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.identity import OperatorSession, OperatorUser, ProductEditLease
from app.persistence import ProductMaster

LEASE_DURATION = timedelta(minutes=2)


def visible_product(db: Session, user: OperatorUser, product_id: uuid.UUID, *, lock: bool = False) -> ProductMaster:
    query = select(ProductMaster).where(ProductMaster.id == product_id)
    if lock:
        query = query.with_for_update()
    product = db.scalar(query)
    if product is None:
        raise HTTPException(status_code=404, detail="Ficha inexistente")
    if user.role == "SUPERVISOR":
        raise HTTPException(status_code=403, detail="Este rol no puede gestionar fichas")
    if user.role != "ADMIN" and product.created_by_user_id != user.id:
        # Historical records with unknown authorship remain admin-only.
        raise HTTPException(status_code=403, detail="La ficha no pertenece al operador")
    return product


def lease_snapshot(lease: ProductEditLease | None) -> dict:
    now = utcnow()
    if lease is None or lease.expires_at <= now:
        return {"locked": False, "expires_at": None}
    return {"locked": True, "expires_at": lease.expires_at, "owner_user_id": str(lease.owner_user_id)}


def acquire(db: Session, user: OperatorUser, session: OperatorSession, product_id: uuid.UUID) -> dict:
    visible_product(db, user, product_id, lock=True)
    current = db.get(ProductEditLease, product_id)
    now = utcnow()
    if current is not None and current.expires_at > now and current.session_id != session.id:
        raise HTTPException(status_code=409, detail="La ficha está siendo editada por otra sesión")
    token = uuid.uuid4()
    if current is None:
        current = ProductEditLease(product_master_id=product_id, owner_user_id=user.id,
                                   session_id=session.id, fencing_token=token, expires_at=now + LEASE_DURATION)
        db.add(current)
    else:
        current.owner_user_id = user.id
        current.session_id = session.id
        current.fencing_token = token
        current.expires_at = now + LEASE_DURATION
        current.updated_at = now
    db.commit()
    return {"fencing_token": str(token), "expires_at": current.expires_at}


def require_owned_lease(db: Session, user: OperatorUser, session: OperatorSession,
                        product_id: uuid.UUID, fencing_token: uuid.UUID) -> ProductEditLease:
    visible_product(db, user, product_id, lock=True)
    current = db.get(ProductEditLease, product_id)
    if current is None or current.expires_at <= utcnow() or current.session_id != session.id or current.owner_user_id != user.id or current.fencing_token != fencing_token:
        raise HTTPException(status_code=409, detail="Bloqueo vencido o perteneciente a otra sesión")
    return current


def renew(db: Session, user: OperatorUser, session: OperatorSession,
          product_id: uuid.UUID, fencing_token: uuid.UUID) -> dict:
    current = require_owned_lease(db, user, session, product_id, fencing_token)
    current.expires_at = utcnow() + LEASE_DURATION
    current.updated_at = utcnow()
    db.commit()
    return {"expires_at": current.expires_at}


def release(db: Session, user: OperatorUser, session: OperatorSession,
            product_id: uuid.UUID, fencing_token: uuid.UUID) -> None:
    current = require_owned_lease(db, user, session, product_id, fencing_token)
    db.delete(current)
    db.commit()


def require_edit_token(db: Session, user: OperatorUser, session: OperatorSession,
                       product_id: uuid.UUID, token: str | None) -> None:
    """Guard the write under the master row lock; caller must commit within the same transaction."""
    if not token:
        raise HTTPException(status_code=428, detail="Adquirí un bloqueo antes de modificar esta ficha")
    try:
        fencing_token = uuid.UUID(token)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail="Token de edición inválido") from exc
    require_owned_lease(db, user, session, product_id, fencing_token)
