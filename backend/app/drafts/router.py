import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import audit
from app.core.db import get_db
from app.core.enums import DraftStatus
from app.drafts.service import generate_drafts, rebase_batch_product_version, rebase_batches_product_version
from app.drafts.validation_service import (
    approve_ready_drafts,
    validate_batch_drafts,
    validate_single_draft,
)
from app.integrations.mercadolibre.client import MercadoLibreError
from app.operator_auth import request_identity
from app.product_edit_leases import require_edit_token
from app.persistence import (
    DraftBatch, KeywordSnapshot, ProductMaster, ProductVersion, PublicationDraft, TitleGenerationRun, ValidationResult
)

router = APIRouter(prefix="/api/drafts", tags=["drafts"])


class CommercialAllocation(BaseModel):
    commercial_intent: str = Field(min_length=1, max_length=40)
    count: int = Field(ge=0, le=100)


class GenerateRequest(BaseModel):
    product_version_id: uuid.UUID
    account_id: uuid.UUID
    count: int = Field(ge=1, le=100)
    commercial_distribution: list[CommercialAllocation] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_distribution(self):
        intents = [p.commercial_intent for p in self.commercial_distribution if p.count > 0]
        if len(intents) != len(set(intents)):
            raise ValueError("No repitas la misma modalidad de cuotas en la distribución.")
        if self.commercial_distribution and sum(p.count for p in self.commercial_distribution) != self.count:
            raise ValueError("La distribución comercial debe sumar exactamente el total de publicaciones.")
        return self


class GenerateMultiRequest(BaseModel):
    product_version_id: uuid.UUID
    account_ids: list[uuid.UUID] = Field(min_length=1, max_length=20)
    count: int = Field(ge=1, le=100)
    commercial_distribution: list[CommercialAllocation] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_request(self):
        if len(self.account_ids) != len(set(self.account_ids)):
            raise ValueError("No repitas cuentas en una publicación multicuenta.")
        intents = [p.commercial_intent for p in self.commercial_distribution if p.count > 0]
        if len(intents) != len(set(intents)):
            raise ValueError("No repitas la misma modalidad de cuotas en la distribución.")
        if self.commercial_distribution and sum(p.count for p in self.commercial_distribution) != self.count:
            raise ValueError("La distribución comercial debe sumar exactamente el total por cuenta.")
        return self


class BatchProductCorrection(BaseModel):
    description: str = ""
    price: float = Field(gt=0)
    quantity: int = Field(ge=0)
    attributes: dict = Field(default_factory=dict)
    commercial: dict = Field(default_factory=dict)
    logistics: dict = Field(default_factory=dict)


class DraftCommercialUpdate(BaseModel):
    price_override: float | None = Field(default=None, gt=0)
    installments_count: int | None = None
    installment_increment_pct: float | None = Field(default=None, ge=0, lt=100)

    @model_validator(mode="after")
    def validate_installments(self):
        if self.installments_count not in (None, 3, 6):
            raise ValueError("installments_count debe ser 3 o 6.")
        if self.installments_count is None and self.installment_increment_pct is not None:
            raise ValueError("Indicá installments_count para aplicar un incremento.")
        return self


class MultiBatchProductCorrection(BatchProductCorrection):
    batch_ids: list[uuid.UUID] = Field(min_length=1, max_length=20)


class TitleUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=255)


@router.post("/generate")
def generate(payload: GenerateRequest, request: Request, db: Session = Depends(get_db)):
    actor, _ = request_identity(db, request)
    batch = generate_drafts(
        db,
        actor_user_id=actor.id,
        product_version_id=payload.product_version_id,
        account_id=payload.account_id,
        count=payload.count,
        commercial_distribution=[p.model_dump() for p in payload.commercial_distribution],
    )
    return {
        "batch_id": batch.id,
        "count": batch.requested_count,
        "commercial_distribution": [
            {
                "commercial_intent": d.commercial_config.get("commercial_intent"),
                "label": d.commercial_config.get("commercial_label"),
                "listing_type_id": d.commercial_config.get("listing_type_id"),
                "listing_type_name": d.commercial_config.get("listing_type_name"),
            }
            for d in batch.drafts
        ],
    }


