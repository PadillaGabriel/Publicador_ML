"""Account scope checks must not trust indirect resource IDs from the browser."""
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import operator_account_scope as scope


MY_ACCOUNT = uuid.uuid4()
OTHER_ACCOUNT = uuid.uuid4()
USER = SimpleNamespace(id=uuid.uuid4(), role="OPERATOR")


@pytest.fixture(autouse=True)
def grant_one_account(monkeypatch):
    monkeypatch.setattr(scope, "allowed_account_ids", lambda db, user: {MY_ACCOUNT})
    monkeypatch.setattr(scope, "batch_account", lambda db, identifier: OTHER_ACCOUNT if identifier == "foreign" else MY_ACCOUNT)
    monkeypatch.setattr(scope, "draft_account", lambda db, identifier: OTHER_ACCOUNT if identifier == "foreign" else MY_ACCOUNT)
    monkeypatch.setattr(scope, "job_accounts", lambda db, identifier: {MY_ACCOUNT, OTHER_ACCOUNT} if identifier == "mixed" else {MY_ACCOUNT})
    monkeypatch.setattr(scope, "version_product", lambda db, identifier: "foreign" if identifier == "foreign" else "own")
    monkeypatch.setattr(scope, "batch_product", lambda db, identifier: "foreign" if identifier == "foreign" else "own")
    monkeypatch.setattr(scope, "draft_product", lambda db, identifier: "foreign" if identifier == "foreign" else "own")
    monkeypatch.setattr(scope, "job_products", lambda db, identifier: {"own", "foreign"} if identifier == "mixed" else {"own"})
    def authorize(db, user, identifier):
        if identifier == "foreign":
            raise HTTPException(status_code=403, detail="Ficha ajena")
    monkeypatch.setattr(scope, "ensure_product", authorize)


@pytest.mark.parametrize("path,method,query,body", [
    ("/api/drafts/generate", "POST", {}, {"account_id": str(OTHER_ACCOUNT)}),
    ("/api/drafts/batches/foreign", "GET", {}, {}),
    ("/api/drafts/foreign/title", "PATCH", {}, {}),
    ("/api/publication/drafts/foreign/dry-run", "GET", {}, {}),
    ("/api/publication/jobs/mixed/export.xlsx", "GET", {}, {}),
    ("/api/publication/jobs", "POST", {}, {"batch_id": "foreign"}),
    ("/api/jobs/mixed", "GET", {}, {}),
    ("/api/jobs/mixed/events", "GET", {}, {}),
    ("/api/jobs/active/current", "GET", {}, {}),
    ("/api/publication/shipping-options", "GET", {"account_id": str(OTHER_ACCOUNT)}, {}),
    ("/api/publication-import/mla", "POST", {}, {"account_id": str(OTHER_ACCOUNT)}),
    ("/api/products/" + str(uuid.uuid4()) + "/technical-attributes/reuse", "GET", {"account_id": str(OTHER_ACCOUNT)}, {}),
    ("/api/title-intelligence/generate", "POST", {}, {}),
])
def test_cross_account_denied(path, method, query, body):
    with pytest.raises(HTTPException) as exc:
        scope.scope_operation(None, USER, path, method, query, body)
    assert exc.value.status_code == 403


@pytest.mark.parametrize("path,method,query,body", [
    ("/api/drafts/generate", "POST", {}, {"account_id": str(MY_ACCOUNT), "product_version_id": "own"}),
    ("/api/drafts/batches/own", "GET", {}, {}),
    ("/api/drafts/own/title", "PATCH", {}, {}),
    ("/api/publication/drafts/own/dry-run", "GET", {}, {}),
    ("/api/publication/jobs/own/export.xlsx", "GET", {}, {}),
    ("/api/publication/jobs", "POST", {}, {"batch_id": "own"}),
    ("/api/jobs/own", "GET", {}, {}),
    ("/api/jobs/own/events", "GET", {}, {}),
])
def test_authorized_account(path, method, query, body):
    scope.scope_operation(None, USER, path, method, query, body)


def test_unknown_publication_operation_denied():
    with pytest.raises(HTTPException) as exc:
        scope.scope_operation(None, USER, "/api/publication/not-classified", "GET", {}, {})
    assert exc.value.status_code == 403


