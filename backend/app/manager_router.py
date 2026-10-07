"""Paginated, permission-scoped read models for the publication manager.

All results originate from persisted internal publications; the manager never
claims to list seller items that have not been imported or created by this app.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.accounts.service import load_access_token
from app.audit.service import audit
from app.core.db import get_db
from app.identity import OperatorAccountGrant, OperatorUser
from app.operator_auth import request_identity
from app.integrations.mercadolibre.client import MercadoLibreClient, MercadoLibreError
from app.persistence import (
    AuditEvent, DraftBatch, Job, JobItem, MercadoLibreAccount, ProductMaster,
    ProductVersion, Publication, PublicationDraft,
)

router = APIRouter(prefix="/api/manager", tags=["manager"])


UPDATABLE_ITEM_FIELDS = {"price", "available_quantity", "status"}


class PublicationChangeSet(BaseModel):
    price: float | None = Field(default=None, gt=0)
    available_quantity: int | None = Field(default=None, ge=0)
    status: str | None = Field(default=None, max_length=40)

    @model_validator(mode="after")
    def validate_non_empty(self):
        if not self.model_dump(exclude_none=True):
            raise ValueError("Indicá al menos un campo para actualizar.")
        return self


class PublicationUpdateConfirm(BaseModel):
    expected: dict = Field(default_factory=dict)
    changes: PublicationChangeSet


class PublicationBulkUpdateItem(PublicationUpdateConfirm):
    publication_id: uuid.UUID


class PublicationBulkUpdate(BaseModel):
    items: list[PublicationBulkUpdateItem] = Field(min_length=1, max_length=100)


def _managed_publication_context(db: Session, actor: OperatorUser, publication_id: uuid.UUID):
    columns = (Publication, PublicationDraft, DraftBatch, ProductVersion, ProductMaster, MercadoLibreAccount)
    stmt = (select(*columns)
        .join(PublicationDraft, PublicationDraft.id == Publication.draft_id)
        .join(DraftBatch, DraftBatch.id == PublicationDraft.batch_id)
        .join(ProductVersion, ProductVersion.id == DraftBatch.product_version_id)
        .join(ProductMaster, ProductMaster.id == ProductVersion.product_master_id)
        .join(MercadoLibreAccount, MercadoLibreAccount.id == Publication.account_id)
        .where(Publication.id == publication_id))
    row = db.execute(_scope_publications(stmt, actor)).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Publicación inexistente o no autorizada")
    return row


def _current_item_fields(item: dict) -> dict:
    return {field: item.get(field) for field in UPDATABLE_ITEM_FIELDS}


def _normalized_changes(changes: PublicationChangeSet) -> dict:
    payload = changes.model_dump(exclude_none=True)
    if "status" in payload:
        payload["status"] = str(payload["status"]).strip().lower()
    return payload


def _preview_changes(current: dict, changes: dict) -> list[dict]:
    return [
        {"field": field, "old": current.get(field), "new": value}
        for field, value in changes.items()
        if current.get(field) != value
    ]


def _check_expected(current: dict, expected: dict) -> None:
    relevant = {key: value for key, value in expected.items() if key in UPDATABLE_ITEM_FIELDS}
    conflicts = {
        key: {"expected": value, "current": current.get(key)}
        for key, value in relevant.items()
        if current.get(key) != value
    }
    if conflicts:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "PUBLICATION_CHANGED_SINCE_PREVIEW",
                "message": "Mercado Libre cambió desde la vista previa. Volvé a revisar antes de confirmar.",
                "conflicts": conflicts,
            },
        )



def _scope_publications(statement, actor: OperatorUser):
    """Apply role constraints in SQL before counts, filters or pagination."""
    if actor.role == "OPERATOR":
        grants = select(OperatorAccountGrant.account_id).where(
            OperatorAccountGrant.user_id == actor.id
        )
        return statement.where(
            ProductMaster.created_by_user_id == actor.id,
            Publication.account_id.in_(grants),
        )
    if actor.role not in {"ADMIN", "SUPERVISOR"}:
        raise HTTPException(status_code=403, detail="Rol no autorizado")
    return statement


def _search_pattern(value: str) -> str:
    """Treat wildcards in the user's query as literal characters."""
    return "%" + value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


