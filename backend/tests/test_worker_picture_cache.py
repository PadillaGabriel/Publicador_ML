import uuid
from types import SimpleNamespace

from app import worker


class FakeClient:
    def __init__(self):
        self.calls = []

    def upload_item_picture(self, storage_path, mime_type):
        self.calls.append((storage_path, mime_type))
        return {"id": f"PIC-{storage_path}"}


def test_picture_ids_are_uploaded_once_per_job_and_reused_in_draft_order(monkeypatch):
    monkeypatch.setattr(worker.settings, "worker_image_upload_concurrency", 2)
    first = SimpleNamespace(id=uuid.uuid4(), storage_path="a.jpg", mime_type="image/jpeg")
    second = SimpleNamespace(id=uuid.uuid4(), storage_path="b.jpg", mime_type="image/jpeg")
    client = FakeClient()
    cache = {}

    initial = worker._picture_ids_for_images(client, [first, second], cache)
    reordered = worker._picture_ids_for_images(client, [second, first], cache)

    assert set(initial) == {"PIC-a.jpg", "PIC-b.jpg"}
    assert reordered == ["PIC-b.jpg", "PIC-a.jpg"]
    assert sorted(client.calls) == [
        ("a.jpg", "image/jpeg"),
        ("b.jpg", "image/jpeg"),
    ]
