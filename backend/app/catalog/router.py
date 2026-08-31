import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.accounts.service import load_access_token
from app.catalog.service import get_category_metadata, metadata_is_publishable_leaf
from app.core.db import get_db
from app.integrations.mercadolibre.client import MercadoLibreClient, MercadoLibreError
from app.persistence import MercadoLibreAccount

router = APIRouter(prefix="/api/catalog", tags=["catalog"])


def _account(db: Session, account_id: uuid.UUID) -> MercadoLibreAccount:
    account = db.get(MercadoLibreAccount, account_id)
    if not account or not account.active:
        raise HTTPException(status_code=404, detail="Cuenta de Mercado Libre no encontrada.")
    return account


@router.get("/category-suggestions")
def category_suggestions(
    account_id: uuid.UUID,
    q: str = Query(min_length=3, max_length=300),
    limit: int = Query(default=8, ge=1, le=20),
    db: Session = Depends(get_db),
):
    account = _account(db, account_id)
    access_token = load_access_token(db, account_id)
    try:
        raw = MercadoLibreClient(access_token).category_suggestions(account.site_id, q.strip(), limit)
    except MercadoLibreError as exc:
        raise HTTPException(status_code=502, detail=f"Mercado Libre no pudo sugerir categorías: {exc}") from exc

    suggestions = []
    for item in raw:
        category_id = item.get("category_id")
        category_name = item.get("category_name")
        if not category_id or not category_name:
            continue
        suggestions.append(
            {
                "category_id": str(category_id),
                "category_name": str(category_name),
                "domain_id": item.get("domain_id"),
                "domain_name": item.get("domain_name"),
            }
        )
    return suggestions


@router.get("/categories")
def categories(account_id: uuid.UUID, db: Session = Depends(get_db)):
    """Manual-exploration fallback. The primary flow uses category suggestions."""
    account = _account(db, account_id)
    access_token = load_access_token(db, account_id)
    return MercadoLibreClient(access_token).site_categories(account.site_id)


@router.get("/categories/{category_id}")
def category_metadata(
    category_id: str,
    account_id: uuid.UUID,
    refresh: bool = False,
    db: Session = Depends(get_db),
):
    account = _account(db, account_id)
    access_token = load_access_token(db, account_id)
    snapshot = get_category_metadata(
        db,
        category_id,
        account.site_id,
        refresh,
        access_token,
    )
    if not metadata_is_publishable_leaf(snapshot):
        raise HTTPException(
            status_code=422,
            detail="La categoría seleccionada no es una categoría hoja publicable. Elegí una sugerencia final de Mercado Libre.",
        )
    return {
        "category_id": snapshot.category_id,
        "name": snapshot.category_name,
        "schema": snapshot.normalized_schema,
        "raw_category": snapshot.raw_category,
        "fetched_at": snapshot.fetched_at,
        "expires_at": snapshot.expires_at,
        "publishable_leaf": True,
    }
