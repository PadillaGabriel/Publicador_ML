"""Validation of previously accepted images must not decode image bytes again."""
from types import SimpleNamespace

from app.publication.validation import validate_image_references


def test_accepted_image_is_checked_without_opening_or_decoding(tmp_path, monkeypatch):
    path = tmp_path / "accepted.jpg"
    path.write_bytes(b"previously validated at upload")

    def fail_read(*_args, **_kwargs):
        raise AssertionError("Validation must not read the image bytes")

    monkeypatch.setattr(type(path), "read_bytes", fail_read)
    assert validate_image_references([SimpleNamespace(storage_path=str(path), original_name="accepted.jpg")]) == []


def test_missing_image_is_reported_without_silently_passing(tmp_path):
    missing = tmp_path / "missing.jpg"
    errors = validate_image_references([SimpleNamespace(storage_path=str(missing), original_name="missing.jpg")])
    assert len(errors) == 1
    assert errors[0]["code"] == "INVALID_IMAGE"
    assert "missing.jpg" in errors[0]["message"]


def test_empty_image_is_reported(tmp_path):
    empty = tmp_path / "empty.jpg"
    empty.touch()
    errors = validate_image_references([SimpleNamespace(storage_path=str(empty), original_name="empty.jpg")])
    assert len(errors) == 1
    assert errors[0]["code"] == "INVALID_IMAGE"
