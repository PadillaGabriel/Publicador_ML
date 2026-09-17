from __future__ import annotations

import re
import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.accounts.service import load_access_token
from app.audit.service import audit
from app.catalog.service import get_category_metadata, metadata_is_publishable_leaf
from app.integrations.mercadolibre.client import MercadoLibreClient, MercadoLibreError
from app.persistence import MercadoLibreAccount, ProductMaster, ProductTechnicalAttribute
from app.technical_attributes.compatibility import compatible_value
from app.technical_attributes.normalization import normalize_attribute_value
from app.technical_attributes.policy import is_reusable_attribute
from app.technical_attributes.schemas import (
    MlaPublicationSnapshot,
    MlaReusePreviewResult,
    ReuseTechnicalAttributesResult,
    TechnicalAttributeRecord,
)


def _normalize_item_id(item_id: str) -> str:
    normalized = str(item_id or "").strip().upper()
    if not re.fullmatch(r"MLA\d+", normalized):
        raise HTTPException(status_code=422, detail="Ingresá un MLA válido, por ejemplo MLA123456789.")
    return normalized


def upsert_product_attributes(
    db: Session,
    *,
    product_master_id: uuid.UUID,
    attributes: dict,
    source_category_id: str | None,
    source_kind: str,
    source_reference: str | None,
) -> list[ProductTechnicalAttribute]:
    """Persist reusable product attributes using one row per product/attribute ID."""
    normalized: dict[str, dict] = {}
    for raw_id, raw_value in (attributes or {}).items():
        attribute_id = str(raw_id or "").strip().upper()
        if not is_reusable_attribute(attribute_id, source_category_id=source_category_id):
            continue
        value = normalize_attribute_value(raw_value)
        if value is not None:
            normalized[attribute_id] = value

    if not normalized:
        return []

    existing_rows = db.scalars(
        select(ProductTechnicalAttribute).where(
            ProductTechnicalAttribute.product_master_id == product_master_id,
            ProductTechnicalAttribute.attribute_id.in_(normalized),
        )
    ).all()
    existing_by_id = {row.attribute_id: row for row in existing_rows}

    persisted: list[ProductTechnicalAttribute] = []
    for attribute_id, value in normalized.items():
        row = existing_by_id.get(attribute_id)
        if row is None:
            row = ProductTechnicalAttribute(
                product_master_id=product_master_id,
                attribute_id=attribute_id,
                value=value,
                source_category_id=source_category_id,
                source_kind=source_kind,
                source_reference=source_reference,
            )
            db.add(row)
        else:
            row.value = value
            row.source_category_id = source_category_id
            row.source_kind = source_kind
            row.source_reference = source_reference
        persisted.append(row)
    db.flush()
    if source_kind == "PRODUCT_VERSION" and persisted:
        audit(
            db,
            "TECHNICAL_ATTRIBUTES_UPDATED_FROM_VERSION",
            "ProductMaster",
            str(product_master_id),
            {
                "source_category_id": source_category_id,
                "source_reference": source_reference,
                "updated_count": len(persisted),
            },
        )
    return persisted


def _load_mla_item(
    db: Session,
    *,
    account: MercadoLibreAccount,
    item_id: str,
) -> tuple[str, dict, MercadoLibreClient]:
    normalized_item_id = _normalize_item_id(item_id)
    token = load_access_token(db, account.id)
    client = MercadoLibreClient(token)
    try:
        item = client.item(normalized_item_id)
    except MercadoLibreError as exc:
        if exc.status_code == 404:
            raise HTTPException(status_code=404, detail="El MLA no existe o no es accesible con la cuenta seleccionada.") from exc
        raise HTTPException(status_code=502, detail="Mercado Libre no pudo devolver la publicación.") from exc

    item_site = str(item.get("site_id") or "").strip().upper()
    account_site = str(account.site_id or "").strip().upper()
    if item_site and account_site and item_site != account_site:
        raise HTTPException(status_code=422, detail="El MLA pertenece a otro sitio de Mercado Libre.")

    item_seller = str(item.get("seller_id") or "").strip()
    account_seller = str(account.seller_id or "").strip()
    if item_seller and account_seller and item_seller != account_seller:
        raise HTTPException(status_code=422, detail="El MLA no pertenece a la cuenta seleccionada.")

    return normalized_item_id, item, client


