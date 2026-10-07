import logging
import mimetypes
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, Request, UploadFile
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from app.audit.service import audit
from app.core.config import get_settings
from app.core.db import get_db
from app.persistence import ProductImage, ProductMaster, ProductVersion
from app.products.image_policy import ImagePolicyError, validate_image_content
from app.products.image_upload import (
    ProductImageUploadError,
    cleanup_staged_images,
    persist_product_image,
    persist_staged_product_images,
    stage_product_image,
)
from app.products.schemas import ProductCreate
from app.operator_auth import request_identity
from app.product_edit_leases import require_edit_token, visible_product
from app.products.service import find_product_by_sku, save_product_version, serialize_version

router = APIRouter(prefix="/api/products", tags=["products"])
logger = logging.getLogger("product-image-performance")


class ImageOrderUpdate(BaseModel):
    image_ids: list[uuid.UUID] = Field(min_length=1, max_length=50)


def _serialize_images(version: ProductVersion) -> list[dict]:
    return [
        {
            "id": image.id,
            "original_name": image.original_name,
            "position": image.position,
            "mime_type": image.mime_type,
        }
        for image in sorted(version.images, key=lambda item: item.position)
    ]



@router.get("")
def list_products(request: Request, db: Session = Depends(get_db)):
    latest_numbers = (
        select(
            ProductVersion.product_master_id.label("product_master_id"),
            func.max(ProductVersion.version_number).label("version_number"),
        )
        .group_by(ProductVersion.product_master_id)
        .subquery()
    )
    actor, _ = request_identity(db, request)
    query = (
        select(ProductMaster, ProductVersion)
        .outerjoin(
            latest_numbers,
            latest_numbers.c.product_master_id == ProductMaster.id,
        )
        .outerjoin(
            ProductVersion,
            and_(
                ProductVersion.product_master_id == ProductMaster.id,
                ProductVersion.version_number == latest_numbers.c.version_number,
            ),
        )
        .order_by(ProductMaster.created_at.desc())
    )
    if actor.role == "OPERATOR":
        query = query.where(ProductMaster.created_by_user_id == actor.id)
    rows = db.execute(query).all()
    return [
        {
            "id": master.id,
            "internal_sku": master.internal_sku,
            "internal_name": master.internal_name,
            "category_id": latest.category_id if latest else None,
            "latest_version_number": latest.version_number if latest else None,
        }
        for master, latest in rows
    ]


@router.get("/lookup")
def lookup_product(
    request: Request,
    sku: str = Query(min_length=1, max_length=120),
    db: Session = Depends(get_db),
):
    master, version = find_product_by_sku(db, sku)
    if master is None or version is None:
        return {"found": False}
    actor, _ = request_identity(db, request)
    visible_product(db, actor, master.id)

    return {
        "found": True,
        "product": {
            "id": master.id,
            "internal_sku": master.internal_sku,
            "internal_name": master.internal_name,
            "latest_version": serialize_version(version),
        },
    }


@router.post("")
def create_product(payload: ProductCreate, request: Request, db: Session = Depends(get_db),
                   x_product_lease_token: str | None = Header(default=None),
                   x_expected_version: int | None = Header(default=None)):
    actor, session = request_identity(db, request)
    master, version, created_master = save_product_version(
        db, payload, actor_user_id=actor.id,
        authorization=lambda product_id: require_edit_token(db, actor, session, product_id, x_product_lease_token),
        expected_version=x_expected_version,
    )
    return {
        "product_id": master.id,
        "version_id": version.id,
        "version_number": version.version_number,
        "created_master": created_master,
    }


@router.post("/{product_id}/versions")
def create_version(product_id: uuid.UUID, payload: ProductCreate, request: Request, db: Session = Depends(get_db),
                   x_product_lease_token: str | None = Header(default=None),
                   x_expected_version: int | None = Header(default=None)):
    master = db.get(ProductMaster, product_id)
    if not master:
        raise HTTPException(status_code=404, detail="Product not found.")
    if master.internal_sku != payload.internal_sku:
        raise HTTPException(
            status_code=409,
            detail="El SKU de una nueva versión debe coincidir con el producto maestro.",
        )

    actor, session = request_identity(db, request)
    if x_expected_version is None:
        raise HTTPException(status_code=428, detail="Se requiere versión esperada")
    require_edit_token(db, actor, session, product_id, x_product_lease_token)
    _, version, _ = save_product_version(
        db, payload, actor_user_id=actor.id, expected_version=x_expected_version,
        authorization=lambda existing_id: require_edit_token(db, actor, session, existing_id, x_product_lease_token),
    )
    return {
        "product_id": master.id,
        "version_id": version.id,
        "version_number": version.version_number,
    }


