from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.persistence import MercadoLibreAccount, ProductMaster
from app.technical_attributes.schemas import (
    ImportMlaRequest,
    ImportTechnicalAttributesResult,
    ReuseTechnicalAttributesResult,
)
from app.technical_attributes.service import import_from_mla, resolve_reuse

router = APIRouter(prefix="/api/products", tags=["technical-attributes"])


def _product(db: Session, product_id: uuid.UUID) -> ProductMaster:
    product = db.get(ProductMaster, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Producto no encontrado.")
    return product


def _account(db: Session, account_id: uuid.UUID) -> MercadoLibreAccount:
    account = db.get(MercadoLibreAccount, account_id)
    if not account or not account.active:
        raise HTTPException(status_code=404, detail="Cuenta de Mercado Libre no encontrada.")
    return account


@router.post(
    "/{product_id}/technical-attributes/import-mla",
    response_model=ImportTechnicalAttributesResult,
)
def import_mla_attributes(
    product_id: uuid.UUID,
    payload: ImportMlaRequest,
    db: Session = Depends(get_db),
):
    product = _product(db, product_id)
    account = _account(db, payload.account_id)
    return import_from_mla(db, product=product, account=account, item_id=payload.item_id)


@router.get(
    "/{product_id}/technical-attributes/reuse",
    response_model=ReuseTechnicalAttributesResult,
)
def reusable_attributes(
    product_id: uuid.UUID,
    account_id: uuid.UUID = Query(...),
    category_id: str = Query(min_length=1, max_length=40),
    db: Session = Depends(get_db),
):
    product = _product(db, product_id)
    account = _account(db, account_id)
    return resolve_reuse(db, product=product, account=account, category_id=category_id)
