from __future__ import annotations

import atexit
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from threading import Lock

from sqlalchemy.orm import Session

from app.accounts.service import load_access_token
from app.catalog.service import get_category_metadata
from app.core.config import get_settings
from app.integrations.mercadolibre.client import MercadoLibreClient, MercadoLibreError
from app.persistence import DraftBatch, MercadoLibreAccount, ProductVersion, PublicationDraft
from app.publication.errors import provider_validation_issues
from app.publication.payload import build_item_payload
from app.publication.shipping import ShippingCapabilityError


@dataclass(frozen=True, slots=True)
class PublicationPreflightContext:
    access_token: str
    version: ProductVersion
    normalized_schema: dict
    seller_sku: str


_executor: ThreadPoolExecutor | None = None
_executor_size: int | None = None
_executor_lock = Lock()


def _get_preflight_executor() -> ThreadPoolExecutor:
    global _executor, _executor_size
    max_workers = max(1, min(12, int(get_settings().ml_preflight_concurrency)))
    with _executor_lock:
        if _executor is not None and _executor_size == max_workers:
            return _executor
        if _executor is not None:
            _executor.shutdown(wait=True, cancel_futures=False)
        _executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="ml-preflight",
        )
        _executor_size = max_workers
        return _executor


def _shutdown_preflight_executor() -> None:
    global _executor, _executor_size
    with _executor_lock:
        if _executor is not None:
            _executor.shutdown(wait=True, cancel_futures=False)
        _executor = None
        _executor_size = None


atexit.register(_shutdown_preflight_executor)


def build_preflight_context(db: Session, batch: DraftBatch) -> PublicationPreflightContext:
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
    return PublicationPreflightContext(
        access_token=access_token,
        version=version,
        normalized_schema=metadata.normalized_schema or {},
        seller_sku=version.master.internal_sku,
    )


def build_preflight_payload(
    context: PublicationPreflightContext,
    draft: PublicationDraft,
    image_urls: list[str],
) -> tuple[dict | None, list[dict]]:
    try:
        return (
            build_item_payload(
                context.version,
                draft,
                image_urls,
                seller_sku=context.seller_sku,
            ),
            [],
        )
    except ShippingCapabilityError as exc:
        return None, [{
            "code": "shipping.invalid_configuration",
            "field": "shipping",
            "message": str(exc),
        }]


def validate_preflight_payload(
    context: PublicationPreflightContext,
    payload: dict,
) -> list[dict]:
    try:
        MercadoLibreClient(context.access_token).validate_item(payload)
    except MercadoLibreError as exc:
        if exc.status_code in {400, 422}:
            return provider_validation_issues(exc.payload, context.normalized_schema)
        raise
    return []


def validate_preflight_payloads(
    context: PublicationPreflightContext,
    payloads_by_key: dict[object, dict],
) -> dict[object, list[dict]]:
    """Validate payloads with globally bounded concurrency.

    No SQLAlchemy session or ORM entity is touched inside worker threads. The
    provider client shares its pooled HTTP transport, while this executor caps
    aggregate preflight pressure for simultaneous operators.
    """

    if not payloads_by_key:
        return {}

    executor = _get_preflight_executor()
    futures: dict[Future[list[dict]], object] = {
        executor.submit(validate_preflight_payload, context, payload): key
        for key, payload in payloads_by_key.items()
    }
    results: dict[object, list[dict]] = {}
    for future, key in futures.items():
        results[key] = future.result()
    return results


def validate_draft_with_mercadolibre(
    db: Session,
    draft: PublicationDraft,
    image_urls: list[str],
) -> list[dict]:
    """Compatibility wrapper for validating one exact create-item payload."""

    batch = db.get(DraftBatch, draft.batch_id)
    if batch is None:
        raise RuntimeError("Draft batch not found during Mercado Libre preflight.")
    context = build_preflight_context(db, batch)
    payload, errors = build_preflight_payload(context, draft, image_urls)
    if errors or payload is None:
        return errors
    return validate_preflight_payload(context, payload)