@router.get("/versions/{version_id}")
def get_version(version_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    version = db.get(ProductVersion, version_id)
    if not version:
        raise HTTPException(status_code=404, detail="Version not found.")
    actor, _ = request_identity(db, request)
    visible_product(db, actor, version.product_master_id)
    return serialize_version(version)


@router.post("/versions/{version_id}/images/batch")
def upload_images_batch(
    version_id: uuid.UUID,
    request: Request,
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    x_product_lease_token: str | None = Header(default=None),
):
    version = db.get(ProductVersion, version_id)
    if version is None:
        raise HTTPException(status_code=404, detail="Version not found.")
    actor, session = request_identity(db, request)
    require_edit_token(db, actor, session, version.product_master_id, x_product_lease_token)

    settings = get_settings()
    started = time.perf_counter()
    if not files:
        raise HTTPException(status_code=422, detail="At least one image is required.")
    if len(files) > settings.max_upload_batch_files:
        raise HTTPException(
            status_code=413,
            detail=f"A batch accepts at most {settings.max_upload_batch_files} images.",
        )

    staged = []
    uploaded_meta: dict[uuid.UUID, dict] = {}
    failures: list[dict] = []
    total_bytes = 0

    try:
        for file in files:
            original_name = file.filename or "image"
            content = file.file.read(settings.max_upload_bytes + 1)
            if len(content) > settings.max_upload_bytes:
                failures.append({
                    "name": original_name,
                    "status": 413,
                    "detail": "Image exceeds configured size limit.",
                })
                continue

            total_bytes += len(content)
            if total_bytes > settings.max_upload_batch_bytes:
                cleanup_staged_images(staged)
                raise HTTPException(
                    status_code=413,
                    detail="Image batch exceeds configured total size limit.",
                )

            mime = file.content_type or mimetypes.guess_type(original_name)[0] or ""
            if not mime.startswith("image/"):
                failures.append({
                    "name": original_name,
                    "status": 415,
                    "detail": "Only image uploads are accepted.",
                })
                continue

            try:
                inspection = validate_image_content(content)
            except ImagePolicyError as exc:
                failures.append({
                    "name": original_name,
                    "status": 422,
                    "detail": str(exc),
                })
                continue

            staged_image = stage_product_image(
                original_name=original_name,
                mime_type=mime,
                content=content,
                upload_dir=settings.upload_dir,
            )
            staged.append(staged_image)
            uploaded_meta[staged_image.id] = {
                "width": inspection.width,
                "height": inspection.height,
                "format": inspection.format,
            }

        images = persist_staged_product_images(
            db,
            version_id=version_id,
            staged_images=staged,
            actor_user_id=actor.id,
        ) if staged else []
    except HTTPException:
        raise
    except ProductImageUploadError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except OSError as exc:
        cleanup_staged_images(staged)
        raise HTTPException(status_code=500, detail="No se pudo guardar el lote de imágenes.") from exc

    logger.info(
        "image_batch_upload_completed version=%s requested=%d uploaded=%d failed=%d bytes=%d duration_ms=%d",
        version_id,
        len(files),
        len(images),
        len(failures),
        total_bytes,
        round((time.perf_counter() - started) * 1000),
    )
    return {
        "uploaded": [
            {
                "id": image.id,
                "position": image.position,
                "name": image.original_name,
                **uploaded_meta[image.id],
            }
            for image in images
        ],
        "failed": failures,
        "uploaded_count": len(images),
        "failed_count": len(failures),
        "recommended_side_px": settings.ml_image_recommended_side_px,
    }


@router.post("/versions/{version_id}/images")
def upload_image(
    version_id: uuid.UUID,
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    x_product_lease_token: str | None = Header(default=None),
):
    version = db.get(ProductVersion, version_id)
    if version is None:
        raise HTTPException(status_code=404, detail="Version not found.")
    actor, session = request_identity(db, request)
    require_edit_token(db, actor, session, version.product_master_id, x_product_lease_token)

    settings = get_settings()
    content = file.file.read(settings.max_upload_bytes + 1)
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="Image exceeds configured size limit.")

    mime = file.content_type or mimetypes.guess_type(file.filename or "")[0] or ""
    if not mime.startswith("image/"):
        raise HTTPException(status_code=415, detail="Only image uploads are accepted.")

    try:
        inspection = validate_image_content(content)
        image = persist_product_image(
            db,
            version_id=version_id,
            original_name=file.filename or "image",
            mime_type=mime,
            content=content,
            upload_dir=settings.upload_dir,
            actor_user_id=actor.id,
        )
    except ImagePolicyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ProductImageUploadError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return {
        "id": image.id,
        "position": image.position,
        "name": image.original_name,
        "width": inspection.width,
        "height": inspection.height,
        "format": inspection.format,
        "recommended_side_px": settings.ml_image_recommended_side_px,
    }

