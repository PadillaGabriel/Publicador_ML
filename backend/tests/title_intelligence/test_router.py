from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.accounts import service as accounts_service
from app.core.db import get_db
from app.core.time import utcnow
from app.integrations.mercadolibre.client import MercadoLibreClient, MercadoLibreError
from app.main import app
from app.persistence import KeywordTrendSnapshot
from app.publication import router as publication_router


class _Account:
    active = True
    site_id = "MLA"


class _Db:
    def __init__(
        self,
        account: _Account | None = None,
        snapshot: KeywordTrendSnapshot | None = None,
    ) -> None:
        self.account = account
        self.snapshot = snapshot
        self.added = []
        self.commits = 0

    def get(self, _model, _account_id):
        return self.account

    def scalar(self, _query):
        return self.snapshot

    def add(self, value) -> None:
        self.added.append(value)

    def flush(self) -> None:
        pass

    def commit(self) -> None:
        self.commits += 1


class _PublicationSpy:
    def __init__(self) -> None:
        self.calls = 0

    def create_job(self, *args, **kwargs) -> None:
        self.calls += 1


def _payload(**overrides):
    payload = {
        "account_id": str(uuid4()),
        "category_id": "MLA412517",
        "product_name": "Cesto plástico plegable",
        "attributes": {"capacity": "40 L", "use": "ropa"},
        "max_length": 60,
    }
    payload.update(overrides)
    return payload


def _client(db: _Db) -> TestClient:
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


_MISSING_OVERRIDE = object()


@pytest.fixture(autouse=True)
def _restore_get_db_override():
    previous = app.dependency_overrides.get(get_db, _MISSING_OVERRIDE)
    yield
    if previous is _MISSING_OVERRIDE:
        app.dependency_overrides.pop(get_db, None)
    else:
        app.dependency_overrides[get_db] = previous


def test_generate_returns_factual_fallback_when_trends_are_unavailable(monkeypatch):
    """Catches an unavailable category-trends provider becoming an HTTP failure."""
    monkeypatch.setattr(accounts_service, "load_access_token", lambda *_: "token")
    monkeypatch.setattr(
        MercadoLibreClient,
        "category_trends",
        lambda *_: (_ for _ in ()).throw(MercadoLibreError("provider unavailable")),
    )

    db = _Db(_Account())
    response = _client(db).post(
        "/api/title-intelligence/generate", json=_payload()
    )

    assert response.status_code == 200
    assert response.json()["fallback_used"] is True
    assert response.json()["confidence"] == "FACTUAL_FALLBACK"
    assert db.commits == 0
    assert db.added == []


def test_generate_commits_only_a_newly_fetched_trend_snapshot(monkeypatch):
    """Catches a fetched trend snapshot being rolled back when the request closes."""
    db = _Db(_Account())
    monkeypatch.setattr(accounts_service, "load_access_token", lambda *_: "token")
    monkeypatch.setattr(
        MercadoLibreClient,
        "category_trends",
        lambda *_: ["cesto ropa sucia"],
    )

    response = _client(db).post(
        "/api/title-intelligence/generate", json=_payload()
    )

    assert response.status_code == 200
    assert db.commits == 1
    assert len(db.added) == 1
    assert isinstance(db.added[0], KeywordTrendSnapshot)


def test_generate_does_not_commit_a_fresh_trend_hit(monkeypatch):
    """Catches read-only cache hits acquiring a write transaction boundary."""
    now = utcnow()
    snapshot = KeywordTrendSnapshot(
        site_id="MLA",
        category_id="MLA412517",
        terms=["cesto ropa sucia"],
        fetched_at=now,
        expires_at=now + timedelta(hours=1),
    )
    db = _Db(_Account(), snapshot)
    monkeypatch.setattr(accounts_service, "load_access_token", lambda *_: "token")
    monkeypatch.setattr(
        MercadoLibreClient,
        "category_trends",
        lambda *_: (_ for _ in ()).throw(AssertionError("fresh cache must not fetch")),
    )

    response = _client(db).post(
        "/api/title-intelligence/generate", json=_payload()
    )

    assert response.status_code == 200
    assert db.commits == 0
    assert db.added == []


def test_generate_response_has_the_stable_recommendation_shape(monkeypatch):
    """Catches the HTTP adapter omitting domain recommendation signals."""
    monkeypatch.setattr(accounts_service, "load_access_token", lambda *_: "token")
    monkeypatch.setattr(
        MercadoLibreClient,
        "category_trends",
        lambda *_: ["cesto ropa sucia"],
    )

    response = _client(_Db(_Account())).post(
        "/api/title-intelligence/generate", json=_payload()
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "recommended_title",
        "alternatives",
        "confidence",
        "matched_trends",
        "fallback_used",
    }
    assert body["recommended_title"] == "CESTO PLEGABLE PARA ROPA 40L"
    assert body["alternatives"]
    assert all(isinstance(title, str) for title in body["alternatives"])
    assert body["confidence"] == "TREND_SUPPORTED"
    assert body["matched_trends"] == ["cesto ropa sucia"]
    assert body["fallback_used"] is False


def test_generate_has_no_publication_side_effect(monkeypatch):
    """Catches title generation being accidentally wired to publication."""
    publication = _PublicationSpy()
    monkeypatch.setattr(accounts_service, "load_access_token", lambda *_: "token")
    monkeypatch.setattr(MercadoLibreClient, "category_trends", lambda *_: [])
    monkeypatch.setattr(publication_router, "create_publication_job", publication.create_job)

    response = _client(_Db(_Account())).post(
        "/api/title-intelligence/generate", json=_payload()
    )

    assert response.status_code == 200
    assert publication.calls == 0


def test_generate_rejects_a_nonpositive_max_length():
    """Catches a caller-supplied invalid title limit reaching the generator."""
    response = _client(_Db(_Account())).post(
        "/api/title-intelligence/generate", json=_payload(max_length=0)
    )

    assert response.status_code == 422


def test_generate_preserves_the_established_missing_account_404():
    """Catches a missing or inactive account being mapped to a generic validation error."""
    response = _client(_Db()).post("/api/title-intelligence/generate", json=_payload())

    assert response.status_code == 404
    assert response.json()["detail"] == "Cuenta de Mercado Libre no encontrada."