@router.post("/generate-multi")
def generate_multi(payload: GenerateMultiRequest, request: Request, db: Session = Depends(get_db)):
    actor, _ = request_identity(db, request)
    version = db.get(ProductVersion, payload.product_version_id)
    if version is None:
        raise HTTPException(status_code=404, detail="Product version not found.")

    # Serialize title reservation for the same master product for the duration of
    # the complete multi-account generation transaction.
    db.scalar(
        select(ProductMaster)
        .where(ProductMaster.id == version.product_master_id)
        .with_for_update()
    )
    reserved_titles: set[str] = set()
    batches: list[DraftBatch] = []
    try:
        for account_id in payload.account_ids:
            batch = generate_drafts(
                db,
                actor_user_id=actor.id,
                product_version_id=payload.product_version_id,
                account_id=account_id,
                count=payload.count,
                commercial_distribution=[p.model_dump() for p in payload.commercial_distribution],
                reserved_titles=reserved_titles,
                commit=False,
            )
            batches.append(batch)
        audit(
            db,
            "DRAFT_MULTI_ACCOUNT_GENERATED",
            "ProductVersion",
            str(payload.product_version_id),
            {
                "account_ids": [str(value) for value in payload.account_ids],
                "batch_ids": [str(batch.id) for batch in batches],
                "drafts_per_account": payload.count,
                "total_drafts": payload.count * len(payload.account_ids),
            },
            actor_user_id=actor.id,
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    return {
        "product_version_id": payload.product_version_id,
        "total_drafts": payload.count * len(batches),
        "batches": [
            {
                "batch_id": batch.id,
                "account_id": batch.account_id,
                "count": batch.requested_count,
                "drafts": [
                    {
                        "id": draft.id,
                        "sequence_number": draft.sequence_number,
                        "title": draft.title,
                        "status": draft.status,
                        "commercial_config": draft.commercial_config,
                    }
                    for draft in sorted(batch.drafts, key=lambda item: item.sequence_number)
                ],
            }
            for batch in batches
        ],
    }


@router.get("/batches/{batch_id}")
def batch_detail(batch_id: uuid.UUID, db: Session = Depends(get_db)):
    batch = db.get(DraftBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found.")
    keyword_intelligence = None
    first_run_id = next((d.title_generation_run_id for d in batch.drafts if d.title_generation_run_id), None)
    if first_run_id:
        run = db.get(TitleGenerationRun, first_run_id)
        snapshot = db.get(KeywordSnapshot, run.keyword_snapshot_id) if run else None
        if snapshot:
            evidence = snapshot.evidence or {}
            rejected = [item for item in evidence.get("ranked_terms", []) if not item.get("eligible")]
            keyword_intelligence = {
                "selected_terms": list(snapshot.keywords or []),
                "token_weights": list(evidence.get("token_weights") or [])[:12],
                "cache_status": evidence.get("trend_cache_status"),
                "semantic_model": evidence.get("semantic_model"),
                "top_rejected": rejected[:8],
            }

    draft_ids = [draft.id for draft in batch.drafts]
    validation_by_draft: dict[uuid.UUID, ValidationResult] = {}
    if draft_ids:
        validation_by_draft = {
            result.draft_id: result
            for result in db.scalars(
                select(ValidationResult).where(ValidationResult.draft_id.in_(draft_ids))
            ).all()
        }

    return {
        "id": batch.id,
        "product_version_id": batch.product_version_id,
        "account_id": batch.account_id,
        "requested_count": batch.requested_count,
        "commercial_distribution": batch.commercial_distribution,
        "keyword_intelligence": keyword_intelligence,
        "drafts": [
            {
                "id": d.id,
                "sequence_number": d.sequence_number,
                "title": d.title,
                "score": d.title_score,
                "commercial_config": d.commercial_config,
                "status": d.status,
                "image_order": d.image_order,
                "last_error": d.last_error,
                "validation": (
                    {
                        "valid": validation_by_draft[d.id].valid,
                        "errors": validation_by_draft[d.id].errors or [],
                        "warnings": validation_by_draft[d.id].warnings or [],
                        "created_at": validation_by_draft[d.id].created_at,
                    }
                    if d.id in validation_by_draft
                    else None
                ),
            }
            for d in sorted(batch.drafts, key=lambda x: x.sequence_number)
        ],
    }


@router.patch("/{draft_id}/commercial")
def update_commercial(
    draft_id: uuid.UUID, payload: DraftCommercialUpdate, request: Request, db: Session = Depends(get_db)
):
    actor, _ = request_identity(db, request)
    draft = db.get(PublicationDraft, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found.")
    if draft.status in {DraftStatus.PUBLISHING, DraftStatus.PUBLISHED}:
        raise HTTPException(status_code=409, detail="Published/publishing drafts are immutable.")
    old = dict(draft.commercial_config or {})
    updated = dict(old)
    for key, value in payload.model_dump().items():
        if value is None:
            updated.pop(key, None)
        else:
            updated[key] = value
    draft.commercial_config = updated
    draft.status = DraftStatus.GENERATED
    audit(
        db,
        "DRAFT_COMMERCIAL_UPDATED",
        "PublicationDraft",
        str(draft.id),
        {"old": old, "new": updated},
        actor_user_id=actor.id,
    )
    db.commit()
    return {"id": draft.id, "commercial_config": draft.commercial_config, "status": draft.status}


@router.patch("/{draft_id}/title")
def update_title(draft_id: uuid.UUID, payload: TitleUpdate, request: Request, db: Session = Depends(get_db)):
    actor, _ = request_identity(db, request)
    draft = db.get(PublicationDraft, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found.")
    if draft.status in {DraftStatus.PUBLISHING, DraftStatus.PUBLISHED}:
        raise HTTPException(status_code=409, detail="Published/publishing drafts are immutable.")
    draft.title = payload.title.strip()
    draft.status = DraftStatus.GENERATED
    audit(db, "DRAFT_TITLE_UPDATED", "PublicationDraft", str(draft.id), actor_user_id=actor.id)
    db.commit()
    return {"id": draft.id, "title": draft.title, "status": draft.status}





@router.post("/batches/multi-product-correction")
def correct_multi_batch_product(
    payload: MultiBatchProductCorrection,
    request: Request,
    db: Session = Depends(get_db),
    x_product_lease_token: str | None = Header(default=None),
    x_expected_product_version: uuid.UUID | None = Header(default=None),
):
    actor, operator_session = request_identity(db, request)
    if x_expected_product_version is None:
        raise HTTPException(status_code=428, detail="Indicá la versión de ficha utilizada por los lotes")
    version = rebase_batches_product_version(
        db,
        batch_ids=payload.batch_ids,
        expected_product_version_id=x_expected_product_version,
        authorization=lambda product_id: require_edit_token(
            db, actor, operator_session, product_id, x_product_lease_token
        ),
        actor_user_id=actor.id,
        description=payload.description,
        price=payload.price,
        quantity=payload.quantity,
        attributes=payload.attributes,
        commercial=payload.commercial,
        logistics=payload.logistics,
    )
    return {
        "batch_ids": payload.batch_ids,
        "version_id": version.id,
        "version_number": version.version_number,
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


@router.post("/batches/{batch_id}/product-correction")
def correct_batch_product(
    batch_id: uuid.UUID,
    payload: BatchProductCorrection,
    request: Request,
    db: Session = Depends(get_db),
    x_product_lease_token: str | None = Header(default=None),
    x_expected_product_version: uuid.UUID | None = Header(default=None),
):
    actor, operator_session = request_identity(db, request)
    if x_expected_product_version is None:
        raise HTTPException(status_code=428, detail="Indicá la versión de ficha utilizada por el lote")
    version = rebase_batch_product_version(
        db,
        batch_id=batch_id,
        expected_product_version_id=x_expected_product_version,
        authorization=lambda product_id: require_edit_token(
            db, actor, operator_session, product_id, x_product_lease_token
        ),
        actor_user_id=actor.id,
        description=payload.description,
        price=payload.price,
        quantity=payload.quantity,
        attributes=payload.attributes,
        commercial=payload.commercial,
        logistics=payload.logistics,
    )
    return {
        "batch_id": batch_id,
        "version_id": version.id,
        "version_number": version.version_number,
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


@router.post("/batches/{batch_id}/validate")
def validate_batch(batch_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    actor, _ = request_identity(db, request)
    batch = db.get(DraftBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found.")

    try:
        outcomes = validate_batch_drafts(
            db,
            batch=batch,
        )
    except MercadoLibreError as exc:
        raise HTTPException(
            status_code=502,
            detail="Mercado Libre no pudo ejecutar la validación previa. Volvé a intentar.",
        ) from exc

    audit(db, "DRAFT_BATCH_VALIDATED", "DraftBatch", str(batch.id), {"validated": len(outcomes), "ready": sum(outcome.valid for outcome in outcomes)}, actor_user_id=actor.id)
    db.commit()
    results = [
        {
            "draft_id": outcome.draft.id,
            "status": outcome.draft.status,
            "valid": outcome.valid,
            "errors": outcome.errors,
            "warnings": outcome.warnings,
        }
        for outcome in outcomes
    ]
    return {
        "batch_id": batch.id,
        "validated": len(results),
        "ready": sum(1 for result in results if result["valid"]),
        "invalid": sum(1 for result in results if not result["valid"]),
        "results": results,
    }


@router.post("/{draft_id}/validate")
def validate(draft_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    actor, _ = request_identity(db, request)
    draft = db.get(PublicationDraft, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found.")
    try:
        outcome = validate_single_draft(
            db,
            draft=draft,
        )
    except MercadoLibreError as exc:
        raise HTTPException(
            status_code=502,
            detail="Mercado Libre no pudo ejecutar la validación previa. Volvé a intentar.",
        ) from exc
    audit(db, "DRAFT_VALIDATED", "PublicationDraft", str(draft.id), {"valid": outcome.valid}, actor_user_id=actor.id)
    db.commit()
    return {
        "valid": outcome.valid,
        "errors": outcome.errors,
        "warnings": outcome.warnings,
        "status": outcome.draft.status,
    }


@router.post("/batches/{batch_id}/approve-ready")
def approve_batch_ready(batch_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    actor, _ = request_identity(db, request)
    batch = db.get(DraftBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found.")
    approved = approve_ready_drafts(db, batch_id=batch_id, actor_user_id=actor.id)
    db.commit()
    return {
        "batch_id": batch_id,
        "approved": len(approved),
        "draft_ids": [draft.id for draft in approved],
    }


@router.post("/{draft_id}/approve")
def approve(draft_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    actor, _ = request_identity(db, request)
    draft = db.get(PublicationDraft, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found.")
    if draft.status != DraftStatus.READY:
        raise HTTPException(status_code=409, detail="Only READY drafts can be approved.")
    draft.status = DraftStatus.APPROVED
    audit(db, "DRAFT_APPROVED", "PublicationDraft", str(draft.id), actor_user_id=actor.id)
    db.commit()
    return {"id": draft.id, "status": draft.status}


@router.post("/{draft_id}/exclude")
def exclude(draft_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    actor, _ = request_identity(db, request)
    draft = db.get(PublicationDraft, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found.")
    if draft.status in {DraftStatus.PUBLISHING, DraftStatus.PUBLISHED}:
        raise HTTPException(status_code=409, detail="Cannot exclude a publishing/published draft.")
    draft.status = DraftStatus.EXCLUDED
    audit(db, "DRAFT_EXCLUDED", "PublicationDraft", str(draft.id), actor_user_id=actor.id)
    db.commit()
    return {"id": draft.id, "status": draft.status}