@router.get("/publications")
def list_publications(
    request: Request,
    q: str = Query(default="", max_length=120),
    account_id: uuid.UUID | None = None,
    status: str = Query(default="", max_length=40),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=10000),
    db: Session = Depends(get_db),
):
    actor, _ = request_identity(db, request)
    columns = (Publication, PublicationDraft, DraftBatch, ProductVersion, ProductMaster, MercadoLibreAccount)
    stmt = (select(*columns)
        .join(PublicationDraft, PublicationDraft.id == Publication.draft_id)
        .join(DraftBatch, DraftBatch.id == PublicationDraft.batch_id)
        .join(ProductVersion, ProductVersion.id == DraftBatch.product_version_id)
        .join(ProductMaster, ProductMaster.id == ProductVersion.product_master_id)
        .join(MercadoLibreAccount, MercadoLibreAccount.id == Publication.account_id))
    stmt = _scope_publications(stmt, actor)
    term = q.strip()
    if term:
        pattern = _search_pattern(term)
        stmt = stmt.where(or_(
            ProductMaster.internal_sku.ilike(pattern, escape="\\"),
            Publication.item_id.ilike(pattern, escape="\\"),
            Publication.user_product_id.ilike(pattern, escape="\\"),
            PublicationDraft.title.ilike(pattern, escape="\\"),
        ))
    if account_id is not None:
        stmt = stmt.where(Publication.account_id == account_id)
    if status.strip():
        stmt = stmt.where(Publication.status == status.strip().upper())
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.execute(stmt.order_by(Publication.published_at.desc().nullslast(), Publication.id.desc())
                      .limit(limit).offset(offset)).all()
    return {
        "total": total, "limit": limit, "offset": offset,
        "items": [{
            "publication_id": str(publication.id),
            "item_id": publication.item_id,
            "user_product_id": publication.user_product_id,
            "status": publication.status,
            "sku": product.internal_sku,
            "product_id": str(product.id),
            "product_owner_id": str(product.created_by_user_id) if product.created_by_user_id else None,
            "version_number": version.version_number,
            "title": draft.title,
            "account_id": str(account.id),
            "account_nickname": account.nickname,
            "batch_id": str(batch.id),
            "draft_id": str(draft.id),
            "internal_price": float(version.price),
            "b2b_sync": (publication.external_response or {}).get("_quantity_price_sync") or {"status": "SIN_CONFIGURAR"},
            "published_at": publication.published_at.isoformat() if publication.published_at else None,
        } for publication, draft, batch, version, product, account in rows],
    }


def _scope_jobs(statement, actor: OperatorUser):
    """For an operator all job items must belong to their owned products/grants.

    A mixed job cannot be exposed just because one of its items is authorized.
    """
    item_graph = (select(JobItem.job_id, ProductMaster.created_by_user_id, DraftBatch.account_id)
        .join(PublicationDraft, PublicationDraft.id == JobItem.draft_id)
        .join(DraftBatch, DraftBatch.id == PublicationDraft.batch_id)
        .join(ProductVersion, ProductVersion.id == DraftBatch.product_version_id)
        .join(ProductMaster, ProductMaster.id == ProductVersion.product_master_id))
    accessible = select(item_graph.subquery().c.job_id)
    statement = statement.where(Job.id.in_(accessible))
    if actor.role == "OPERATOR":
        # Check every item, not just job.requested_by_user_id (legacy jobs are nullable).
        graph = item_graph.subquery()
        grants = select(OperatorAccountGrant.account_id).where(OperatorAccountGrant.user_id == actor.id)
        denied = (select(graph.c.job_id).where(or_(
            graph.c.created_by_user_id != actor.id,
            graph.c.created_by_user_id.is_(None),
            ~graph.c.account_id.in_(grants),
        )))
        return statement.where(~Job.id.in_(denied))
    if actor.role not in {"ADMIN", "SUPERVISOR"}:
        raise HTTPException(status_code=403, detail="Rol no autorizado")
    return statement


