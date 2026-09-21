import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from app.accounts.service import load_access_token
from app.core.config import get_settings
from app.core.db import SessionLocal, reset_connection_pool
from app.core.enums import DraftStatus, JobItemStatus, JobStatus
from app.core.time import utcnow
from app.integrations.mercadolibre.client import MercadoLibreClient, MercadoLibreError
from app.persistence import (
    DraftBatch, Job, JobItem, ProductVersion, Publication, PublicationAttempt, PublicationDraft
)
from app.publication.errors import build_mercadolibre_error
from app.publication.payload import build_item_payload, publication_title_intent
from app.publication.quantity_pricing import (
    QuantityPricingSyncError,
    normalize_b2b_quantity_prices,
    sync_b2b_quantity_prices,
)
from app.products.storage import cleanup_temporary_product_images
from app.worker_runtime import heartbeat_worker, register_worker, unregister_worker

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ml-worker")
settings = get_settings()


def _db_retry_delay(attempt: int) -> float:
    base = max(0.1, float(settings.worker_db_retry_base_seconds))
    ceiling = max(base, float(settings.worker_db_retry_max_seconds))
    return min(ceiling, base * (2 ** max(0, attempt - 1)))


def _recover_db_connection(stage: str, exc: OperationalError, attempt: int) -> float:
    reset_connection_pool()
    delay = _db_retry_delay(attempt)
    logger.warning(
        "worker_database_unavailable stage=%s attempt=%d retry_in_seconds=%.1f error=%s",
        stage,
        attempt,
        delay,
        exc.__class__.__name__,
    )
    return delay


def _run_control_db_action(stage: str, action, *, max_attempts: int | None = None) -> None:
    """Retry idempotent worker-control DB operations without terminating the worker."""

    attempt = 0
    while True:
        attempt += 1
        try:
            with SessionLocal() as db:
                action(db)
            return
        except OperationalError as exc:
            if max_attempts is not None and attempt >= max_attempts:
                reset_connection_pool()
                raise
            time.sleep(_recover_db_connection(stage, exc, attempt))


def _reconcile_ambiguous_claim(job_id: uuid.UUID, claimed_at) -> bool:
    """Return whether a claim COMMIT that lost its response actually persisted.

    ``started_at`` is written by this exact claim before COMMIT, so matching both the
    job id and timestamp distinguishes our durable claim from another worker's claim.
    """

    attempt = 0
    while True:
        attempt += 1
        try:
            with SessionLocal() as db:
                job = db.get(Job, job_id)
                return bool(
                    job
                    and job.status == JobStatus.RUNNING
                    and job.started_at == claimed_at
                )
        except OperationalError as exc:
            time.sleep(_recover_db_connection("claim_reconcile", exc, attempt))


def claim_job():
    attempt = 0
    while True:
        attempt += 1
        try:
            with SessionLocal() as db:
                job = db.scalar(
                    select(Job)
                    .where(Job.status == JobStatus.PENDING)
                    .order_by(Job.created_at)
                    .with_for_update(skip_locked=True)
                    .limit(1)
                )
                if not job:
                    return None

                claimed_at = utcnow()
                job.status = JobStatus.RUNNING
                job.started_at = claimed_at
                job_id = job.id
                total = job.total
                try:
                    db.commit()
                except OperationalError as exc:
                    # The server can close the socket after receiving COMMIT. Do not
                    # blindly repeat the claim: first determine whether it persisted.
                    reset_connection_pool()
                    if _reconcile_ambiguous_claim(job_id, claimed_at):
                        logger.warning(
                            "publication_job_claim_reconciled job=%s reason=ambiguous_commit",
                            job_id,
                        )
                        return job_id
                    time.sleep(_recover_db_connection("claim_commit", exc, attempt))
                    continue

                logger.info("publication_job_claimed job=%s total=%d", job_id, total)
                return job_id
        except OperationalError as exc:
            time.sleep(_recover_db_connection("claim_select", exc, attempt))


