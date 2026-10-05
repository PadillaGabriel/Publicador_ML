"""Fail-closed account scope for publication resources.

Authorizes actual account ownership resolved from persisted batches/drafts/job items.
Product routes are allowlisted only where handlers enforce ownership and leases.
"""

import uuid

from fastapi import HTTPException
from sqlalchemy import distinct, select
from sqlalchemy.orm import Session

from app.identity import OperatorAccountGrant, OperatorUser
from app.persistence import DraftBatch, JobItem, ProductMaster, ProductVersion, PublicationDraft


def _uuid(value: object) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(status_code=422, detail="Identificador inválido") from exc


def allowed_account_ids(db: Session, user: OperatorUser) -> set[uuid.UUID]:
    return set(db.scalars(select(OperatorAccountGrant.account_id).where(
        OperatorAccountGrant.user_id == user.id
    )).all())


def ensure_account(db: Session, user: OperatorUser, account_id: object) -> None:
    if user.role == "ADMIN":
        return
    if _uuid(account_id) not in allowed_account_ids(db, user):
        raise HTTPException(status_code=403, detail="Cuenta Mercado Libre no autorizada")


def batch_account(db: Session, batch_id: object) -> uuid.UUID:
    value = db.scalar(select(DraftBatch.account_id).where(DraftBatch.id == _uuid(batch_id)))
    if value is None:
        raise HTTPException(status_code=404, detail="Lote inexistente")
    return value


def draft_account(db: Session, draft_id: object) -> uuid.UUID:
    value = db.scalar(select(DraftBatch.account_id).join(
        PublicationDraft, PublicationDraft.batch_id == DraftBatch.id
    ).where(PublicationDraft.id == _uuid(draft_id)))
    if value is None:
        raise HTTPException(status_code=404, detail="Borrador inexistente")
    return value


def job_accounts(db: Session, job_id: object) -> set[uuid.UUID]:
    values = set(db.scalars(select(distinct(DraftBatch.account_id))
        .join(PublicationDraft, PublicationDraft.batch_id == DraftBatch.id)
        .join(JobItem, JobItem.draft_id == PublicationDraft.id)
        .where(JobItem.job_id == _uuid(job_id))).all())
    # A job with zero items is not an authorized resource, even if its ID exists.
    if not values:
        raise HTTPException(status_code=404, detail="Trabajo inexistente o sin publicaciones")
    return values



def version_product(db: Session, version_id: object) -> uuid.UUID:
    value = db.scalar(select(ProductVersion.product_master_id).where(ProductVersion.id == _uuid(version_id)))
    if value is None:
        raise HTTPException(status_code=404, detail="Versión de ficha inexistente")
    return value


def batch_product(db: Session, batch_id: object) -> uuid.UUID:
    value = db.scalar(select(ProductVersion.product_master_id)
        .join(DraftBatch, DraftBatch.product_version_id == ProductVersion.id)
        .where(DraftBatch.id == _uuid(batch_id)))
    if value is None:
        raise HTTPException(status_code=404, detail="Lote inexistente")
    return value


def draft_product(db: Session, draft_id: object) -> uuid.UUID:
    value = db.scalar(select(ProductVersion.product_master_id)
        .join(DraftBatch, DraftBatch.product_version_id == ProductVersion.id)
        .join(PublicationDraft, PublicationDraft.batch_id == DraftBatch.id)
        .where(PublicationDraft.id == _uuid(draft_id)))
    if value is None:
        raise HTTPException(status_code=404, detail="Borrador inexistente")
    return value


def job_products(db: Session, job_id: object) -> set[uuid.UUID]:
    values = set(db.scalars(select(distinct(ProductVersion.product_master_id))
        .join(DraftBatch, DraftBatch.product_version_id == ProductVersion.id)
        .join(PublicationDraft, PublicationDraft.batch_id == DraftBatch.id)
        .join(JobItem, JobItem.draft_id == PublicationDraft.id)
        .where(JobItem.job_id == _uuid(job_id))).all())
    if not values:
        raise HTTPException(status_code=404, detail="Trabajo inexistente o sin fichas")
    return values


def ensure_product(db: Session, user: OperatorUser, product_id: uuid.UUID) -> None:
    # Historical fichas have no reliable owner; only an Administrator may access them.
    owner = db.scalar(select(ProductMaster.created_by_user_id).where(ProductMaster.id == product_id))
    if owner != user.id:
        raise HTTPException(status_code=403, detail="Ficha no autorizada para este operador")


def ensure_products(db: Session, user: OperatorUser, product_ids: set[uuid.UUID]) -> None:
    for product_id in product_ids:
        ensure_product(db, user, product_id)


def ensure_accounts(db: Session, user: OperatorUser, account_ids: set[uuid.UUID]) -> None:
    if user.role != "ADMIN" and not account_ids.issubset(allowed_account_ids(db, user)):
        raise HTTPException(status_code=403, detail="El recurso incluye cuentas no autorizadas")


