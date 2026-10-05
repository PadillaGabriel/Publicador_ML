"""Isolation tests for ML-hosted pictures in preflight; no DB/provider needed."""
import ast
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

PREFLIGHT_PATH = Path(__file__).resolve().parents[1] / "app/publication/preflight.py"
ROUTER_PATH = Path(__file__).resolve().parents[1] / "app/drafts/router.py"
VALIDATION_PATH = Path(__file__).resolve().parents[1] / "app/drafts/validation_service.py"


def _functions():
    root = ast.parse(PREFLIGHT_PATH.read_text(encoding="utf-8"))
    return [node for node in root.body if isinstance(node, ast.FunctionDef) and node.name in {
        "upload_preflight_pictures", "ordered_preflight_pictures"
    }]


def _isolated_contract(monkeypatch):
    fake_client = MagicMock()
    fake_client.upload_item_picture.side_effect = lambda path, _mime: {"id": f"ML-{path}"}
    context = SimpleNamespace(
        access_token="not-a-real-token",
        version=SimpleNamespace(images=[
            SimpleNamespace(id="one", storage_path="one.jpg", mime_type="image/jpeg"),
            SimpleNamespace(id="two", storage_path="two.jpg", mime_type="image/jpeg"),
        ]),
    )
    ns = {
        "ThreadPoolExecutor": ThreadPoolExecutor,
        "as_completed": as_completed,
        "MercadoLibreClient": lambda token: fake_client,
        "HTTPException": HTTPException,
        "PublicationPreflightContext": object,
        "PublicationDraft": object,
    }
    module = ast.fix_missing_locations(ast.Module(body=_functions(), type_ignores=[]))
    exec(compile(module, str(PREFLIGHT_PATH), "exec"), ns)
    return ns, fake_client, context


def test_batch_uploads_two_unique_images_once_and_keeps_per_draft_order(monkeypatch):
    ns, client, context = _isolated_contract(monkeypatch)
    drafts = [SimpleNamespace(image_order=["one", "two"]), SimpleNamespace(image_order=["two", "one"])]
    uploaded = ns["upload_preflight_pictures"](context, drafts)
    assert uploaded == {"one": "ML-one.jpg", "two": "ML-two.jpg"}
    assert client.upload_item_picture.call_count == 2
    assert ns["ordered_preflight_pictures"](drafts[0], uploaded) == [
        {"id": "ML-one.jpg"}, {"id": "ML-two.jpg"},
    ]
    assert ns["ordered_preflight_pictures"](drafts[1], uploaded) == [
        {"id": "ML-two.jpg"}, {"id": "ML-one.jpg"},
    ]


def test_preflight_rejects_stale_image_before_upload(monkeypatch):
    ns, client, context = _isolated_contract(monkeypatch)
    with pytest.raises(HTTPException) as error:
        ns["upload_preflight_pictures"](context, [SimpleNamespace(image_order=["removed"])])
    assert error.value.status_code == 422
    client.upload_item_picture.assert_not_called()


def test_private_upload_routes_are_not_embedded_into_validation():
    assert 'url_for("serve_upload"' not in ROUTER_PATH.read_text(encoding="utf-8")
    source = VALIDATION_PATH.read_text(encoding="utf-8")
    assert "ordered_preflight_pictures" in source
    assert "upload_preflight_pictures" in source
    assert "image_url_for" not in source
