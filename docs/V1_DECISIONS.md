# V1 Engineering Decisions

## Publication safety

Live publication is disabled by default. This is intentional.

The V1 implements the `/items` publishing adapter behind a feature flag, while the domain retains
`item_id` and optional `user_product_id`. This avoids coupling the entire application to one external
identity model.

## Dynamic metadata

Category metadata comes from Mercado Libre and is cached in PostgreSQL. The frontend renders
attributes from the normalized schema.

## Images

The administrative UI can serve local images for preview. Mercado Libre live publication normally
needs publicly reachable HTTPS picture sources. For live mode the worker reads
`logistics.public_image_base_url`. A production deployment should put uploaded images behind a
public object store/CDN or HTTPS application endpoint before enabling live publication.

## Keyword intelligence

V1 intentionally does not scrape Mercado Libre. Keyword evidence begins with first-party product
data and category attributes. The architecture preserves `KeywordSnapshot` so legitimate external
signals can be added later.

## Reconciliation

Timeouts are persisted as `UNKNOWN_EXTERNAL_STATE`, rather than blindly retried. Automatic
reconciliation is intentionally not guessed because it depends on the exact marketplace contract
available to the seller/account. A follow-up hardening phase should implement the verified lookup
strategy for the target accounts before high-volume live publication.

## Alembic

The initial migration creates the complete V1 schema from the versioned ORM metadata. Future
production schema changes should be explicit Alembic revisions.