def ordered_images_for_worker(version: ProductVersion, draft: PublicationDraft) -> list:
    """Return persisted product images in the exact draft publication order."""

    images = {str(image.id): image for image in version.images}
    return [
        image
        for image_id in draft.image_order
        if (image := images.get(str(image_id))) is not None
    ]


def _existing_confirmed_publication(db, draft_id):
    publication = db.scalar(select(Publication).where(Publication.draft_id == draft_id))
    if publication and publication.status == DraftStatus.PUBLISHED:
        return publication
    return None


def _picture_ids_for_images(
    client: MercadoLibreClient,
    ordered_images: list,
    picture_cache: dict[str, str],
) -> list[str]:
    """Upload each product image at most once per job and preserve per-draft order."""

    started = time.perf_counter()
    missing = {
        str(image.id): image
        for image in ordered_images
        if str(image.id) not in picture_cache
    }
    if missing:
        max_workers = max(1, min(settings.worker_image_upload_concurrency, len(missing)))
        first_error: MercadoLibreError | None = None
        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="ml-picture") as executor:
            futures = {
                executor.submit(
                    client.upload_item_picture,
                    image.storage_path,
                    image.mime_type,
                ): image_id
                for image_id, image in missing.items()
            }
            for future in as_completed(futures):
                image_id = futures[future]
                try:
                    picture_cache[image_id] = str(future.result()["id"])
                except MercadoLibreError as exc:
                    if first_error is None:
                        first_error = exc
        if first_error is not None:
            raise first_error

    logger.info(
        "publication_pictures_ready total=%d uploaded=%d reused=%d duration_ms=%d",
        len(ordered_images),
        len(missing),
        len(ordered_images) - len(missing),
        round((time.perf_counter() - started) * 1000),
    )
    return [picture_cache[str(image.id)] for image in ordered_images]


def _description_sync_status(publication: Publication) -> str:
    response = publication.external_response or {}
    sync = response.get("_description_sync") or {}
    return str(sync.get("status") or "").upper()


def _set_description_sync(publication: Publication, *, status: str, detail: dict | None = None) -> None:
    response = dict(publication.external_response or {})
    response["_description_sync"] = {"status": status, **(detail or {})}
    publication.external_response = response


def _sync_description(db, *, client: MercadoLibreClient, publication: Publication, version: ProductVersion, item: JobItem, draft: PublicationDraft, attempt: PublicationAttempt) -> tuple[bool, bool]:
    description = (version.description or "").strip()
    if not description:
        _set_description_sync(publication, status="NOT_REQUESTED")
        return True, False

    if _description_sync_status(publication) == "SYNCED":
        return True, False

    try:
        response = client.create_item_description(publication.item_id, description)
        _set_description_sync(
            publication,
            status="SYNCED",
            detail={"http_status": response.status_code},
        )
        db.commit()
        logger.info("publication_description_succeeded draft=%s item_id=%s", draft.id, publication.item_id)
        return True, False
    except MercadoLibreError as exc:
        retry = exc.retryable and item.attempts < settings.worker_max_attempts
        error = build_mercadolibre_error(exc, retryable=retry)
        error["code"] = "DESCRIPTION_SYNC_FAILED"
        _set_description_sync(
            publication,
            status="FAILED",
            detail={"http_status": exc.status_code, "error": error},
        )
        attempt.outcome = "DESCRIPTION_FAILED"
        attempt.http_status = exc.status_code
        attempt.response_payload = exc.payload
        attempt.retryable = retry
        item.last_error = error
        draft.last_error = error
        item.status = JobItemStatus.FAILED if not retry else JobItemStatus.RUNNING
        draft.status = DraftStatus.FAILED if not retry else DraftStatus.PUBLISHING
        db.commit()
        logger.error(
            "publication_description_failed draft=%s item_id=%s http_status=%s retryable=%s",
            draft.id,
            publication.item_id,
            exc.status_code,
            retry,
        )
        return False, retry