def _item_description(client: MercadoLibreClient, item_id: str) -> str | None:
    try:
        payload = client.item_description(item_id)
    except MercadoLibreError as exc:
        if exc.status_code == 404:
            return None
        raise HTTPException(status_code=502, detail="Mercado Libre no pudo devolver la descripción de la publicación.") from exc
    value = str(payload.get("plain_text") or "").strip()
    return value or None


def _technical_records_from_item(
    *,
    item: dict,
    item_id: str,
) -> tuple[list[TechnicalAttributeRecord], list[TechnicalAttributeRecord]]:
    category_id = str(item.get("category_id") or "").strip() or None
    imported_records: list[TechnicalAttributeRecord] = []
    skipped_records: list[TechnicalAttributeRecord] = []

    for raw in item.get("attributes") or []:
        if not isinstance(raw, dict):
            continue
        attribute_id = str(raw.get("id") or "").strip().upper()
        label = str(raw.get("name") or attribute_id).strip() or attribute_id
        value = normalize_attribute_value(raw)
        target = imported_records if (
            is_reusable_attribute(attribute_id, source_category_id=category_id)
            and value is not None
        ) else skipped_records
        target.append(
            TechnicalAttributeRecord(
                attribute_id=attribute_id or "UNKNOWN",
                label=label or attribute_id or "Atributo",
                value=value,
                source_category_id=category_id,
                source_kind="MLA_IMPORT",
                source_reference=item_id,
                status="IMPORTADO" if target is imported_records else "OMITIDO",
            )
        )

    return imported_records, skipped_records


def _seller_sku(item: dict) -> str | None:
    for raw in item.get("attributes") or []:
        if not isinstance(raw, dict) or str(raw.get("id") or "").strip().upper() != "SELLER_SKU":
            continue
        value = normalize_attribute_value(raw)
        if value:
            sku = str(value.get("value_name") or value.get("name") or value.get("value_id") or "").strip()
            if sku:
                return sku
    legacy = str(item.get("seller_custom_field") or "").strip()
    return legacy or None


def preview_mla(
    db: Session,
    *,
    account: MercadoLibreAccount,
    item_id: str,
) -> MlaPublicationSnapshot:
    """Read an owned ML publication without creating or mutating a ProductMaster."""
    normalized_item_id, item, client = _load_mla_item(db, account=account, item_id=item_id)
    imported, skipped = _technical_records_from_item(item=item, item_id=normalized_item_id)
    return MlaPublicationSnapshot(
        item_id=normalized_item_id,
        title=str(item.get("title") or "").strip(),
        description=_item_description(client, normalized_item_id),
        category_id=str(item.get("category_id") or "").strip() or None,
        condition=str(item.get("condition") or "").strip() or None,
        seller_sku=_seller_sku(item),
        attributes=imported,
        skipped=skipped,
    )


def _category_fields(
    db: Session,
    *,
    account: MercadoLibreAccount,
    category_id: str,
) -> tuple[str, list[dict]]:
    category = str(category_id or "").strip().upper()
    if not category:
        raise HTTPException(status_code=422, detail="Categoría requerida.")
    token = load_access_token(db, account.id)
    try:
        snapshot = get_category_metadata(
            db,
            category,
            site_id=account.site_id,
            access_token=token,
        )
    except MercadoLibreError as exc:
        raise HTTPException(status_code=502, detail="Mercado Libre no pudo devolver la categoría destino.") from exc
    if not metadata_is_publishable_leaf(snapshot):
        raise HTTPException(status_code=422, detail="La categoría destino no es una categoría hoja publicable.")
    fields = [
        field
        for field in ((snapshot.normalized_schema or {}).get("fields") or [])
        if isinstance(field, dict) and field.get("id")
    ]
    return category, fields


