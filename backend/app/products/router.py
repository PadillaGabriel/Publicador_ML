import mimetypes
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.persistence import ProductMaster, ProductVersion
from app.products.image_policy import ImagePolicyError, validate_image_content
from app.products.image_upload import ProductImageUploadError, persist_product_image
from app.products.schemas import ProductCreate
from app.products.service import find_product_by_sku, save_product_version, serialize_version

router = APIRouter(prefix="/api/products", tags=["products"])


@router.get("")
def list_products(db: Session = Depends(get_db)):
    masters = db.scalars(select(ProductMaster).order_by(ProductMaster.created_at.desc())).all()
    result = []
    for master in masters:
        _, latest = find_product_by_sku(db, master.internal_sku)
        result.append(
            {
                "id": master.id,
                "internal_sku": master.internal_sku,
                "internal_name": master.internal_name,
                "category_id": latest.category_id if latest else None,
                "latest_version_number": latest.version_number if latest else None,
            }
        )
    return result


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