def scope_operation(db: Session, user: OperatorUser, path: str, method: str,
                    query: dict[str, str], body: dict | None) -> None:
    """Check every defined publication route for operators, defaulting to deny.

    Management roles retain their existing RBAC (supervisors cannot publish).
    """
    if user.role != "OPERATOR":
        return
    data = body or {}
    parts = path.strip("/").split("/")
    if path == "/api/accounts" and method == "GET":
        return  # Response filtered by the accounts router.
    if path == "/api/accounts/oauth/status":
        return
    if path.startswith("/api/accounts"):
        raise HTTPException(status_code=403, detail="Solo administración puede gestionar cuentas")
    if path.startswith("/api/publication-import"):
        if method == "POST" and parts[2:] in (["mla"], ["mla", "reuse"]):
            ensure_account(db, user, data.get("account_id"))
            return
        raise HTTPException(status_code=403, detail="Operación sin alcance autorizado")
    if path.startswith("/api/drafts"):
        if path == "/api/drafts/generate" and method == "POST":
            ensure_account(db, user, data.get("account_id"))
            ensure_product(db, user, version_product(db, data.get("product_version_id")))
        elif len(parts) >= 4 and parts[2] == "batches":
            ensure_account(db, user, batch_account(db, parts[3]))
            ensure_product(db, user, batch_product(db, parts[3]))
            if method == "POST" and parts[4:] == ["product-correction"]:
                # Handler requires a fencing token plus expected product version
                # under ProductMaster row lock before persisting the corrected snapshot.
                return
        elif len(parts) >= 3:
            ensure_account(db, user, draft_account(db, parts[2]))
            ensure_product(db, user, draft_product(db, parts[2]))
        else:
            raise HTTPException(status_code=403, detail="Operación sin alcance autorizado")
        return
    if path.startswith("/api/publication"):
        if path in ("/api/publication/shipping-options", "/api/publication/commercial-options") and method == "GET":
            ensure_account(db, user, query.get("account_id"))
        elif path == "/api/publication/jobs" and method == "POST":
            ensure_account(db, user, batch_account(db, data.get("batch_id")))
            ensure_product(db, user, batch_product(db, data.get("batch_id")))
        elif len(parts) == 5 and parts[2] == "drafts" and parts[4] == "dry-run" and method == "GET":
            ensure_account(db, user, draft_account(db, parts[3]))
            ensure_product(db, user, draft_product(db, parts[3]))
        elif len(parts) == 5 and parts[2] == "jobs" and parts[4] == "export.xlsx" and method == "GET":
            ensure_accounts(db, user, job_accounts(db, parts[3]))
            ensure_products(db, user, job_products(db, parts[3]))
        else:
            raise HTTPException(status_code=403, detail="Operación sin alcance autorizado")
        return
    if path.startswith("/api/jobs"):
        if path == "/api/jobs/worker-status" and method == "GET":
            return
        if path == "/api/jobs/active/current":
            raise HTTPException(status_code=403, detail="Seguimiento global exclusivo de administración")
        if len(parts) >= 3 and parts[2] not in ("active", "worker-status"):
            ensure_accounts(db, user, job_accounts(db, parts[2]))
            ensure_products(db, user, job_products(db, parts[2]))
            return
        raise HTTPException(status_code=403, detail="Operación sin alcance autorizado")
    if path.startswith("/api/products"):
        # Product/version/image handlers enforce creator ownership and a valid lease
        # in the same database transaction as the write. Other paths deny by default.
        if path == "/api/products" and method in ("GET", "POST"):
            return
        if path == "/api/products/lookup" and method == "GET":
            return
        if len(parts) == 4 and parts[2] == "versions" and method == "GET":
            return
        if len(parts) == 4 and parts[3] == "versions" and method == "POST":
            return
        if len(parts) == 5 and parts[3:] == ["technical-attributes", "reuse"] and method == "GET":
            # The handler validates both product ownership and its required account_id.
            if query.get("account_id"):
                ensure_account(db, user, query["account_id"])
            return
        if len(parts) in (5, 6) and parts[2] == "versions" and parts[4] == "images" and method == "POST":
            return
        raise HTTPException(status_code=403, detail="Ruta de ficha sin control de propiedad")
    if path == "/api/title-intelligence/generate" and method == "POST":
        # The request only uses caller-supplied product data, but can access
        # account-specific title trends. Verify account assignment first.
        if not data.get("account_id"):
            raise HTTPException(status_code=403, detail="Cuenta Mercado Libre requerida")
        ensure_account(db, user, data["account_id"])
        return
    if path.startswith("/api/title-intelligence"):
        raise HTTPException(status_code=403, detail="Operación de títulos sin alcance autorizado")
    # Unknown commercial routes must not silently pass to handlers.
    raise HTTPException(status_code=403, detail="Ruta comercial sin clasificación de alcance")
