import hashlib
import logging
import time
import uuid

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.accounts.service import load_access_token
from app.audit.service import audit
from app.catalog.service import get_category_metadata
from app.core.config import get_settings
from app.core.enums import DraftStatus
from app.drafts.image_ordering import generate_image_orders
from app.drafts.intelligence import score_title, validate_title_set
from app.integrations.openai.titles import OpenAIProviderError, OpenAITitleGenerator
from app.keywords.service import KeywordResearchError, build_ml_keyword_snapshot
from app.technical_attributes.service import upsert_product_attributes
from app.publication.commercial import (
    WITH_INSTALLMENTS,
    commercial_sequence,
    fetch_commercial_options,
    normalize_commercial_distribution,
)
from app.persistence import (
    DraftBatch,
    JobItem,
    MercadoLibreAccount,
    ProductImage,
    ProductVersion,
    PublicationDraft,
    TitleGenerationRun,
    ValidationResult,
)

logger = logging.getLogger("ml-draft-generation")
performance_logger = logging.getLogger("title-performance")


def _max_title_length(category_raw: dict) -> int:
    settings = category_raw.get("settings") or {}
    value = settings.get("max_title_length")
    if isinstance(value, int) and value > 0:
        return value
    return 60


def generate_drafts(
    db: Session,
    *,
    product_version_id: uuid.UUID,
    account_id: uuid.UUID,
    count: int,
    commercial_distribution: list[dict] | None = None,
    actor_user_id: uuid.UUID | None = None,
    reserved_titles: set[str] | None = None,
    commit: bool = True,
) -> DraftBatch:
    started = time.perf_counter()
    if count < 1 or count > 100:
        raise HTTPException(status_code=422, detail="V1 supports 1..100 drafts per batch.")

    version = db.get(ProductVersion, product_version_id)
    if not version:
        raise HTTPException(status_code=404, detail="Product version not found.")
    if not version.images:
        # Reject before keyword research/OpenAI so an incomplete upload cannot
        # consume provider calls or produce drafts with an empty image order.
        raise HTTPException(
            status_code=422,
            detail="Cargá al menos una imagen confirmada por el backend antes de generar borradores.",
        )

    logger.info(
        "draft_generation_started product_version=%s account=%s requested=%d category=%s",
        product_version_id,
        account_id,
        count,
        version.category_id,
    )
    access_token = load_access_token(db, account_id)
    account = db.get(MercadoLibreAccount, account_id)
    if not account or not account.seller_id:
        raise HTTPException(status_code=422, detail="La cuenta seleccionada no tiene seller_id disponible.")

    commercial_options = fetch_commercial_options(
        access_token=access_token,
        seller_id=account.seller_id,
        category_id=version.category_id,
        site_id=account.site_id or get_settings().ml_site_id,
    )
    normalized_distribution = normalize_commercial_distribution(
        count=count, requested=commercial_distribution, options=commercial_options
    )
    commercial_by_draft = commercial_sequence(normalized_distribution)

    metadata = get_category_metadata(
        db, version.category_id, get_settings().ml_site_id, access_token=access_token
    )
    logger.info(
        "draft_generation_metadata_ready product_version=%s category=%s",
        product_version_id,
        version.category_id,
    )
    try:
        keyword_snapshot = build_ml_keyword_snapshot(
            db,
            version=version,
            site_id=get_settings().ml_site_id,
            category_name=metadata.category_name,
            access_token=access_token,
        )
    except KeywordResearchError as exc:
        db.rollback()
        logger.warning(
            "draft_generation_keyword_failed product_version=%s code=%s retryable=%s",
            product_version_id,
            exc.code,
            exc.retryable,
        )
        raise HTTPException(
            status_code=424,
            detail={"code": exc.code, "message": str(exc), "retryable": exc.retryable},
        ) from exc

    keywords = list(keyword_snapshot.keywords)
    generator = OpenAITitleGenerator()
    requested_candidates = min(max(count * 2, count + 4), 200)
    max_len = _max_title_length(metadata.raw_category)
    try:
        result, provider = generator.generate(
            category_name=metadata.category_name,
            product_name=version.title_reference,
            description=version.description,
            attributes=version.attributes,
            discovery_context=version.discovery_context,
            keywords=keywords,
            count=requested_candidates,
            max_length=max_len,
        )
    except OpenAIProviderError as exc:
        db.rollback()
        logger.warning(
            "draft_generation_ai_failed product_version=%s code=%s retryable=%s",
            product_version_id,
            exc.code,
            exc.retryable,
        )
        raise HTTPException(
            status_code=424,
            detail={"code": exc.code, "message": str(exc), "retryable": exc.retryable},
        ) from exc

    generation_run = TitleGenerationRun(
        keyword_snapshot_id=keyword_snapshot.id,
        model=provider["model"],
        prompt_version=generator.prompt_version,
        requested_count=requested_candidates,
        provider_request_id=provider.get("request_id"),
        usage=provider.get("usage") or {},
    )
    db.add(generation_run)
    db.flush()

    raw_titles = [x.title for x in result.titles]
    ranked_candidates = sorted(
        (t for t in raw_titles if len(t) <= max_len),
        key=lambda title: score_title(title, keywords, max_len),
        reverse=True,
    )
    accepted = validate_title_set(ranked_candidates)
    # Never reuse a title already persisted for this product, and allow a caller
    # orchestrating multiple accounts to reserve titles across all batches in-memory.
    product_master_id = version.product_master_id
    persisted_titles = set(
        title.casefold().strip()
        for title in db.scalars(
            select(PublicationDraft.title)
            .join(DraftBatch, DraftBatch.id == PublicationDraft.batch_id)
            .join(ProductVersion, ProductVersion.id == DraftBatch.product_version_id)
            .where(ProductVersion.product_master_id == product_master_id)
        ).all()
        if title
    )
    reserved = reserved_titles if reserved_titles is not None else set()
    used = persisted_titles | {title.casefold().strip() for title in reserved}
    accepted = [title for title in accepted if title.casefold().strip() not in used]
    logger.info(
        "draft_generation_titles_ranked product_version=%s received=%d valid_distinct=%d selected=%d",
        product_version_id,
        len(raw_titles),
        len(accepted),
        min(len(accepted), count),
    )
    if len(accepted) < count:
        db.rollback()
        raise HTTPException(
            status_code=422,
            detail=(
                f"OpenAI produced only {len(accepted)} sufficiently distinct valid titles "
                f"for {count} requested drafts. Regenerate with richer product data."
            ),
        )

    batch = DraftBatch(
        product_version_id=version.id,
        account_id=account_id,
        requested_count=count,
        commercial_distribution=normalized_distribution,
    )
    db.add(batch)
    db.flush()

    selected_titles = accepted[:count]
    reserved.update(title.casefold().strip() for title in selected_titles)

    image_orders = generate_image_orders(
        [img.id for img in sorted(version.images, key=lambda x: x.position)],
        count,
        str(batch.id),
    )
    for index, title in enumerate(selected_titles, start=1):
        commercial_choice = commercial_by_draft[index - 1]
        idem = hashlib.sha256(f"{account_id}:{batch.id}:{index}".encode()).hexdigest()
        db.add(
            PublicationDraft(
                batch_id=batch.id,
                sequence_number=index,
                title=title,
                title_score=score_title(title, keywords, max_len),
                commercial_config={
                    "commercial_intent": commercial_choice["commercial_intent"],
                    "commercial_label": commercial_choice["label"],
                    "listing_type_id": commercial_choice["listing_type_id"],
                    "listing_type_name": commercial_choice["listing_type_name"],
                    "financing_resolution": "RESOLVED",
                    "installment_offer": (
                        "ADD_INSTALLMENTS"
                        if commercial_choice["commercial_intent"] == WITH_INSTALLMENTS
                        else "DO_NOT_ADD_INSTALLMENTS"
                    ),
                    "naming_contract": "FAMILY_NAME_FROM_TITLE_INTENT",
                },
                status=DraftStatus.GENERATED,
                image_order=image_orders[index - 1],
                title_generation_run_id=generation_run.id,
                idempotency_key=idem,
            )
        )

    audit(
        db,
        "DRAFT_BATCH_GENERATED",
        "DraftBatch",
        str(batch.id),
        {
            "count": count,
            "product_version_id": str(version.id),
            "commercial_distribution": normalized_distribution,
        },
        actor_user_id=actor_user_id,
    )
    if commit:
        db.commit()
        db.refresh(batch)
    else:
        db.flush()
    logger.info("draft_generation_completed batch=%s drafts=%d", batch.id, count)
    performance_logger.info(
        "title_generation_completed batch=%s drafts=%d total_ms=%d",
        batch.id,
        count,
        round((time.perf_counter() - started) * 1000),
    )
    return batch