@router.put("/versions/{version_id}/images/order")
def reorder_images(
    version_id: uuid.UUID,
    payload: ImageOrderUpdate,
    request: Request,
    db: Session = Depends(get_db),
    x_product_lease_token: str | None = Header(default=None),
):
    version = db.scalar(
        select(ProductVersion).where(ProductVersion.id == version_id).with_for_update()
    )
    if version is None:
        raise HTTPException(status_code=404, detail="Version not found.")
    actor, operator_session = request_identity(db, request)
    require_edit_token(
        db, actor, operator_session, version.product_master_id, x_product_lease_token
    )
    images = db.scalars(
        select(ProductImage)
        .where(ProductImage.product_version_id == version_id)
        .order_by(ProductImage.position)
        .with_for_update()
    ).all()
    existing = {image.id: image for image in images}
    requested = payload.image_ids
    if len(requested) != len(set(requested)):
        raise HTTPException(status_code=422, detail="No repitas imágenes en el orden solicitado.")
    if set(requested) != set(existing):
        raise HTTPException(
            status_code=409,
            detail="El orden debe incluir exactamente todas las imágenes actuales de la ficha.",
        )
    old_order = [str(image.id) for image in images]
    for position, image_id in enumerate(requested, start=1):
        existing[image_id].position = position
    audit(
        db,
        "PRODUCT_IMAGES_REORDERED",
        "ProductVersion",
        str(version_id),
        {"old_order": old_order, "new_order": [str(value) for value in requested]},
        actor_user_id=actor.id,
    )
    db.commit()
    db.refresh(version)
    return {"version_id": version.id, "images": _serialize_images(version)}


@router.delete("/versions/{version_id}/images/{image_id}")
def delete_image(
    version_id: uuid.UUID,
    image_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    x_product_lease_token: str | None = Header(default=None),
):
    version = db.scalar(
        select(ProductVersion).where(ProductVersion.id == version_id).with_for_update()
    )
    if version is None:
        raise HTTPException(status_code=404, detail="Version not found.")
    actor, operator_session = request_identity(db, request)
    require_edit_token(
        db, actor, operator_session, version.product_master_id, x_product_lease_token
    )
    image = db.scalar(
        select(ProductImage)
        .where(
            ProductImage.id == image_id,
            ProductImage.product_version_id == version_id,
        )
        .with_for_update()
    )
    if image is None:
        raise HTTPException(status_code=404, detail="Image not found.")

    storage_path = str(image.storage_path or "")
    removed_position = image.position
    db.delete(image)
    remaining = db.scalars(
        select(ProductImage)
        .where(ProductImage.product_version_id == version_id, ProductImage.id != image_id)
        .order_by(ProductImage.position)
        .with_for_update()
    ).all()
    for position, row in enumerate(remaining, start=1):
        row.position = position
    audit(
        db,
        "PRODUCT_IMAGE_DELETED",
        "ProductVersion",
        str(version_id),
        {"image_id": str(image_id), "position": removed_position},
        actor_user_id=actor.id,
    )
    db.commit()

    # Bytes are deleted only when they belong to the configured upload root.
    if storage_path:
        try:
            root = get_settings().upload_dir.resolve()
            candidate = Path(storage_path).resolve()
            if candidate.is_relative_to(root):
                candidate.unlink(missing_ok=True)
        except OSError:
            logger.warning("product_image_file_cleanup_failed image=%s", image_id)

    refreshed = db.get(ProductVersion, version_id)
    return {"version_id": version_id, "deleted_image_id": image_id, "images": _serialize_images(refreshed)}

