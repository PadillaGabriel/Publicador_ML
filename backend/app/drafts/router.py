import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import audit
from app.core.db import get_db
from app.core.enums import DraftStatus
from app.drafts.service import generate_drafts, rebase_batch_product_version
from app.drafts.validation_service import (
    approve_ready_drafts,
    validate_batch_drafts,
    validate_single_draft,
)
from app.integrations.mercadolibre.client import MercadoLibreError
from app.persistence import (
    DraftBatch, KeywordSnapshot, ProductVersion, PublicationDraft, TitleGenerationRun, ValidationResult
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




class BatchProductCorrection(BaseModel):
    description: str = ""
    price: float = Field(gt=0)
    quantity: int = Field(ge=0)
    attributes: dict = Field(default_factory=dict)
    commercial: dict = Field(default_factory=dict)
    logistics: dict = Field(default_factory=dict)


class TitleUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=255)


@router.post("/generate")
def generate(payload: GenerateRequest, db: Session = Depends(get_db)):
    batch = generate_drafts(
        db,
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


@router.patch("/{draft_id}/title")
def update_title(draft_id: uuid.UUID, payload: TitleUpdate, db: Session = Depends(get_db)):
    draft = db.get(PublicationDraft, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found.")
    if draft.status in {DraftStatus.PUBLISHING, DraftStatus.PUBLISHED}:
        raise HTTPException(status_code=409, detail="Published/publishing drafts are immutable.")
    draft.title = payload.title.strip()
    draft.status = DraftStatus.GENERATED
    audit(db, "DRAFT_TITLE_UPDATED", "PublicationDraft", str(draft.id), {"title": draft.title})
    db.commit()
    return {"id": draft.id, "title": draft.title, "status": draft.status}





@router.post("/batches/{batch_id}/product-correction")
def correct_batch_product(
    batch_id: uuid.UUID,
    payload: BatchProductCorrection,
    db: Session = Depends(get_db),
):
    version = rebase_batch_product_version(
        db,
        batch_id=batch_id,
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
    batch = db.get(DraftBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found.")

    try:
        outcomes = validate_batch_drafts(
            db,
            batch=batch,
            image_url_for=lambda image_id: str(request.url_for("serve_upload", image_id=image_id)),
        )
    except MercadoLibreError as exc:
        raise HTTPException(
            status_code=502,
            detail="Mercado Libre no pudo ejecutar la validación previa. Volvé a intentar.",
        ) from exc

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
    draft = db.get(PublicationDraft, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found.")
    try:
        outcome = validate_single_draft(
            db,
            draft=draft,
            image_url_for=lambda image_id: str(request.url_for("serve_upload", image_id=image_id)),
        )
    except MercadoLibreError as exc:
        raise HTTPException(
            status_code=502,
            detail="Mercado Libre no pudo ejecutar la validación previa. Volvé a intentar.",
        ) from exc
    db.commit()
    return {
        "valid": outcome.valid,
        "errors": outcome.errors,
        "warnings": outcome.warnings,
        "status": outcome.draft.status,
    }


@router.post("/batches/{batch_id}/approve-ready")
def approve_batch_ready(batch_id: uuid.UUID, db: Session = Depends(get_db)):
    batch = db.get(DraftBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found.")
    approved = approve_ready_drafts(db, batch_id=batch_id)
    db.commit()
    return {
        "batch_id": batch_id,
        "approved": len(approved),
        "draft_ids": [draft.id for draft in approved],
    }


@router.post("/{draft_id}/approve")
def approve(draft_id: uuid.UUID, db: Session = Depends(get_db)):
    draft = db.get(PublicationDraft, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found.")
    if draft.status != DraftStatus.READY:
        raise HTTPException(status_code=409, detail="Only READY drafts can be approved.")
    draft.status = DraftStatus.APPROVED
    audit(db, "DRAFT_APPROVED", "PublicationDraft", str(draft.id))
    db.commit()
    return {"id": draft.id, "status": draft.status}


@router.post("/{draft_id}/exclude")
def exclude(draft_id: uuid.UUID, db: Session = Depends(get_db)):
    draft = db.get(PublicationDraft, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found.")
    if draft.status in {DraftStatus.PUBLISHING, DraftStatus.PUBLISHED}:
        raise HTTPException(status_code=409, detail="Cannot exclude a publishing/published draft.")
    draft.status = DraftStatus.EXCLUDED
    audit(db, "DRAFT_EXCLUDED", "PublicationDraft", str(draft.id))
    db.commit()
    return {"id": draft.id, "status": draft.status}
