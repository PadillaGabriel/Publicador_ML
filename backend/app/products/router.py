import logging
import mimetypes
import time
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.persistence import ProductMaster, ProductVersion
from app.products.image_policy import ImagePolicyError, validate_image_content
from app.products.image_upload import (
    ProductImageUploadError,
    cleanup_staged_images,
    persist_product_image,
    persist_staged_product_images,
    stage_product_image,
)
from app.products.schemas import ProductCreate
from app.products.service import find_product_by_sku, save_product_version, serialize_version

router = APIRouter(prefix="/api/products", tags=["products"])
logger = logging.getLogger("product-image-performance")


@router.get("")
def list_products(db: Session = Depends(get_db)):
    latest_numbers = (
        select(
            ProductVersion.product_master_id.label("product_master_id"),
            func.max(ProductVersion.version_number).label("version_number"),
        )
        .group_by(ProductVersion.product_master_id)
        .subquery()
    )
    rows = db.execute(
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
    ).all()
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
    sku: str = Query(min_length=1, max_length=120),
    db: Session = Depends(get_db),
):
    master, version = find_product_by_sku(db, sku)
    if master is None or version is None:
        return {"found": False}

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
def create_product(payload: ProductCreate, db: Session = Depends(get_db)):
    master, version, created_master = save_product_version(db, payload)
    return {
        "product_id": master.id,
        "version_id": version.id,
        "version_number": version.version_number,
        "created_master": created_master,
    }


@router.post("/{product_id}/versions")
def create_version(product_id: uuid.UUID, payload: ProductCreate, db: Session = Depends(get_db)):
    master = db.get(ProductMaster, product_id)
    if not master:
        raise HTTPException(status_code=404, detail="Product not found.")
    if master.internal_sku != payload.internal_sku:
        raise HTTPException(
            status_code=409,
            detail="El SKU de una nueva versión debe coincidir con el producto maestro.",
        )

    _, version, _ = save_product_version(db, payload)
    return {
        "product_id": master.id,
        "version_id": version.id,
        "version_number": version.version_number,
    }


@router.get("/versions/{version_id}")
def get_version(version_id: uuid.UUID, db: Session = Depends(get_db)):
    version = db.get(ProductVersion, version_id)
    if not version:
        raise HTTPException(status_code=404, detail="Version not found.")
    return serialize_version(version)


@router.post("/versions/{version_id}/images/batch")
def upload_images_batch(
    version_id: uuid.UUID,
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
):
    if db.get(ProductVersion, version_id) is None:
        raise HTTPException(status_code=404, detail="Version not found.")

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
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    if db.get(ProductVersion, version_id) is None:
        raise HTTPException(status_code=404, detail="Version not found.")

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
