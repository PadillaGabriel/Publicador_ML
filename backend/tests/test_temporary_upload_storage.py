from dataclasses import dataclass
from pathlib import Path

from app.products.storage import cleanup_temporary_product_images


@dataclass
class _Image:
    storage_path: str


def test_cleanup_temporary_product_images_deletes_only_files_under_upload_root(tmp_path: Path):
    upload_root = tmp_path / "uploads"
    upload_root.mkdir()
    first = upload_root / "a.jpg"
    second = upload_root / "b.jpg"
    outside = tmp_path / "outside.jpg"
    first.write_bytes(b"abc")
    second.write_bytes(b"12345")
    outside.write_bytes(b"keep")

    images = [_Image(str(first)), _Image(str(second)), _Image(str(outside))]

    deleted_files, deleted_bytes = cleanup_temporary_product_images(images, upload_root)

    assert deleted_files == 2
    assert deleted_bytes == 8
    assert first.exists() is False
    assert second.exists() is False
    assert outside.exists() is True
    assert images[0].storage_path == ""
    assert images[1].storage_path == ""
    assert images[2].storage_path == str(outside)