def _quantity_price_sync_status(publication: Publication) -> str:
    response = publication.external_response or {}
    sync = response.get("_quantity_price_sync") or {}
    return str(sync.get("status") or "").upper()


def _set_quantity_price_sync(publication: Publication, *, status: str, detail: dict | None = None) -> None:
    response = dict(publication.external_response or {})
    response["_quantity_price_sync"] = {"status": status, **(detail or {})}
    publication.external_response = response


def _sync_quantity_prices(
    db, *, client: MercadoLibreClient, publication: Publication, version: ProductVersion, draft: PublicationDraft
) -> dict | None:
    tiers = normalize_b2b_quantity_prices(version.commercial, base_price=version.price)
    if not tiers:
        _set_quantity_price_sync(publication, status="NOT_REQUESTED")
        db.commit()
        return None
    if _quantity_price_sync_status(publication) == "SYNCED":
        return None

    try:
        result = sync_b2b_quantity_prices(
            client,
            item_id=publication.item_id,
            tiers=tiers,
            currency_id=version.currency_id,
            base_price=version.price,
        )
        _set_quantity_price_sync(
            publication,
            status="SYNCED",
            detail={
                "http_status": result["http_status"],
                "model": "discount_percentage",
                "price_version": result["version"],
                "standard_amount": float(result["standard_amount"]),
                "tiers": [
                    {"min_purchase_unit": row["min_purchase_unit"], "amount": float(row["amount"])}
                    for row in tiers
                ],
                "price_per_quantity": result["request"].get("price_per_quantity") or [],
            },
        )
        db.commit()
        logger.info(
            "publication_quantity_prices_succeeded draft=%s item_id=%s tiers=%d",
            draft.id, publication.item_id, len(tiers),
        )
        return None
    except QuantityPricingSyncError as exc:
        error = {
            "code": "QUANTITY_PRICE_POLICY_CONFLICT",
            "message": str(exc),
            "retryable": False,
        }
        _set_quantity_price_sync(
            publication,
            status="FAILED",
            detail={"error": error},
        )
        db.commit()
        logger.warning(
            "publication_quantity_prices_policy_conflict draft=%s item_id=%s message=%s",
            draft.id, publication.item_id, str(exc),
        )
        return error
    except MercadoLibreError as exc:
        error = build_mercadolibre_error(exc, retryable=False)
        error["code"] = "QUANTITY_PRICE_SYNC_FAILED"
        _set_quantity_price_sync(
            publication,
            status="FAILED",
            detail={"http_status": exc.status_code, "error": error},
        )
        db.commit()
        logger.warning(
            "publication_quantity_prices_failed draft=%s item_id=%s http_status=%s message=%s",
            draft.id, publication.item_id, exc.status_code, error.get("message"),
        )
        return error


def _fail_without_retry(db, *, item, draft, attempt, outcome: str, code: str, message: str):
    attempt.outcome = outcome
    item.status = JobItemStatus.FAILED
    error = {"code": code, "message": message}
    item.last_error = error
    draft.last_error = error
    draft.status = DraftStatus.FAILED
    db.commit()
    logger.error(
        "publication_item_failed draft=%s sequence=%s code=%s message=%s",
        draft.id,
        draft.sequence_number,
        code,
        message,
    )
    return False, False