def rebase_batch_product_version(
    db: Session,
    *,
    batch_id: uuid.UUID,
    expected_product_version_id: uuid.UUID,
    authorization,
    actor_user_id: uuid.UUID,
    description: str,
    price: float,
    quantity: int,
    attributes: dict,
    commercial: dict,
    logistics: dict,
) -> ProductVersion:
    """Create a corrected immutable product snapshot and attach an editable batch to it.

    Draft titles and their generation evidence are intentionally preserved. This operation
    exists only for pre-publication corrections discovered by validation (for example,
    required measurements/units). It never mutates an existing ProductVersion.
    """
    batch = db.scalar(select(DraftBatch).where(DraftBatch.id == batch_id).with_for_update())
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found.")

    # The callback locks ProductMaster and validates ownership/session/fencing token.
    # The master row stays locked through the commit below.
    current = db.get(ProductVersion, batch.product_version_id)
    if current is None:
        raise HTTPException(status_code=409, detail="Product version for batch not found.")
    authorization(current.product_master_id)
    if current.id != expected_product_version_id:
        raise HTTPException(status_code=409, detail="El lote cambió de versión; volvé a cargarlo")
    latest = db.scalar(select(func.max(ProductVersion.version_number)).where(
        ProductVersion.product_master_id == current.product_master_id
    )) or 0
    if latest != current.version_number:
        raise HTTPException(status_code=409, detail="La ficha cambió desde que se generó el lote; revisá la versión vigente")

    drafts = list(batch.drafts)
    draft_ids = [draft.id for draft in drafts]
    if any(draft.status in {DraftStatus.PUBLISHING, DraftStatus.PUBLISHED, DraftStatus.UNKNOWN_EXTERNAL_STATE} for draft in drafts):
        raise HTTPException(
            status_code=409,
            detail="No se puede corregir la ficha de un lote que ya inició una publicación externa.",
        )

    if draft_ids:
        existing_job_item = db.scalar(
            select(JobItem.id)
            .join(PublicationDraft, PublicationDraft.id == JobItem.draft_id)
            .where(PublicationDraft.id.in_(draft_ids))
            .limit(1)
        )
        if existing_job_item:
            raise HTTPException(
                status_code=409,
                detail=(
                    "El lote ya tiene ejecución de publicación asociada. "
                    "No se puede reemplazar su snapshot de producto de forma segura."
                ),
            )

    next_version_number = latest + 1

    corrected = ProductVersion(
        product_master_id=current.product_master_id,
        version_number=next_version_number,
        category_id=current.category_id,
        title_reference=current.title_reference,
        description=description,
        price=price,
        quantity=quantity,
        condition=current.condition,
        currency_id=current.currency_id,
        listing_type_id=current.listing_type_id,
        attributes=attributes,
        commercial=commercial,
        logistics=logistics,
        # Title-generation context stays frozen because the generated titles are reused.
        discovery_context=current.discovery_context or {},
    )
    db.add(corrected)
    db.flush()
    upsert_product_attributes(
        db,
        product_master_id=corrected.product_master_id,
        attributes=corrected.attributes or {},
        source_category_id=corrected.category_id,
        source_kind="PRODUCT_VERSION",
        source_reference=str(corrected.id),
    )

    image_id_map: dict[str, str] = {}
    for image in sorted(current.images, key=lambda item: item.position):
        cloned = ProductImage(
            product_version_id=corrected.id,
            original_name=image.original_name,
            storage_path=image.storage_path,
            mime_type=image.mime_type,
            position=image.position,
        )
        db.add(cloned)
        db.flush()
        image_id_map[str(image.id)] = str(cloned.id)

    batch.product_version_id = corrected.id
    if draft_ids:
        db.query(ValidationResult).filter(ValidationResult.draft_id.in_(draft_ids)).delete(
            synchronize_session=False
        )

    reset_count = 0
    for draft in drafts:
        if draft.status == DraftStatus.EXCLUDED:
            continue
        draft.image_order = [image_id_map.get(str(image_id), str(image_id)) for image_id in (draft.image_order or [])]
        draft.status = DraftStatus.GENERATED
        draft.last_error = None
        reset_count += 1

    audit(
        db,
        "DRAFT_BATCH_PRODUCT_VERSION_REBASED",
        "DraftBatch",
        str(batch.id),
        {
            "previous_product_version_id": str(current.id),
            "product_version_id": str(corrected.id),
            "version_number": next_version_number,
            "reset_drafts": reset_count,
            "reason": "PREPUBLICATION_VALIDATION_CORRECTION",
        },
        actor_user_id=actor_user_id,
    )
    db.commit()
    db.refresh(corrected)
    return corrected


