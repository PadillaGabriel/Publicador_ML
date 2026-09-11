import logging
import uuid
from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.accounts.service import load_access_token
from app.audit.service import audit
from app.core.db import get_db
from app.core.enums import DraftStatus, JobItemStatus, JobStatus
from app.persistence import (
    DraftBatch,
    Job,
    JobItem,
    MercadoLibreAccount,
    ProductVersion,
    Publication,
    PublicationDraft,
)
from app.publication.commercial import fetch_commercial_options
from app.publication.export import build_job_export_xlsx
from app.integrations.mercadolibre.client import MercadoLibreClient, MercadoLibreError
from app.publication.payload import build_item_payload, ordered_image_urls
from app.publication.preflight import validate_draft_with_mercadolibre
from app.publication.shipping import ShippingCapabilityError, fetch_shipping_capabilities
from app.publication.validation import validate_draft

logger = logging.getLogger("ml-publication")
router = APIRouter(prefix="/api/publication", tags=["publication"])


class BatchAction(BaseModel):
    batch_id: uuid.UUID
    draft_ids: list[uuid.UUID] | None = None



@router.get("/shipping-options")
def shipping_options(
    account_id: uuid.UUID,
    category_id: str,
    db: Session = Depends(get_db),
):
    account = db.get(MercadoLibreAccount, account_id)
    if not account or not account.active or not account.seller_id:
        raise HTTPException(
            status_code=404,
            detail="Cuenta de Mercado Libre no encontrada o sin seller_id.",
        )

    token = load_access_token(db, account.id)
    try:
        client = MercadoLibreClient(token)
        capabilities = fetch_shipping_capabilities(
            client,
            seller_id=account.seller_id,
            category_id=category_id,
        )
    except ShippingCapabilityError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except MercadoLibreError as exc:
        raise HTTPException(
            status_code=502,
            detail="Mercado Libre no pudo informar las opciones de envío de la cuenta.",
        ) from exc

    return {
        "mode": capabilities.mode,
        "base_logistic_type": capabilities.base_logistic_type,
        "flex_available": capabilities.flex_available,
        "flex_logistic_type": capabilities.flex_logistic_type,
    }


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
    return ordered_image_urls(
        version,
        draft,
        lambda image_id: str(request.url_for("serve_upload", image_id=image_id)),
    )


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
def create_publication_job(payload: BatchAction, request: Request, db: Session = Depends(get_db)):
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
    batch_version = db.get(ProductVersion, batch.product_version_id)
    if batch_version is None:
        raise HTTPException(status_code=409, detail="La versión de producto del lote ya no existe.")

    for draft in approved:
        errors, _warnings = validate_draft(db, draft)
        if not errors:
            try:
                errors.extend(
                    validate_draft_with_mercadolibre(
                        db,
                        draft,
                        _image_urls(request, batch_version, draft),
                    )
                )
            except MercadoLibreError as exc:
                raise HTTPException(
                    status_code=502,
                    detail="Mercado Libre no pudo ejecutar la validación previa. Volvé a intentar antes de publicar.",
                ) from exc
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
                    "Uno o más borradores seleccionados no pasan la validación previa de Mercado Libre. "
                    f"{validation_failures[0]['errors'][0].get('message', '')} "
                    "Corregí la ficha y volvé a validar antes de crear el job."
                ).strip(),
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