def process_item_once(
    item_id: uuid.UUID,
    picture_cache: dict[str, str],
) -> tuple[bool, bool]:
    """Return (success, should_retry).

    Network timeout after sending a publication is intentionally NOT retried:
    the external state is ambiguous and must be reconciled first.
    """
    with SessionLocal() as db:
        item = db.get(JobItem, item_id)
        draft = db.get(PublicationDraft, item.draft_id)
        batch = db.get(DraftBatch, draft.batch_id)
        version = db.get(ProductVersion, batch.product_version_id)

        existing_publication = _existing_confirmed_publication(db, draft.id)
        if existing_publication:
            item.status = JobItemStatus.RUNNING
            item.attempts += 1
            draft.status = DraftStatus.PUBLISHING
            attempt = PublicationAttempt(
                draft_id=draft.id,
                attempt_number=item.attempts,
                request_payload={"resume_publication_id": existing_publication.item_id},
                outcome="POST_PUBLICATION_RESUME_STARTED",
            )
            db.add(attempt)
            db.flush()
            token = load_access_token(db, batch.account_id)
            client = MercadoLibreClient(token)

            description_ok, description_retry = _sync_description(
                db, client=client, publication=existing_publication, version=version,
                item=item, draft=draft, attempt=attempt
            )
            if not description_ok:
                return False, description_retry

            quantity_warning = _sync_quantity_prices(
                db, client=client, publication=existing_publication, version=version, draft=draft
            )
            attempt.outcome = "SUCCEEDED_WITH_WARNING" if quantity_warning else "SUCCEEDED"
            item.status = JobItemStatus.SUCCEEDED
            draft.status = DraftStatus.PUBLISHED
            draft.last_error = None
            item.last_error = quantity_warning
            db.commit()
            logger.info("publication_item_already_confirmed draft=%s", draft.id)
            return True, False

        item.status = JobItemStatus.RUNNING
        item.attempts += 1
        draft.status = DraftStatus.PUBLISHING
        db.commit()
        logger.info(
            "publication_item_started job_item=%s draft=%s sequence=%d attempt=%d category=%s",
            item.id,
            draft.id,
            draft.sequence_number,
            item.attempts,
            version.category_id,
        )

        ordered_images = ordered_images_for_worker(version, draft)
        payload = build_item_payload(
            version,
            draft,
            [],
            seller_sku=version.master.internal_sku,
        )
        attempt = PublicationAttempt(
            draft_id=draft.id,
            attempt_number=item.attempts,
            request_payload=payload,
            outcome="STARTED",
        )
        db.add(attempt)
        db.flush()

        if not settings.ml_live_publication_enabled:
            return _fail_without_retry(
                db,
                item=item,
                draft=draft,
                attempt=attempt,
                outcome="BLOCKED_BY_FEATURE_FLAG",
                code="LIVE_PUBLICATION_DISABLED",
                message="Live publication is disabled by configuration.",
            )

        if not ordered_images:
            return _fail_without_retry(
                db,
                item=item,
                draft=draft,
                attempt=attempt,
                outcome="MISSING_IMAGES",
                code="PUBLICATION_IMAGES_REQUIRED",
                message="La publicación live necesita al menos una imagen guardada en el producto.",
            )

        missing_files = [image.original_name for image in ordered_images if not Path(image.storage_path).is_file()]
        if missing_files:
            return _fail_without_retry(
                db,
                item=item,
                draft=draft,
                attempt=attempt,
                outcome="MISSING_IMAGE_FILES",
                code="PUBLICATION_IMAGE_FILE_MISSING",
                message=f"No se encuentran {len(missing_files)} archivos de imagen guardados localmente.",
            )

        token = load_access_token(db, batch.account_id)
        client = MercadoLibreClient(token)

        # Persist a durable checkpoint before external side effects.
        db.commit()

        try:
            uploaded_picture_ids = _picture_ids_for_images(
                client,
                ordered_images,
                picture_cache,
            )
            payload = build_item_payload(
                version,
                draft,
                [{"id": picture_id} for picture_id in uploaded_picture_ids],
                seller_sku=version.master.internal_sku,
            )
            attempt = db.get(PublicationAttempt, attempt.id)
            attempt.request_payload = payload
            db.commit()
            logger.info(
                "publication_request_started draft=%s sequence=%d images=%d payload_fields=%s commercial_intent=%s",
                draft.id,
                draft.sequence_number,
                len(uploaded_picture_ids),
                sorted(payload.keys()),
                (draft.commercial_config or {}).get("commercial_intent"),
            )
            response = client.create_item(payload)
            attempt = db.get(PublicationAttempt, attempt.id)
            item = db.get(JobItem, item.id)
            draft = db.get(PublicationDraft, draft.id)
            attempt.http_status = response.status_code
            attempt.response_payload = response.payload
            attempt.outcome = "SUCCEEDED"

            publication = Publication(
                draft_id=draft.id,
                account_id=batch.account_id,
                status=DraftStatus.PUBLISHED,
                item_id=response.payload.get("id"),
                user_product_id=response.payload.get("user_product_id"),
                external_response=response.payload,
                published_at=utcnow(),
            )
            _set_description_sync(
                publication,
                status="PENDING" if (version.description or "").strip() else "NOT_REQUESTED",
            )
            db.add(publication)
            db.commit()

            description_ok, description_retry = _sync_description(
                db, client=client, publication=publication, version=version,
                item=item, draft=draft, attempt=attempt
            )
            if not description_ok:
                return False, description_retry

            quantity_warning = _sync_quantity_prices(
                db, client=client, publication=publication, version=version, draft=draft
            )
            draft.status = DraftStatus.PUBLISHED
            draft.last_error = None
            item.status = JobItemStatus.SUCCEEDED
            item.last_error = quantity_warning
            db.commit()
            returned_title = str(response.payload.get("title") or "").strip()
            intended_title = publication_title_intent(draft)
            logger.info(
                "publication_request_succeeded draft=%s sequence=%d http_status=%s item_id=%s "
                "user_product_id=%s returned_title_matches_intent=%s returned_title=%s",
                draft.id,
                draft.sequence_number,
                response.status_code,
                response.payload.get("id"),
                response.payload.get("user_product_id"),
                bool(returned_title and returned_title.casefold() == intended_title.casefold()),
                returned_title or None,
            )
            return True, False

        except MercadoLibreError as exc:
            attempt = db.get(PublicationAttempt, attempt.id)
            item = db.get(JobItem, item.id)
            draft = db.get(PublicationDraft, draft.id)
            attempt.http_status = exc.status_code
            attempt.response_payload = exc.payload
            attempt.retryable = exc.retryable

            ambiguous = exc.status_code is None
            if ambiguous:
                attempt.outcome = "UNKNOWN_EXTERNAL_STATE"
                draft.status = DraftStatus.UNKNOWN_EXTERNAL_STATE
                item.status = JobItemStatus.UNKNOWN
                retry = False
            else:
                attempt.outcome = "FAILED"
                draft.status = DraftStatus.FAILED
                item.status = JobItemStatus.FAILED
                retry = exc.retryable and item.attempts < settings.worker_max_attempts

            error = build_mercadolibre_error(exc, retryable=retry)
            draft.last_error = error
            item.last_error = error
            db.commit()

            causes = error.get("causes") or []
            logger.error(
                "publication_request_failed draft=%s sequence=%d http_status=%s retryable=%s ambiguous=%s "
                "api_error=%s api_message=%s cause_count=%d",
                draft.id,
                draft.sequence_number,
                exc.status_code,
                retry,
                ambiguous,
                error.get("provider_error"),
                error.get("message"),
                len(causes),
            )
            for index, cause in enumerate(causes, start=1):
                logger.error(
                    "publication_rejection_cause draft=%s sequence=%d cause=%d code=%s field=%s type=%s message=%s",
                    draft.id,
                    draft.sequence_number,
                    index,
                    cause.get("code"),
                    cause.get("field"),
                    cause.get("type"),
                    cause.get("message"),
                )
            return False, retry


def process_item(item_id: uuid.UUID, picture_cache: dict[str, str]) -> bool:
    while True:
        success, retry = process_item_once(item_id, picture_cache)
        if success:
            return True
        if not retry:
            return False
        with SessionLocal() as db:
            item = db.get(JobItem, item_id)
            attempt_no = item.attempts
        delay = settings.worker_base_backoff_seconds * (2 ** max(0, attempt_no - 1))
        logger.warning("publication_retry_scheduled job_item=%s delay_seconds=%.1f next_attempt=%d", item_id, delay, attempt_no + 1)
        time.sleep(delay)


def process_job(job_id: uuid.UUID, *, worker_instance_id: uuid.UUID):
    with SessionLocal() as db:
        item_ids = db.scalars(
            select(JobItem.id)
            .where(JobItem.job_id == job_id, JobItem.status == JobItemStatus.PENDING)
            .order_by(JobItem.id)
        ).all()

    picture_cache: dict[str, str] = {}
    for item_id in item_ids:
        _run_control_db_action(
            "job_heartbeat_before_item",
            lambda db: heartbeat_worker(db, instance_id=worker_instance_id),
        )
        ok = process_item(item_id, picture_cache)
        with SessionLocal() as db:
            heartbeat_worker(db, instance_id=worker_instance_id)
            job = db.get(Job, job_id)
            job.processed += 1
            if ok:
                job.succeeded += 1
            else:
                job.failed += 1
            db.commit()
            logger.info(
                "publication_job_progress job=%s processed=%d total=%d succeeded=%d failed=%d",
                job.id,
                job.processed,
                job.total,
                job.succeeded,
                job.failed,
            )

    with SessionLocal() as db:
        job = db.get(Job, job_id)
        job.finished_at = utcnow()
        if job.failed == 0:
            job.status = JobStatus.COMPLETED
        elif job.succeeded > 0:
            job.status = JobStatus.PARTIAL
        else:
            job.status = JobStatus.FAILED

        deleted_files = 0
        deleted_bytes = 0
        if job.status == JobStatus.COMPLETED and settings.cleanup_uploads_after_success:
            version_ids = db.scalars(
                select(DraftBatch.product_version_id)
                .join(PublicationDraft, PublicationDraft.batch_id == DraftBatch.id)
                .join(JobItem, JobItem.draft_id == PublicationDraft.id)
                .where(JobItem.job_id == job.id)
                .distinct()
            ).all()
            for version_id in version_ids:
                version = db.get(ProductVersion, version_id)
                if version is None:
                    continue
                removed_count, removed_bytes = cleanup_temporary_product_images(
                    version.images, settings.upload_dir
                )
                deleted_files += removed_count
                deleted_bytes += removed_bytes

        db.commit()
        logger.info(
            "publication_job_finished job=%s status=%s succeeded=%d failed=%d "
            "temporary_uploads_deleted=%d temporary_upload_bytes_deleted=%d",
            job.id,
            job.status,
            job.succeeded,
            job.failed,
            deleted_files,
            deleted_bytes,
        )


def run():
    instance_id = uuid.uuid4()
    _run_control_db_action(
        "register",
        lambda db: register_worker(db, instance_id=instance_id),
    )
    logger.info(
        "publication_worker_started instance=%s poll_seconds=%.1f live_enabled=%s",
        instance_id,
        settings.worker_poll_seconds,
        settings.ml_live_publication_enabled,
    )
    try:
        while True:
            _run_control_db_action(
                "heartbeat",
                lambda db: heartbeat_worker(db, instance_id=instance_id),
            )
            job_id = claim_job()
            if job_id:
                process_job(job_id, worker_instance_id=instance_id)
            else:
                time.sleep(settings.worker_poll_seconds)
    finally:
        try:
            _run_control_db_action(
                "unregister",
                lambda db: unregister_worker(db, instance_id=instance_id),
                max_attempts=1,
            )
        except Exception:
            logger.exception("publication_worker_unregister_failed instance=%s", instance_id)


if __name__ == "__main__":
    run()
