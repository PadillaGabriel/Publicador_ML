import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.db import get_db
from app.technical_attributes.router import router
from app.technical_attributes.schemas import ImportTechnicalAttributesResult, ReuseTechnicalAttributesResult


PRODUCT_ID = uuid.uuid4()
ACCOUNT_ID = uuid.uuid4()


def _app_with_db(db):
    application = FastAPI()
    application.include_router(router)
    application.dependency_overrides[get_db] = lambda: db
    return application


def _db_with_entities():
    product = SimpleNamespace(id=PRODUCT_ID)
    account = SimpleNamespace(id=ACCOUNT_ID, active=True, site_id="MLA", seller_id="123")
    db = MagicMock()
    db.get.side_effect = lambda model, value: product if value == PRODUCT_ID else account if value == ACCOUNT_ID else None
    return db


def test_import_route_delegates_to_service(monkeypatch):
    from app.technical_attributes import router as module

    db = _db_with_entities()
    monkeypatch.setattr(
        module,
        "import_from_mla",
        lambda _db, **kwargs: ImportTechnicalAttributesResult(
            item_id="MLA123456789", category_id="MLA1000", imported_count=1, skipped_count=0
        ),
    )
    response = TestClient(_app_with_db(db)).post(
        f"/api/products/{PRODUCT_ID}/technical-attributes/import-mla",
        json={"account_id": str(ACCOUNT_ID), "item_id": "mla123456789"},
    )
    assert response.status_code == 200
    assert response.json()["item_id"] == "MLA123456789"


def test_reuse_route_delegates_with_query(monkeypatch):
    from app.technical_attributes import router as module

    db = _db_with_entities()
    monkeypatch.setattr(
        module,
        "resolve_reuse",
        lambda _db, **kwargs: ReuseTechnicalAttributesResult(
            product_id=PRODUCT_ID, category_id="MLA1000"
        ),
    )
    response = TestClient(_app_with_db(db)).get(
        f"/api/products/{PRODUCT_ID}/technical-attributes/reuse",
        params={"account_id": str(ACCOUNT_ID), "category_id": "MLA1000"},
    )
    assert response.status_code == 200
    assert response.json()["category_id"] == "MLA1000"


def test_unknown_product_returns_404():
    db = MagicMock()
    db.get.return_value = None
    response = TestClient(_app_with_db(db)).get(
        f"/api/products/{PRODUCT_ID}/technical-attributes/reuse",
        params={"account_id": str(ACCOUNT_ID), "category_id": "MLA1000"},
    )
    assert response.status_code == 404
