"""Operator-scoped, explicit edit-lease lifecycle API."""
import uuid

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.identity import ProductEditLease
from app.operator_auth import request_identity
from app.product_edit_leases import acquire, lease_snapshot, release, renew, visible_product

router = APIRouter(prefix="/api/product-edit-leases", tags=["product-edit-leases"])


class LeaseToken(BaseModel):
    fencing_token: uuid.UUID


@router.get("/{product_id}")
def read_lease(product_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    user, _ = request_identity(db, request)
    visible_product(db, user, product_id)
    return lease_snapshot(db.get(ProductEditLease, product_id))


@router.post("/{product_id}")
def take_lease(product_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    user, session = request_identity(db, request)
    return acquire(db, user, session, product_id)


@router.put("/{product_id}")
def renew_lease(product_id: uuid.UUID, payload: LeaseToken, request: Request, db: Session = Depends(get_db)):
    user, session = request_identity(db, request)
    return renew(db, user, session, product_id, payload.fencing_token)


@router.delete("/{product_id}", status_code=204)
def drop_lease(product_id: uuid.UUID, payload: LeaseToken, request: Request, db: Session = Depends(get_db)):
    user, session = request_identity(db, request)
    release(db, user, session, product_id, payload.fencing_token)
