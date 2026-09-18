import uuid
from unittest.mock import MagicMock

import pytest

from app.products import image_upload
from app.products.image_upload import persist_product_image


def test_persist_product_image_assigns_next_position_under_version_lock(tmp_path, monkeypatch):
    db = MagicMock()
    db.scalar.side_effect = [object(), 4]
    monkeypatch.setattr(image_upload, "audit", MagicMock())
    version_id = uuid.uuid4()

    stored = persist_product_image(
        db,
        version_id=version_id,
        original_name="producto.png",
        mime_type="image/png",
        content=b"image-bytes",
        upload_dir=tmp_path,
    )

    lock_statement = db.scalar.call_args_list[0].args[0]
    assert "FOR UPDATE" in str(lock_statement)
    assert stored.product_version_id == version_id
    assert stored.position == 5
    assert stored.storage_path.endswith(".png")
    assert db.commit.call_count == 1
    assert (tmp_path / f"{stored.id}.png").read_bytes() == b"image-bytes"


def test_persist_product_image_removes_file_when_commit_fails(tmp_path, monkeypatch):
    db = MagicMock()
    db.scalar.side_effect = [object(), 0]
    db.commit.side_effect = RuntimeError("database unavailable")
    monkeypatch.setattr(image_upload, "audit", MagicMock())

    with pytest.raises(RuntimeError, match="database unavailable"):
        persist_product_image(
            db,
            version_id=uuid.uuid4(),
            original_name="producto.jpg",
            mime_type="image/jpeg",
            content=b"image-bytes",
            upload_dir=tmp_path,
        )

    assert list(tmp_path.iterdir()) == []
    db.rollback.assert_called_once()