def test_missing_account_identifier_is_denied():
    with pytest.raises(HTTPException) as exc:
        scope.scope_operation(None, USER, "/api/drafts/generate", "POST", {}, {})
    assert exc.value.status_code == 422


@pytest.mark.parametrize("path,method", [
    ("/api/products", "POST"),
    ("/api/products", "GET"),
    ("/api/products/lookup", "GET"),
    ("/api/products/versions/" + str(uuid.uuid4()), "GET"),
    ("/api/products/versions/" + str(uuid.uuid4()) + "/images/batch", "POST"),
])
def test_product_routes_use_owner_and_lease_in_handler(path, method):
    scope.scope_operation(None, USER, path, method, {}, {})


def test_unclassified_product_write_denied():
    with pytest.raises(HTTPException) as exc:
        scope.scope_operation(None, USER, "/api/products/unknown/write", "POST", {}, {})
    assert exc.value.status_code == 403


@pytest.mark.parametrize("path,method,body", [
    ("/api/drafts/generate", "POST", {"account_id": str(MY_ACCOUNT), "product_version_id": "foreign"}),
    ("/api/drafts/batches/foreign", "GET", {}),
    ("/api/drafts/foreign/validate", "POST", {}),
    ("/api/publication/jobs", "POST", {"batch_id": "foreign"}),
    ("/api/publication/drafts/foreign/dry-run", "GET", {}),
    ("/api/jobs/foreign", "GET", {}),
    ("/api/publication/jobs/foreign/export.xlsx", "GET", {}),
])
def test_same_account_foreign_product_denied(path, method, body, monkeypatch):
    # Simulate an owner mismatch without relying on an account-grant mismatch.
    monkeypatch.setattr(scope, "batch_account", lambda db, identifier: MY_ACCOUNT)
    monkeypatch.setattr(scope, "draft_account", lambda db, identifier: MY_ACCOUNT)
    monkeypatch.setattr(scope, "job_accounts", lambda db, identifier: {MY_ACCOUNT})
    monkeypatch.setattr(scope, "job_products", lambda db, identifier: {"foreign"})
    with pytest.raises(HTTPException) as error:
        scope.scope_operation(None, USER, path, method, {}, body)
    assert error.value.status_code == 403


def test_operator_may_correct_own_batch_only_when_handler_validates_lease():
    # Account/ownership are resolved at the boundary. The handler enforces
    # expected_version and the fencing token in its write transaction.
    scope.scope_operation(None, USER, "/api/drafts/batches/own/product-correction", "POST", {}, {})
    with pytest.raises(HTTPException) as error:
        scope.scope_operation(None, USER, "/api/drafts/batches/foreign/product-correction", "POST", {}, {})
    assert error.value.status_code == 403


def test_admin_can_still_rebase_product():
    scope.scope_operation(None, SimpleNamespace(role="ADMIN"), "/api/drafts/batches/own/product-correction", "POST", {}, {})


@pytest.mark.parametrize("path,method,query,body", [
    ("/api/pricing/simulate", "POST", {}, {"account_id": str(OTHER_ACCOUNT)}),
    ("/api/pricing/logistics-quotes", "POST", {}, {"account_id": str(OTHER_ACCOUNT)}),
    ("/api/catalog/category-suggestions", "GET", {"account_id": str(OTHER_ACCOUNT)}, {}),
])
def test_pricing_and_catalog_respect_account_grants(path, method, query, body):
    with pytest.raises(HTTPException) as exc:
        scope.scope_operation(None, USER, path, method, query, body)
    assert exc.value.status_code == 403


@pytest.mark.parametrize("path,method,query,body", [
    ("/api/pricing/simulate", "POST", {}, {"account_id": str(MY_ACCOUNT)}),
    ("/api/pricing/logistics-quotes", "POST", {}, {"account_id": str(MY_ACCOUNT)}),
    ("/api/catalog/category-suggestions", "GET", {"account_id": str(MY_ACCOUNT)}, {}),
])
def test_pricing_and_catalog_allow_granted_account(path, method, query, body):
    scope.scope_operation(None, USER, path, method, query, body)