@router.get("/jobs")
def list_jobs(
    request: Request,
    status: str = Query(default="", max_length=40),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=10000),
    db: Session = Depends(get_db),
):
    actor, _ = request_identity(db, request)
    stmt = _scope_jobs(select(Job), actor)
    if status.strip():
        stmt = stmt.where(Job.status == status.strip().upper())
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    jobs = db.scalars(stmt.order_by(Job.created_at.desc(), Job.id.desc()).limit(limit).offset(offset)).all()
    return {
        "total": total, "limit": limit, "offset": offset,
        "items": [{
            "id": str(job.id), "status": job.status, "type": job.type,
            "total": job.total, "processed": job.processed,
            "succeeded": job.succeeded, "failed": job.failed,
            "requested_by_user_id": str(job.requested_by_user_id) if job.requested_by_user_id else None,
            "created_at": job.created_at.isoformat(),
            "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        } for job in jobs],
    }


@router.post("/publications/{publication_id}/preview-update")
def preview_publication_update(
    publication_id: uuid.UUID,
    changes: PublicationChangeSet,
    request: Request,
    db: Session = Depends(get_db),
):
    actor, _ = request_identity(db, request)
    publication, _draft, _batch, _version, _product, account = _managed_publication_context(
        db, actor, publication_id
    )
    if not publication.item_id:
        raise HTTPException(status_code=409, detail="La publicación todavía no tiene MLA.")
    client = MercadoLibreClient(load_access_token(db, account.id))
    try:
        item = client.item(publication.item_id)
    except MercadoLibreError as exc:
        raise HTTPException(status_code=502, detail="No se pudo leer el estado actual de Mercado Libre.") from exc
    current = _current_item_fields(item)
    desired = _normalized_changes(changes)
    return {
        "publication_id": str(publication.id),
        "item_id": publication.item_id,
        "account_id": str(account.id),
        "expected": current,
        "changes": _preview_changes(current, desired),
        "has_changes": bool(_preview_changes(current, desired)),
    }


def _apply_publication_update(
    db: Session, actor: OperatorUser, publication_id: uuid.UUID, payload: PublicationUpdateConfirm
) -> dict:
    publication, draft, batch, version, product, account = _managed_publication_context(
        db, actor, publication_id
    )
    if not publication.item_id:
        raise HTTPException(status_code=409, detail="La publicación todavía no tiene MLA.")
    client = MercadoLibreClient(load_access_token(db, account.id))
    desired = _normalized_changes(payload.changes)
    try:
        before_item = client.item(publication.item_id)
    except MercadoLibreError as exc:
        raise HTTPException(status_code=502, detail="No se pudo validar el estado actual de Mercado Libre.") from exc
    before = _current_item_fields(before_item)
    _check_expected(before, payload.expected)
    actual_changes = {key: value for key, value in desired.items() if before.get(key) != value}
    if not actual_changes:
        return {
            "publication_id": str(publication.id),
            "item_id": publication.item_id,
            "status": "NO_CHANGES",
            "before": before,
            "after": before,
        }
    try:
        write = client.update_item(publication.item_id, actual_changes)
        after_item = client.item(publication.item_id)
    except MercadoLibreError as exc:
        audit(
            db, "PUBLICATION_UPDATE_FAILED", "Publication", str(publication.id),
            {
                "item_id": publication.item_id,
                "account_id": str(account.id),
                "requested_changes": actual_changes,
                "error": str(exc),
            },
            actor_user_id=actor.id,
        )
        db.commit()
        raise HTTPException(status_code=502, detail="Mercado Libre rechazó la actualización.") from exc
    after = _current_item_fields(after_item)
    mismatches = {
        key: {"requested": value, "actual": after.get(key)}
        for key, value in actual_changes.items()
        if after.get(key) != value
    }
    event = "PUBLICATION_UPDATED" if not mismatches else "PUBLICATION_UPDATE_VERIFICATION_FAILED"
    audit(
        db, event, "Publication", str(publication.id),
        {
            "item_id": publication.item_id,
            "account_id": str(account.id),
            "product_id": str(product.id),
            "batch_id": str(batch.id),
            "draft_id": str(draft.id),
            "before": before,
            "requested": actual_changes,
            "after": after,
            "http_status": write.status_code,
            "mismatches": mismatches,
        },
        actor_user_id=actor.id,
    )
    db.commit()
    if mismatches:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "PUBLICATION_UPDATE_NOT_CONFIRMED",
                "message": "Mercado Libre respondió la actualización pero la lectura posterior no confirmó todos los cambios.",
                "mismatches": mismatches,
            },
        )
    return {
        "publication_id": str(publication.id),
        "item_id": publication.item_id,
        "status": "UPDATED",
        "before": before,
        "after": after,
        "changes": actual_changes,
    }


