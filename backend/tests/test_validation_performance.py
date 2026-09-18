import uuid
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.core.enums import DraftStatus
from app.drafts import validation_service
from app.publication import preflight


def test_batch_validation_builds_shared_context_once_and_preflights_in_one_group(monkeypatch):
    drafts = [
        SimpleNamespace(id=uuid.uuid4(), sequence_number=index, status=DraftStatus.GENERATED)
        for index in range(1, 4)
    ]
    batch = SimpleNamespace(id=uuid.uuid4(), drafts=drafts)
    context = SimpleNamespace(version=object())
    db = MagicMock()

    build_local = MagicMock(return_value=context)
    validate_local = MagicMock(return_value=([], []))
    build_provider = MagicMock(return_value=object())
    build_payload = MagicMock(side_effect=lambda _ctx, draft, _urls: ({"draft": str(draft.id)}, []))
    validate_payloads = MagicMock(
        side_effect=lambda _ctx, payloads: {draft_id: [] for draft_id in payloads}
    )

    monkeypatch.setattr(validation_service, "build_validation_context", build_local)
    monkeypatch.setattr(validation_service, "validate_draft_with_context", validate_local)
    monkeypatch.setattr(validation_service, "build_preflight_context", build_provider)
    monkeypatch.setattr(validation_service, "build_preflight_payload", build_payload)
    monkeypatch.setattr(validation_service, "validate_preflight_payloads", validate_payloads)
    monkeypatch.setattr(validation_service, "ordered_image_urls", lambda *_args: ["https://image"])
    monkeypatch.setattr(validation_service, "_persist_outcomes", MagicMock())

    outcomes = validation_service.validate_batch_drafts(
        db,
        batch=batch,
        image_url_for=lambda image_id: f"https://images/{image_id}",
    )

    assert len(outcomes) == 3
    build_local.assert_called_once_with(db, batch)
    build_provider.assert_called_once_with(db, batch)
    assert validate_local.call_count == 3
    validate_payloads.assert_called_once()
    assert len(validate_payloads.call_args.args[1]) == 3


def test_preflight_payload_group_preserves_result_keys(monkeypatch):
    executor = ThreadPoolExecutor(max_workers=2)
    monkeypatch.setattr(preflight, "_get_preflight_executor", lambda: executor)
    monkeypatch.setattr(
        preflight,
        "validate_preflight_payload",
        lambda _context, payload: [{"code": payload["code"]}],
    )
    context = SimpleNamespace()
    try:
        result = preflight.validate_preflight_payloads(
            context,
            {"a": {"code": "A"}, "b": {"code": "B"}},
        )
    finally:
        executor.shutdown(wait=True)

    assert result == {
        "a": [{"code": "A"}],
        "b": [{"code": "B"}],
    }


def test_approve_ready_drafts_updates_all_without_committing_inside_service(monkeypatch):
    drafts = [
        SimpleNamespace(id=uuid.uuid4(), status=DraftStatus.READY),
        SimpleNamespace(id=uuid.uuid4(), status=DraftStatus.READY),
    ]
    scalars = MagicMock()
    scalars.all.return_value = drafts
    db = MagicMock()
    db.scalars.return_value = scalars
    audit = MagicMock()
    monkeypatch.setattr(validation_service, "audit", audit)

    result = validation_service.approve_ready_drafts(db, batch_id=uuid.uuid4())

    assert result == drafts
    assert all(draft.status == DraftStatus.APPROVED for draft in drafts)
    assert audit.call_count == 2
    db.commit.assert_not_called()
