from collections.abc import Iterable
from pathlib import Path
from typing import Protocol


class StoredImage(Protocol):
    storage_path: str


def cleanup_temporary_product_images(
    images: Iterable[StoredImage],
    upload_root: Path,
) -> tuple[int, int]:
    """Delete persisted upload bytes that belong to the configured temporary root.

    Database metadata is intentionally retained for auditability. A cleared
    ``storage_path`` explicitly signals that the bytes are no longer available
    locally and must be uploaded again before a future publication attempt.
    """

    root = upload_root.resolve()
    deleted_files = 0
    deleted_bytes = 0

    for image in images:
        raw_path = str(image.storage_path or "").strip()
        if not raw_path:
            continue

        path = Path(raw_path)
        try:
            resolved = path.resolve()
        except OSError:
            continue

        if not resolved.is_relative_to(root):
            continue

        try:
            size = resolved.stat().st_size
        except FileNotFoundError:
            image.storage_path = ""
            continue

        try:
            resolved.unlink()
        except FileNotFoundError:
            image.storage_path = ""
            continue

        image.storage_path = ""
        deleted_files += 1
        deleted_bytes += size

    return deleted_files, deleted_bytes