def rebase_batches_product_version(
    db: Session,
    *,
    batch_ids: list[uuid.UUID],
    expected_product_version_id: uuid.UUID,
    authorization,
    actor_user_id: uuid.UUID,
    description: str,
    price: float,
    quantity: int,
    attributes: dict,
    commercial: dict,
    logistics: dict,
) -> ProductVersion:
    """Rebase several account batches onto one corrected immutable product version.

    This is the multi-account counterpart of ``rebase_batch_product_version``. It
    creates exactly one corrected snapshot and atomically repoints every selected
    pre-publication batch to it, preserving independent drafts/titles per account.
    """
    unique_ids = list(dict.fromkeys(batch_ids))
    if not unique_ids:
        raise HTTPException(status_code=422, detail="Indicá al menos un lote.")

    batches = list(db.scalars(
        select(DraftBatch)
        .where(DraftBatch.id.in_(unique_ids))
        .order_by(DraftBatch.id)
        .with_for_update()
    ).all())
    if len(batches) != len(unique_ids):
        raise HTTPException(status_code=404, detail="Uno o más lotes no existen.")
    current_ids = {batch.product_version_id for batch in batches}
    if current_ids != {expected_product_version_id}:
        raise HTTPException(
            status_code=409,
            detail="Los lotes no comparten la versión esperada; recargá la operación multicuenta.",
        )
    current = db.get(ProductVersion, expected_product_version_id)
    if current is None:
        raise HTTPException(status_code=409, detail="Product version for batches not found.")
    authorization(current.product_master_id)
    latest = db.scalar(select(func.max(ProductVersion.version_number)).where(
        ProductVersion.product_master_id == current.product_master_id
    )) or 0
    if latest != current.version_number:
        raise HTTPException(
            status_code=409,
            detail="La ficha cambió desde que se generaron los lotes; revisá la versión vigente",
        )

    drafts = [draft for batch in batches for draft in list(batch.drafts)]
    if any(draft.status in {
        DraftStatus.PUBLISHING, DraftStatus.PUBLISHED, DraftStatus.UNKNOWN_EXTERNAL_STATE
    } for draft in drafts):
        raise HTTPException(
            status_code=409,
            detail="No se puede corregir una operación multicuenta que ya inició una publicación externa.",
        )
    draft_ids = [draft.id for draft in drafts]
    if draft_ids:
        existing_job_item = db.scalar(
            select(JobItem.id)
            .where(JobItem.draft_id.in_(draft_ids))
            .limit(1)
        )
        if existing_job_item:
            raise HTTPException(
                status_code=409,
                detail="La operación ya tiene ejecución asociada y no puede reemplazar su snapshot.",
            )

    corrected = ProductVersion(
        product_master_id=current.product_master_id,
        version_number=latest + 1,
        category_id=current.category_id,
        title_reference=current.title_reference,
        description=description,
        price=price,
        quantity=quantity,
        condition=current.condition,
        currency_id=current.currency_id,
        listing_type_id=current.listing_type_id,
        attributes=attributes,
        commercial=commercial,
        logistics=logistics,
        discovery_context=current.discovery_context or {},
    )
    db.add(corrected)
    db.flush()
    upsert_product_attributes(
        db,
        product_master_id=corrected.product_master_id,
        attributes=corrected.attributes or {},
        source_category_id=corrected.category_id,
        source_kind="PRODUCT_VERSION",
        source_reference=str(corrected.id),
    )

    image_id_map: dict[str, str] = {}
    for image in sorted(current.images, key=lambda item: item.position):
        cloned = ProductImage(
            product_version_id=corrected.id,
            original_name=image.original_name,
            storage_path=image.storage_path,
            mime_type=image.mime_type,
            position=image.position,
        )
        db.add(cloned)
        db.flush()
        image_id_map[str(image.id)] = str(cloned.id)

    if draft_ids:
        db.query(ValidationResult).filter(ValidationResult.draft_id.in_(draft_ids)).delete(
            synchronize_session=False
        )
    reset_count = 0
    for batch in batches:
        batch.product_version_id = corrected.id
        for draft in batch.drafts:
            if draft.status == DraftStatus.EXCLUDED:
                continue
            draft.image_order = [
                image_id_map.get(str(image_id), str(image_id))
                for image_id in (draft.image_order or [])
            ]
            draft.status = DraftStatus.GENERATED
            draft.last_error = None
            reset_count += 1

    audit(
        db,
        "DRAFT_MULTI_BATCH_PRODUCT_VERSION_REBASED",
        "ProductVersion",
        str(corrected.id),
        {
            "batch_ids": [str(batch.id) for batch in batches],
            "previous_product_version_id": str(current.id),
            "product_version_id": str(corrected.id),
            "version_number": corrected.version_number,
            "reset_drafts": reset_count,
            "reason": "PREPUBLICATION_VALIDATION_CORRECTION",
        },
        actor_user_id=actor_user_id,
    )
    db.commit()
    db.refresh(corrected)
    return corrected
