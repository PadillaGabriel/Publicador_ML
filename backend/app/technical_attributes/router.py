from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.operator_auth import request_identity
from app.product_edit_leases import visible_product
from app.operator_account_scope import ensure_account
from app.persistence import MercadoLibreAccount, ProductMaster
from app.technical_attributes.schemas import (
    ImportMlaRequest,
    MlaPublicationSnapshot,
    MlaReusePreviewResult,
    ResolveMlaRequest,
    ReuseTechnicalAttributesResult,
)
from app.technical_attributes.service import preview_mla, resolve_preview_mla, resolve_reuse

router = APIRouter(prefix="/api/products", tags=["technical-attributes"])
publication_import_router = APIRouter(prefix="/api/publication-import", tags=["technical-attributes"])


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



@publication_import_router.post("/mla", response_model=MlaPublicationSnapshot)
def preview_mla_publication(
    payload: ImportMlaRequest,
    db: Session = Depends(get_db),
):
    account = _account(db, payload.account_id)
    return preview_mla(db, account=account, item_id=payload.item_id)


@publication_import_router.post("/mla/reuse", response_model=MlaReusePreviewResult)
def preview_mla_reuse(
    payload: ResolveMlaRequest,
    db: Session = Depends(get_db),
):
    account = _account(db, payload.account_id)
    return resolve_preview_mla(
        db,
        account=account,
        item_id=payload.item_id,
        category_id=payload.category_id,
    )


@router.get(
    "/{product_id}/technical-attributes/reuse",
    response_model=ReuseTechnicalAttributesResult,
)
def reusable_attributes(
    product_id: uuid.UUID,
    request: Request,
    account_id: uuid.UUID = Query(...),
    category_id: str = Query(min_length=1, max_length=40),
    db: Session = Depends(get_db),
):
    actor, _ = request_identity(db, request)
    product = visible_product(db, actor, product_id)
    ensure_account(db, actor, account_id)
    account = _account(db, account_id)
    return resolve_reuse(db, product=product, account=account, category_id=category_id)
