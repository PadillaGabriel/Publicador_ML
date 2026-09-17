import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.technical_attributes import service


class FakeSession:
    def __init__(self, existing=None):
        self.existing = existing
        self.added = []
        self.flushed = 0

    def scalar(self, statement):
        return self.existing

    def scalars(self, statement):
        rows = [] if self.existing is None else [self.existing]
        return SimpleNamespace(all=lambda: rows)

    def add(self, value):
        self.added.append(value)

    def flush(self):
        self.flushed += 1


class BatchSession(FakeSession):
    def __init__(self, existing_rows=None):
        super().__init__(existing=None)
        self.existing_rows = list(existing_rows or [])
        self.scalar_calls = 0
        self.scalars_calls = 0

    def scalar(self, statement):
        self.scalar_calls += 1
        return None

    def scalars(self, statement):
        self.scalars_calls += 1
        return SimpleNamespace(all=lambda: list(self.existing_rows))


def test_upsert_prefetches_existing_attributes_in_one_query():
    product_id = uuid.uuid4()
    db = BatchSession()

    service.upsert_product_attributes(
        db,
        product_master_id=product_id,
        attributes={
            "BRAND": {"value_name": "Marca X"},
            "MATERIAL": {"value_name": "Acero"},
            "COLOR": {"value_name": "Negro"},
        },
        source_category_id="MLA1",
        source_kind="MLA_IMPORT",
        source_reference="MLA123",
    )

    assert db.scalars_calls == 1
    assert db.scalar_calls == 0
    assert len(db.added) == 3


def test_upsert_updates_existing_attribute_without_duplicate():
    product_id = uuid.uuid4()
    existing = SimpleNamespace(
        product_master_id=product_id,
        attribute_id="BRAND",
        value={"value_name": "Vieja"},
        source_category_id="MLA1",
        source_kind="PRODUCT_VERSION",
        source_reference="old",
    )
    db = FakeSession(existing=existing)

    rows = service.upsert_product_attributes(
        db,
        product_master_id=product_id,
        attributes={"BRAND": {"value_name": "Nueva"}, "SELLER_SKU": "SKU-X"},
        source_category_id="MLA2",
        source_kind="MLA_IMPORT",
        source_reference="MLA123",
    )

    assert rows == [existing]
    assert db.added == []
    assert existing.value == {"value_name": "Nueva"}
    assert existing.source_category_id == "MLA2"
    assert existing.source_reference == "MLA123"


def test_preview_mla_filters_non_reusable_attributes(monkeypatch):
    db = MagicMock()
    account = SimpleNamespace(id=uuid.uuid4(), site_id="MLA", seller_id="9988")
    item = {
        "id": "MLA123",
        "site_id": "MLA",
        "seller_id": 9988,
        "category_id": "MLA1000",
        "title": "Producto",
        "attributes": [
            {"id": "BRAND", "name": "Marca", "value_name": "Marca X"},
            {"id": "SELLER_SKU", "name": "SKU", "value_name": "SKU-1"},
        ],
    }
    monkeypatch.setattr(service, "load_access_token", lambda _db, _id: "token")
    client = MagicMock()
    client.item.return_value = item
    monkeypatch.setattr(service, "MercadoLibreClient", lambda _token: client)

    result = service.preview_mla(db, account=account, item_id="mla123")

    assert [row.attribute_id for row in result.attributes] == ["BRAND"]
    assert [row.attribute_id for row in result.skipped] == ["SELLER_SKU"]
    assert result.seller_sku == "SKU-1"


@pytest.mark.parametrize(
    ("site_id", "seller_id"),
    [("MLB", "9988"), ("MLA", "7777")],
)
def test_preview_rejects_wrong_site_or_seller(monkeypatch, site_id, seller_id):
    db = MagicMock()
    account = SimpleNamespace(id=uuid.uuid4(), site_id="MLA", seller_id="9988")
    monkeypatch.setattr(service, "load_access_token", lambda _db, _id: "token")
    client = MagicMock()
    client.item.return_value = {
        "id": "MLA123",
        "site_id": site_id,
        "seller_id": seller_id,
        "category_id": "MLA1000",
        "title": "Producto",
        "attributes": [],
    }
    monkeypatch.setattr(service, "MercadoLibreClient", lambda _token: client)

    with pytest.raises(HTTPException) as exc:
        service.preview_mla(db, account=account, item_id="MLA123")
    assert exc.value.status_code == 422


def test_resolve_reuse_separates_reusable_incompatible_and_pending(monkeypatch):
    db = MagicMock()
    product = SimpleNamespace(id=uuid.uuid4())
    account = SimpleNamespace(id=uuid.uuid4(), site_id="MLA")
    rows = [
        SimpleNamespace(
            attribute_id="BRAND", value={"value_id": "1", "value_name": "Marca X"},
            source_category_id="MLA1", source_kind="MLA_IMPORT", source_reference="MLA123",
        ),
        SimpleNamespace(
            attribute_id="MATERIAL", value={"value_name": "Madera"},
            source_category_id="MLA1", source_kind="PRODUCT_VERSION", source_reference="v1",
        ),
        SimpleNamespace(
            attribute_id="OLD_FIELD", value={"value_name": "Viejo"},
            source_category_id="MLA1", source_kind="PRODUCT_VERSION", source_reference="v1",
        ),
    ]
    db.scalars.return_value.all.return_value = rows
    monkeypatch.setattr(service, "load_access_token", lambda _db, _id: "token")
    snapshot = SimpleNamespace(raw_category={"settings": {"listing_allowed": True}, "children_categories": []}, normalized_schema={"fields": [
        {"id": "BRAND", "label": "Marca", "value_type": "list", "hidden": False, "importance": "required", "allow_custom_value": False, "values": [{"id": "1", "name": "Marca X"}]},
        {"id": "MATERIAL", "label": "Material", "value_type": "list", "hidden": False, "importance": "recommended", "allow_custom_value": False, "values": [{"id": "2", "name": "Acero"}]},
        {"id": "COLOR", "label": "Color", "value_type": "string", "hidden": False, "importance": "recommended", "allow_custom_value": True, "values": []},
    ]})
    metadata = MagicMock(return_value=snapshot)
    monkeypatch.setattr(service, "get_category_metadata", metadata)
    monkeypatch.setattr(service, "audit", lambda *args, **kwargs: None)

    result = service.resolve_reuse(db, product=product, account=account, category_id="MLA9")

    assert [item.attribute_id for item in result.reusable] == ["BRAND"]
    assert {item.attribute_id for item in result.incompatible} == {"MATERIAL", "OLD_FIELD"}
    assert [item.attribute_id for item in result.pending] == ["COLOR", "MATERIAL"]
    metadata.assert_called_once()


