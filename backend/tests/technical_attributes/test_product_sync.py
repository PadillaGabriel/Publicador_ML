import sys
import types
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

# app.drafts.service imports the OpenAI adapter at module load; the rebase path
# exercised here never calls OpenAI, so provide the missing optional SDK symbols
# in this sandbox-only test environment.
if "openai" not in sys.modules:
    fake_openai = types.ModuleType("openai")
    for name in ("APIConnectionError", "APIStatusError", "RateLimitError"):
        setattr(fake_openai, name, type(name, (Exception,), {}))
    setattr(fake_openai, "OpenAI", object)
    sys.modules["openai"] = fake_openai

from app.drafts import service as drafts_service
from app.persistence import DraftBatch, ProductVersion
from app.products import service as products_service


class Payload(SimpleNamespace):
    pass


def _payload():
    return Payload(
        internal_sku="SKU-1",
        internal_name="Producto",
        category_id="MLA1",
        title_reference="Producto",
        description="",
        price=1000,
        quantity=1,
        condition="new",
        currency_id="ARS",
        listing_type_id="gold_special",
        attributes={"BRAND": {"value_name": "Marca X"}},
        commercial={},
        logistics={},
        discovery_context={},
    )


def test_save_product_version_syncs_technical_library(monkeypatch):
    db = MagicMock()
    db.scalar.return_value = None

    def flush():
        for call in db.add.call_args_list:
            obj = call.args[0]
            if hasattr(obj, "id") and obj.id is None:
                obj.id = uuid.uuid4()
    db.flush.side_effect = flush
    monkeypatch.setattr(products_service, "audit", lambda *args, **kwargs: None)
    captured = {}
    monkeypatch.setattr(
        products_service,
        "upsert_product_attributes",
        lambda _db, **kwargs: captured.update(kwargs) or [],
        raising=False,
    )

    master, version, created = products_service.save_product_version(db, _payload())

    assert created is True
    assert captured["product_master_id"] == master.id
    assert captured["attributes"] == {"BRAND": {"value_name": "Marca X"}}
    assert captured["source_category_id"] == "MLA1"
    assert captured["source_kind"] == "PRODUCT_VERSION"
    assert captured["source_reference"] == str(version.id)


def test_rebase_syncs_corrected_product_version(monkeypatch):
    batch_id = uuid.uuid4()
    current_id = uuid.uuid4()
    master_id = uuid.uuid4()
    batch = SimpleNamespace(id=batch_id, product_version_id=current_id, drafts=[])
    current = SimpleNamespace(
        id=current_id,
        product_master_id=master_id,
        version_number=1,
        category_id="MLA1",
        title_reference="Producto",
        condition="new",
        currency_id="ARS",
        listing_type_id="gold_special",
        discovery_context={},
        images=[],
    )
    db = MagicMock()
    db.get.side_effect = lambda model, key: batch if model is DraftBatch and key == batch_id else current if model is ProductVersion and key == current_id else None
    db.scalar.return_value = 1

    def flush():
        for call in db.add.call_args_list:
            obj = call.args[0]
            if isinstance(obj, ProductVersion) and obj.id is None:
                obj.id = uuid.uuid4()
    db.flush.side_effect = flush
    monkeypatch.setattr(drafts_service, "audit", lambda *args, **kwargs: None)
    captured = {}
    monkeypatch.setattr(
        drafts_service,
        "upsert_product_attributes",
        lambda _db, **kwargs: captured.update(kwargs) or [],
        raising=False,
    )

    corrected = drafts_service.rebase_batch_product_version(
        db,
        batch_id=batch_id,
        description="Corregido",
        price=1200,
        quantity=2,
        attributes={"MATERIAL": {"value_name": "Acero"}},
        commercial={},
        logistics={},
    )

    assert captured["product_master_id"] == master_id
    assert captured["attributes"] == {"MATERIAL": {"value_name": "Acero"}}
    assert captured["source_category_id"] == "MLA1"
    assert captured["source_kind"] == "PRODUCT_VERSION"
    assert captured["source_reference"] == str(corrected.id)
