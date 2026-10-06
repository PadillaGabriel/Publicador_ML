from __future__ import annotations

from typing import Any
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit.service import audit
from app.persistence import ProductMaster, ProductVersion
from fastapi import HTTPException
from app.technical_attributes.service import upsert_product_attributes


def find_product_by_sku(db: Session, internal_sku: str) -> tuple[ProductMaster | None, ProductVersion | None]:
    sku = internal_sku.strip()
    if not sku:
        return None, None

    master = db.scalar(select(ProductMaster).where(ProductMaster.internal_sku == sku))
    if master is None:
        return None, None

    version = db.scalar(
        select(ProductVersion)
        .where(ProductVersion.product_master_id == master.id)
        .order_by(ProductVersion.version_number.desc())
        .limit(1)
    )
    return master, version


def serialize_version(version: ProductVersion) -> dict[str, Any]:
    return {
        "id": version.id,
        "product_master_id": version.product_master_id,
        "version_number": version.version_number,
        "category_id": version.category_id,
        "title_reference": version.title_reference,
        "description": version.description,
        "price": float(version.price),
        "quantity": version.quantity,
        "condition": version.condition,
        "currency_id": version.currency_id,
        "listing_type_id": version.listing_type_id,
        "attributes": version.attributes or {},
        "commercial": version.commercial or {},
        "logistics": version.logistics or {},
        "discovery_context": version.discovery_context or {},
        "images": [
            {
                "id": image.id,
                "original_name": image.original_name,
                "position": image.position,
                "mime_type": image.mime_type,
            }
            for image in sorted(version.images, key=lambda item: item.position)
        ],
    }


def save_product_version(db: Session, payload: Any, *, actor_user_id: uuid.UUID,
                         authorization: Any = None, expected_version: int | None = None) -> tuple[ProductMaster, ProductVersion, bool]:
    sku = payload.internal_sku.strip()
    master = db.scalar(select(ProductMaster).where(ProductMaster.internal_sku == sku).with_for_update())
    created_master = master is None

    if master is None:
        master = ProductMaster(
            internal_sku=sku,
            internal_name=payload.internal_name,
            created_by_user_id=actor_user_id,
        )
        db.add(master)
        db.flush()
        version_number = 1
    else:
        if authorization is None:
            raise HTTPException(status_code=428, detail="Se requiere bloqueo vigente para una ficha existente")
        authorization(master.id)
        if expected_version is None:
            raise HTTPException(status_code=428, detail="Se requiere la versión esperada de la ficha")
        latest_version = db.scalar(select(func.max(ProductVersion.version_number)).where(
            ProductVersion.product_master_id == master.id
        )) or 0
        if latest_version != expected_version:
            raise HTTPException(status_code=409, detail="La ficha fue modificada; actualizá los datos antes de guardar")
        master.internal_name = payload.internal_name
        version_number = latest_version + 1

    version = ProductVersion(
        product_master_id=master.id,
        version_number=version_number,
        category_id=payload.category_id,
        title_reference=payload.title_reference,
        description=payload.description,
        price=payload.price,
        quantity=payload.quantity,
        condition=payload.condition,
        currency_id=payload.currency_id,
        listing_type_id=payload.listing_type_id,
        attributes=payload.attributes,
        commercial=payload.commercial,
        logistics=payload.logistics,
        discovery_context=payload.discovery_context,
    )
    db.add(version)
    db.flush()
    upsert_product_attributes(
        db,
        product_master_id=master.id,
        attributes=payload.attributes,
        source_category_id=payload.category_id,
        source_kind="PRODUCT_VERSION",
        source_reference=str(version.id),
    )

    audit(
        db,
        "PRODUCT_CREATED" if created_master else "PRODUCT_VERSION_CREATED",
        "ProductMaster",
        str(master.id),
        {"version": version_number, "category_id": payload.category_id},
        actor_user_id=actor_user_id,
    )
    db.commit()
    return master, version, created_master
