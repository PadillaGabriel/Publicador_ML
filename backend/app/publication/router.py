import logging
import uuid
from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import audit
from app.accounts.service import load_access_token
from app.core.db import get_db
from app.core.enums import DraftStatus, JobItemStatus, JobStatus
from app.persistence import DraftBatch, Job, JobItem, MercadoLibreAccount, ProductVersion, Publication, PublicationDraft
from app.publication.commercial import fetch_commercial_options
from app.publication.export import build_job_export_xlsx
from app.publication.payload import build_item_payload
from app.publication.validation import validate_draft

logger = logging.getLogger("ml-publication")
router = APIRouter(prefix="/api/publication", tags=["publication"])


class BatchAction(BaseModel):
    batch_id: uuid.UUID
    draft_ids: list[uuid.UUID] | None = None


@router.get("/commercial-options")
def commercial_options(
    account_id: uuid.UUID,
    category_id: str,
    db: Session = Depends(get_db),
):
    account = db.get(MercadoLibreAccount, account_id)
    if not account or not account.active or not account.seller_id:
        raise HTTPException(status_code=404, detail="Cuenta de Mercado Libre no encontrada o sin seller_id.")

    token = load_access_token(db, account.id)
    options = fetch_commercial_options(
        access_token=token,
        seller_id=account.seller_id,
        category_id=category_id,
        site_id=account.site_id,
    )
    return {
        "account_id": account.id,
        "category_id": category_id,
        "options": [
            {
                "commercial_intent": option.commercial_intent,
                "label": option.label,
                "listing_type_id": option.listing_type_id,
                "listing_type_name": option.listing_type_name,
            }
            for option in options
        ],
    }


def _image_urls(request: Request, version: ProductVersion, draft: PublicationDraft) -> list[str]:
    images = {str(img.id): img for img in version.images}
    result = []
    for image_id in draft.image_order:
        image = images.get(str(image_id))
        if image:
            result.append(str(request.url_for("serve_upload", image_id=str(image.id))))
    return result


@router.get("/drafts/{draft_id}/dry-run")
def dry_run(draft_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    draft = db.get(PublicationDraft, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found.")
    batch = db.get(DraftBatch, draft.batch_id)
    version = db.get(ProductVersion, batch.product_version_id)
    errors, warnings = validate_draft(db, draft)
    payload = build_item_payload(
        version,
        draft,
        _image_urls(request, version, draft),
        seller_sku=version.master.internal_sku,
    )
    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "title_intent": draft.title,
        "naming_contract": (draft.commercial_config or {}).get("naming_contract"),
        "commercial_intent": draft.commercial_config or {},
        "payload": payload,
        "live_publication": False,
    }


@router.post("/jobs")
def create_publication_job(payload: BatchAction, db: Session = Depends(get_db)):
    batch = db.get(DraftBatch, payload.batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found.")

    approved = [d for d in batch.drafts if d.status == DraftStatus.APPROVED]
    if not approved:
        raise HTTPException(status_code=409, detail="Batch has no APPROVED drafts.")

    if payload.draft_ids is not None:
        if not payload.draft_ids:
            raise HTTPException(status_code=422, detail="Seleccioná al menos un borrador aprobado.")
        requested = set(payload.draft_ids)
        approved_by_id = {d.id: d for d in approved}
        unknown = requested - set(approved_by_id)
        if unknown:
            raise HTTPException(
                status_code=409,
                detail="Uno o más borradores seleccionados no pertenecen al lote o no están APPROVED.",
            )
        approved = [approved_by_id[draft_id] for draft_id in payload.draft_ids]

    validation_failures = []
    for draft in approved:
        errors, _warnings = validate_draft(db, draft)
        if errors:
            validation_failures.append({
                "draft_id": str(draft.id),
                "sequence_number": draft.sequence_number,
                "title": draft.title,
                "errors": errors,
            })
    if validation_failures:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "DRAFTS_NOT_PUBLISHABLE",
                "message": (
                    "Uno o más borradores seleccionados ya no cumplen las validaciones necesarias "
                    "para publicación live. Corregilos y volvé a validar antes de crear el job."
                ),
                "drafts": validation_failures,
            },
        )

    already_published = set(
        db.scalars(
            select(Publication.draft_id).where(Publication.draft_id.in_([d.id for d in approved]))
        ).all()
    )
    eligible = [d for d in approved if d.id not in already_published]
    if not eligible:
        raise HTTPException(status_code=409, detail="All selected drafts are already published.")

    job = Job(total=len(eligible), status=JobStatus.PENDING)
    db.add(job)
    db.flush()
    for draft in eligible:
        db.add(JobItem(job_id=job.id, draft_id=draft.id, status=JobItemStatus.PENDING))
    audit(
        db,
        "PUBLICATION_JOB_CREATED",
        "Job",
        str(job.id),
        {"count": len(eligible), "draft_ids": [str(d.id) for d in eligible]},
    )
    db.commit()
    logger.info("publication_job_created job=%s drafts=%d", job.id, job.total)
    return {"job_id": job.id, "total": job.total, "status": job.status}


@router.get("/jobs/{job_id}/export.xlsx")
def export_job(job_id: uuid.UUID, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job.status not in {JobStatus.COMPLETED, JobStatus.PARTIAL, JobStatus.FAILED}:
        raise HTTPException(status_code=409, detail="El Excel se habilita cuando finaliza el proceso.")

    content = build_job_export_xlsx(db, job)
    filename = f"publicaciones_ml_{str(job.id)[:8]}.xlsx"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(
        BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )
