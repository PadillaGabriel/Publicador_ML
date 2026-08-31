from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from io import BytesIO
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from app.core.config import get_settings


@dataclass(frozen=True, slots=True)
class ImageInspection:
    width: int
    height: int
    format: str


class ImagePolicyError(ValueError):
    """Raised when an uploaded image cannot satisfy the publication image policy."""


def inspect_image(content: bytes) -> ImageInspection:
    """Read image metadata without persisting or transforming the original file."""
    try:
        with Image.open(BytesIO(content)) as image:
            image.verify()
        with Image.open(BytesIO(content)) as image:
            return ImageInspection(
                width=int(image.width),
                height=int(image.height),
                format=str(image.format or "").upper(),
            )
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ImagePolicyError("El archivo no contiene una imagen válida.") from exc


def validate_image_content(content: bytes) -> ImageInspection:
    """Validate image dimensions and format before accepting the upload.

    Mercado Libre's seller guidance requires images large enough to support zoom and
    recommends 1200 x 1200 px. We enforce the documented minimum side configured for
    the application and expose the recommendation separately instead of inventing a
    hard maximum resolution not present in the current public guidance.
    """
    settings = get_settings()
    inspection = inspect_image(content)

    if inspection.format not in settings.ml_image_allowed_formats:
        allowed = ", ".join(sorted(settings.ml_image_allowed_formats))
        raise ImagePolicyError(
            f"Formato de imagen no permitido. Usá uno de estos formatos: {allowed}."
        )

    if inspection.width < settings.ml_image_min_side_px or inspection.height < settings.ml_image_min_side_px:
        raise ImagePolicyError(
            "La imagen es demasiado pequeña para Mercado Libre: "
            f"{inspection.width}x{inspection.height}px. "
            f"El mínimo configurado es {settings.ml_image_min_side_px}px por lado."
        )

    return inspection


@lru_cache(maxsize=512)
def _cached_file_validation(path_text: str, modified_ns: int, size: int) -> ImageInspection:
    del modified_ns, size
    return validate_image_content(Path(path_text).read_bytes())


def validate_stored_image(path: str) -> ImageInspection:
    file_path = Path(path)
    stat = file_path.stat()
    return _cached_file_validation(str(file_path), stat.st_mtime_ns, stat.st_size)