def test_product_version_upsert_audits_update(monkeypatch):
    product_id = uuid.uuid4()
    db = FakeSession(existing=None)
    events = []
    monkeypatch.setattr(service, "audit", lambda *args, **kwargs: events.append((args, kwargs)))

    service.upsert_product_attributes(
        db,
        product_master_id=product_id,
        attributes={"BRAND": {"value_name": "Marca X"}},
        source_category_id="MLA1",
        source_kind="PRODUCT_VERSION",
        source_reference="version-1",
    )

    assert events
    assert events[0][0][1] == "TECHNICAL_ATTRIBUTES_UPDATED_FROM_VERSION"


def test_resolve_reuse_rejects_non_publishable_category(monkeypatch):
    db = MagicMock()
    product = SimpleNamespace(id=uuid.uuid4())
    account = SimpleNamespace(id=uuid.uuid4(), site_id="MLA")
    monkeypatch.setattr(service, "load_access_token", lambda _db, _id: "token")
    snapshot = SimpleNamespace(normalized_schema={"fields": []}, raw_category={"settings": {"listing_allowed": False}})
    monkeypatch.setattr(service, "get_category_metadata", lambda *args, **kwargs: snapshot)

    with pytest.raises(HTTPException) as exc:
        service.resolve_reuse(db, product=product, account=account, category_id="MLA9")
    assert exc.value.status_code == 422


def test_preview_mla_does_not_require_product_and_returns_publication_context(monkeypatch):
    db = MagicMock()
    account = SimpleNamespace(id=uuid.uuid4(), site_id="MLA", seller_id="9988")
    item = {
        "id": "MLA123",
        "site_id": "MLA",
        "seller_id": 9988,
        "title": "Organizador transparente",
        "condition": "new",
        "category_id": "MLA1000",
        "seller_custom_field": "SKU-LEGACY",
        "attributes": [
            {"id": "SELLER_SKU", "name": "SKU", "value_name": "SKU-123"},
            {"id": "BRAND", "name": "Marca", "value_name": "Silmar"},
            {"id": "MATERIAL", "name": "Material", "value_name": "Poliestireno"},
        ],
    }
    monkeypatch.setattr(service, "load_access_token", lambda _db, _id: "token")
    client = MagicMock()
    client.item.return_value = item
    monkeypatch.setattr(service, "MercadoLibreClient", lambda _token: client)

    client.item_description.return_value = {"plain_text": "Descripción original del producto"}

    result = service.preview_mla(db, account=account, item_id="mla123")

    assert result.item_id == "MLA123"
    assert result.title == "Organizador transparente"
    assert result.category_id == "MLA1000"
    assert result.condition == "new"
    assert result.seller_sku == "SKU-123"
    assert result.description == "Descripción original del producto"
    assert [row.attribute_id for row in result.attributes] == ["BRAND", "MATERIAL"]
    db.add.assert_not_called()
    db.commit.assert_not_called()


def test_resolve_preview_mla_reuses_only_compatible_destination_fields(monkeypatch):
    db = MagicMock()
    account = SimpleNamespace(id=uuid.uuid4(), site_id="MLA", seller_id="9988")
    preview = service.MlaPublicationSnapshot(
        item_id="MLA123",
        title="Producto",
        category_id="MLA1",
        attributes=[
            service.TechnicalAttributeRecord(
                attribute_id="BRAND",
                label="Marca",
                value={"value_name": "Silmar"},
                source_category_id="MLA1",
                source_kind="MLA_IMPORT",
                source_reference="MLA123",
                status="IMPORTADO",
            ),
            service.TechnicalAttributeRecord(
                attribute_id="COLOR",
                label="Color",
                value={"value_id": "RED", "value_name": "Rojo"},
                source_category_id="MLA1",
                source_kind="MLA_IMPORT",
                source_reference="MLA123",
                status="IMPORTADO",
            ),
        ],
    )
    monkeypatch.setattr(service, "preview_mla", lambda *args, **kwargs: preview)
    monkeypatch.setattr(
        service,
        "_category_fields",
        lambda *args, **kwargs: (
            "MLA2",
            [
                {"id": "BRAND", "label": "Marca", "value_type": "string", "allow_custom_value": True, "importance": "required"},
                {"id": "COLOR", "label": "Color", "value_type": "list", "values": [{"id": "BLUE", "name": "Azul"}], "importance": "recommended"},
            ],
        ),
    )

    result = service.resolve_preview_mla(db, account=account, item_id="MLA123", category_id="MLA2")

    assert [row.attribute_id for row in result.reusable] == ["BRAND"]
    assert [row.attribute_id for row in result.incompatible] == ["COLOR"]
