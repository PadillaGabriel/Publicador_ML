from datetime import timedelta

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.catalog.normalization import (
    NORMALIZED_SCHEMA_VERSION,
    category_is_publishable_leaf,
    normalize_attributes,
)
from app.core.config import get_settings
from app.core.time import utcnow
from app.integrations.mercadolibre.client import MercadoLibreClient
from app.persistence import CategoryMetadataSnapshot


def get_category_metadata(
    db: Session,
    category_id: str,
    site_id: str = "MLA",
    force_refresh: bool = False,
    access_token: str | None = None,
) -> CategoryMetadataSnapshot:
    now = utcnow()
    latest = db.scalar(
        select(CategoryMetadataSnapshot)
        .where(
            CategoryMetadataSnapshot.site_id == site_id,
            CategoryMetadataSnapshot.category_id == category_id,
        )
        .order_by(desc(CategoryMetadataSnapshot.fetched_at))
        .limit(1)
    )
    if latest and not force_refresh and latest.expires_at > now:
        # Normalization rules evolve independently from Mercado Libre metadata TTL.
        # Rebuild the local schema from the persisted raw provider payload when the
        # schema version changes; this avoids stale UI contracts without an extra
        # external request.
        if (latest.normalized_schema or {}).get("schema_version") != NORMALIZED_SCHEMA_VERSION:
            latest.normalized_schema = normalize_attributes(
                latest.raw_attributes or [], latest.raw_category
            )
            db.commit()
            db.refresh(latest)
        return latest

    client = MercadoLibreClient(access_token)
    category = client.category(category_id)
    attributes = client.category_attributes(category_id)
    ttl = get_settings().ml_metadata_ttl_seconds
    snapshot = CategoryMetadataSnapshot(
        site_id=site_id,
        category_id=category_id,
        category_name=category.get("name") or category_id,
        raw_category=category,
        raw_attributes=attributes,
        normalized_schema=normalize_attributes(attributes, category),
        fetched_at=now,
        expires_at=now + timedelta(seconds=ttl),
    )
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return snapshot


def metadata_is_publishable_leaf(snapshot: CategoryMetadataSnapshot) -> bool:
    return category_is_publishable_leaf(snapshot.raw_category)
