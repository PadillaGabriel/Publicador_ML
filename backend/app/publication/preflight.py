from __future__ import annotations

from sqlalchemy.orm import Session

from app.accounts.service import load_access_token
from app.catalog.service import get_category_metadata
from app.integrations.mercadolibre.client import MercadoLibreClient, MercadoLibreError
from app.persistence import DraftBatch, MercadoLibreAccount, ProductVersion, PublicationDraft
from app.publication.errors import provider_validation_issues
from app.publication.payload import build_item_payload
from app.publication.shipping import ShippingCapabilityError


def validate_draft_with_mercadolibre(
    db: Session,
    draft: PublicationDraft,
    image_urls: list[str],
) -> list[dict]:
    """Validate the exact create-item payload against Mercado Libre without publishing it."""

    batch = db.get(DraftBatch, draft.batch_id)
    if batch is None:
        raise RuntimeError("Draft batch not found during Mercado Libre preflight.")
    version = db.get(ProductVersion, batch.product_version_id)
    if version is None:
        raise RuntimeError("Product version not found during Mercado Libre preflight.")
    account = db.get(MercadoLibreAccount, batch.account_id)
    if account is None:
        raise RuntimeError("Mercado Libre account not found during publication preflight.")

    access_token = load_access_token(db, account.id)
    metadata = get_category_metadata(
        db,
        version.category_id,
        account.site_id,
        access_token=access_token,
    )
    try:
        payload = build_item_payload(
            version,
            draft,
            image_urls,
            seller_sku=version.master.internal_sku,
        )
    except ShippingCapabilityError as exc:
        return [{
            "code": "shipping.invalid_configuration",
            "field": "shipping",
            "message": str(exc),
        }]

    try:
        MercadoLibreClient(access_token).validate_item(payload)
    except MercadoLibreError as exc:
        if exc.status_code in {400, 422}:
            return provider_validation_issues(exc.payload, metadata.normalized_schema or {})
        raise
    return []