def _resolve_records(
    *,
    records: list[TechnicalAttributeRecord],
    category: str,
    fields: list[dict],
) -> tuple[list[TechnicalAttributeRecord], list[TechnicalAttributeRecord], list[TechnicalAttributeRecord]]:
    field_by_id = {str(field["id"]).strip().upper(): field for field in fields}
    reusable: list[TechnicalAttributeRecord] = []
    incompatible: list[TechnicalAttributeRecord] = []
    reusable_ids: set[str] = set()

    for record in records:
        attribute_id = str(record.attribute_id or "").strip().upper()
        field = field_by_id.get(attribute_id)
        if field is None:
            incompatible.append(record.model_copy(update={"status": "NO_APLICA"}))
            continue
        if not is_reusable_attribute(
            attribute_id,
            source_category_id=record.source_category_id,
            target_category_id=category,
        ) or not compatible_value(field, record.value):
            incompatible.append(record.model_copy(update={
                "label": str(field.get("label") or attribute_id),
                "status": "INCOMPATIBLE",
            }))
            continue
        reusable_ids.add(attribute_id)
        reusable.append(record.model_copy(update={
            "label": str(field.get("label") or attribute_id),
            "status": "REUTILIZABLE",
        }))

    pending: list[TechnicalAttributeRecord] = []
    for field in fields:
        attribute_id = str(field.get("id") or "").strip().upper()
        if attribute_id in reusable_ids:
            continue
        if field.get("hidden") or field.get("importance") not in {"required", "recommended"}:
            continue
        if not is_reusable_attribute(attribute_id, source_category_id=None, target_category_id=category):
            continue
        pending.append(TechnicalAttributeRecord(
            attribute_id=attribute_id,
            label=str(field.get("label") or attribute_id),
            value=None,
            status="PENDIENTE",
        ))

    reusable.sort(key=lambda item: item.attribute_id)
    pending.sort(key=lambda item: item.attribute_id)
    incompatible.sort(key=lambda item: item.attribute_id)
    return reusable, pending, incompatible


def resolve_preview_mla(
    db: Session,
    *,
    account: MercadoLibreAccount,
    item_id: str,
    category_id: str,
) -> MlaReusePreviewResult:
    preview = preview_mla(db, account=account, item_id=item_id)
    category, fields = _category_fields(db, account=account, category_id=category_id)
    reusable, pending, incompatible = _resolve_records(
        records=preview.attributes,
        category=category,
        fields=fields,
    )
    return MlaReusePreviewResult(
        item_id=preview.item_id,
        category_id=category,
        reusable=reusable,
        pending=pending,
        incompatible=incompatible,
    )


def resolve_reuse(
    db: Session,
    *,
    product: ProductMaster,
    account: MercadoLibreAccount,
    category_id: str,
) -> ReuseTechnicalAttributesResult:
    category, fields = _category_fields(db, account=account, category_id=category_id)
    rows = db.scalars(
        select(ProductTechnicalAttribute)
        .where(ProductTechnicalAttribute.product_master_id == product.id)
        .order_by(ProductTechnicalAttribute.attribute_id)
    ).all()

    records = [
        TechnicalAttributeRecord(
            attribute_id=str(row.attribute_id or "").strip().upper(),
            label=str(row.attribute_id or "").strip().upper(),
            value=row.value,
            source_category_id=row.source_category_id,
            source_kind=row.source_kind,
            source_reference=row.source_reference,
            status="ALMACENADO",
        )
        for row in rows
    ]
    reusable, pending, incompatible = _resolve_records(
        records=records,
        category=category,
        fields=fields,
    )

    audit(
        db,
        "TECHNICAL_ATTRIBUTES_REUSED",
        "ProductMaster",
        str(product.id),
        {
            "category_id": category,
            "account_id": str(account.id),
            "reusable_count": len(reusable),
            "pending_count": len(pending),
            "incompatible_count": len(incompatible),
        },
    )
    db.commit()
    return ReuseTechnicalAttributesResult(
        product_id=product.id,
        category_id=category,
        reusable=reusable,
        pending=pending,
        incompatible=incompatible,
    )
