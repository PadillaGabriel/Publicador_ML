from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit.service import audit
from app.persistence import ProductImage, ProductVersion


class ProductImageUploadError(RuntimeError):
    """Raised when one or more validated images cannot be persisted."""


@dataclass(frozen=True, slots=True)
class StagedProductImage:
    id: uuid.UUID
    original_name: str
    mime_type: str
    storage_path: Path


def stage_product_image(
    *,
    original_name: str,
    mime_type: str,
    content: bytes,
    upload_dir: Path,
) -> StagedProductImage:
    """Write one already validated image to its final local path without touching the DB."""

    image_id = uuid.uuid4()
    suffix = Path(original_name or "image").suffix.lower()[:10]
    path = upload_dir / f"{image_id}{suffix}"
    path.write_bytes(content)
    return StagedProductImage(
        id=image_id,
        original_name=original_name or str(image_id),
        mime_type=mime_type,
        storage_path=path,
    )


def cleanup_staged_images(images: list[StagedProductImage]) -> None:
    for image in images:
        image.storage_path.unlink(missing_ok=True)


def persist_staged_product_images(
    db: Session,
    *,
    version_id: uuid.UUID,
    staged_images: list[StagedProductImage],
) -> list[ProductImage]:
    """Persist a batch with one row lock, one MAX(position) lookup and one commit."""

    if not staged_images:
        return []

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
        start_position = int(current_max or 0) + 1

        images: list[ProductImage] = []
        for offset, staged in enumerate(staged_images):
            position = start_position + offset
            image = ProductImage(
                id=staged.id,
                product_version_id=version_id,
                original_name=staged.original_name,
                storage_path=str(staged.storage_path),
                mime_type=staged.mime_type,
                position=position,
            )
            images.append(image)
            db.add(image)
            audit(
                db,
                "PRODUCT_IMAGE_UPLOADED",
                "ProductVersion",
                str(version_id),
                {"image_id": str(image.id), "position": position},
            )

        db.commit()
        return images
    except Exception:
        db.rollback()
        cleanup_staged_images(staged_images)
        raise


def persist_product_image(
    db: Session,
    *,
    version_id: uuid.UUID,
    original_name: str,
    mime_type: str,
    content: bytes,
    upload_dir: Path,
) -> ProductImage:
    """Compatibility path for a single image upload."""

    staged = stage_product_image(
        original_name=original_name,
        mime_type=mime_type,
        content=content,
        upload_dir=upload_dir,
    )
    return persist_staged_product_images(
        db,
        version_id=version_id,
        staged_images=[staged],
    )[0]
