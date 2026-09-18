from __future__ import annotations

import uuid
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit.service import audit
from app.persistence import ProductImage, ProductVersion


class ProductImageUploadError(RuntimeError):
    """Raised when an image cannot be persisted for a product version."""


def persist_product_image(
    db: Session,
    *,
    version_id: uuid.UUID,
    original_name: str,
    mime_type: str,
    content: bytes,
    upload_dir: Path,
) -> ProductImage:
    """Persist one validated image with a race-safe position assignment.

    File validation happens before this function. The product-version row is locked
    only for the short persistence section, allowing multiple uploads to transfer and
    validate concurrently while serializing the position allocation itself.
    """

    image_id = uuid.uuid4()
    suffix = Path(original_name or "image").suffix.lower()[:10]
    path = upload_dir / f"{image_id}{suffix}"
    path.write_bytes(content)

    try:
        version = db.scalar(
            select(ProductVersion)
            .where(ProductVersion.id == version_id)
            .with_for_update()
        )
        if version is None:
            raise ProductImageUploadError("Version not found.")

        current_max = db.scalar(
            select(func.max(ProductImage.position)).where(
                ProductImage.product_version_id == version_id
            )
        )
        position = int(current_max or 0) + 1

        image = ProductImage(
            id=image_id,
            product_version_id=version_id,
            original_name=original_name or str(image_id),
            storage_path=str(path),
            mime_type=mime_type,
            position=position,
        )
        db.add(image)
        audit(
            db,
            "PRODUCT_IMAGE_UPLOADED",
            "ProductVersion",
            str(version_id),
            {"image_id": str(image.id), "position": position},
        )
        db.commit()
        return image
    except Exception:
        db.rollback()
        path.unlink(missing_ok=True)
        raise
