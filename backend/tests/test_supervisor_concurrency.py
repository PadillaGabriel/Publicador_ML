from types import SimpleNamespace

from app import run


def test_worker_count_uses_configured_processes(monkeypatch):
    monkeypatch.setattr(
        run,
        "get_settings",
        lambda: SimpleNamespace(worker_processes=2, cleanup_uploads_after_success=False),
    )
    assert run._worker_count() == 2


def test_worker_count_caps_to_one_when_upload_cleanup_is_enabled(monkeypatch):
    monkeypatch.setattr(
        run,
        "get_settings",
        lambda: SimpleNamespace(worker_processes=3, cleanup_uploads_after_success=True),
    )
    assert run._worker_count() == 1