@router.post("/publications/{publication_id}/apply-update")
def apply_publication_update(
    publication_id: uuid.UUID,
    payload: PublicationUpdateConfirm,
    request: Request,
    db: Session = Depends(get_db),
):
    actor, _ = request_identity(db, request)
    return _apply_publication_update(db, actor, publication_id, payload)


@router.post("/bulk/publications/update")
def bulk_publication_update(
    payload: PublicationBulkUpdate, request: Request, db: Session = Depends(get_db)
):
    actor, _ = request_identity(db, request)
    results: list[dict] = []
    for item in payload.items:
        try:
            result = _apply_publication_update(
                db, actor, item.publication_id,
                PublicationUpdateConfirm(expected=item.expected, changes=item.changes),
            )
            results.append({"publication_id": str(item.publication_id), "ok": True, "result": result})
        except HTTPException as exc:
            db.rollback()
            results.append({
                "publication_id": str(item.publication_id),
                "ok": False,
                "status_code": exc.status_code,
                "error": exc.detail,
            })
    succeeded = sum(1 for result in results if result["ok"])
    return {
        "status": "COMPLETED" if succeeded == len(results) else "PARTIAL" if succeeded else "FAILED",
        "total": len(results),
        "succeeded": succeeded,
        "failed": len(results) - succeeded,
        "results": results,
    }


@router.get("/audit")
def list_audit_events(
    request: Request,
    event_type: str = Query(default="", max_length=100),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=10000),
    db: Session = Depends(get_db),
):
    actor, _ = request_identity(db, request)
    if actor.role not in {"ADMIN", "SUPERVISOR"}:
        raise HTTPException(status_code=403, detail="Auditoría reservada a administración")
    stmt = (select(AuditEvent, OperatorUser.display_name)
        .outerjoin(OperatorUser, OperatorUser.id == AuditEvent.actor_user_id))
    if event_type.strip():
        stmt = stmt.where(AuditEvent.event_type == event_type.strip().upper())
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.execute(stmt.order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
                      .limit(limit).offset(offset)).all()
    # Do not project payload: older audit events may contain sensitive provider metadata.
    return {
        "total": total, "limit": limit, "offset": offset,
        "items": [{
            "id": str(event.id), "event_type": event.event_type,
            "entity_type": event.entity_type, "entity_id": event.entity_id,
            "actor_user_id": str(event.actor_user_id) if event.actor_user_id else None,
            "actor_name": actor_name,
            "created_at": event.created_at.isoformat(),
        } for event, actor_name in rows],
    }
