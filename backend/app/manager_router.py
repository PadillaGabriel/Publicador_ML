"""Paginated, permission-scoped read models for the publication manager.

All results originate from persisted internal publications; the manager never
claims to list seller items that have not been imported or created by this app.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.identity import OperatorAccountGrant, OperatorUser
from app.operator_auth import request_identity
from app.persistence import (
    AuditEvent, DraftBatch, Job, JobItem, MercadoLibreAccount, ProductMaster,
    ProductVersion, Publication, PublicationDraft,
)

router = APIRouter(prefix="/api/manager", tags=["manager"])


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
