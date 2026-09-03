from datetime import timedelta
from types import SimpleNamespace

import pytest

from app.core.time import utcnow
from app.integrations.mercadolibre.client import MercadoLibreError
from app.keywords.relevance import (
    build_product_evidence,
    rank_trends,
    select_assessed_keywords,
)
from app.keywords.service import (
    KeywordResearchError,
    build_ml_keyword_snapshot,
    get_category_trends,
)
from app.persistence import KeywordTrendSnapshot


class _TrendDb:
    def __init__(self, snapshot=None):
        self.added = []
        self.snapshot = snapshot

    def scalar(self, _query):
        return self.snapshot

    def add(self, value):
        self.added.append(value)

    def flush(self):
        pass


def test_category_trends_exposes_a_stable_lookup_contract(monkeypatch):
    monkeypatch.setattr("app.keywords.service.MercadoLibreClient.category_trends", lambda *_: ["cesto ropa"])

    lookup = get_category_trends(_TrendDb(), site_id="MLA", category_id="MLA1", access_token="token")

    assert lookup.terms == ("cesto ropa",)
    assert lookup.cache_status == "MISS_FETCHED"
    assert lookup.snapshot is not None


def test_category_trends_returns_stale_snapshot_when_provider_fails(monkeypatch):
    snapshot = KeywordTrendSnapshot(
        site_id="MLA",
        category_id="MLA1",
        terms=["cesto ropa", "organizador"],
        fetched_at=utcnow() - timedelta(days=2),
        expires_at=utcnow() - timedelta(days=1),
    )
    monkeypatch.setattr(
        "app.keywords.service.MercadoLibreClient.category_trends",
        lambda *_: (_ for _ in ()).throw(MercadoLibreError("provider unavailable")),
    )

    lookup = get_category_trends(
        _TrendDb(snapshot), site_id="MLA", category_id="MLA1", access_token="token"
    )

    assert lookup.terms == ("cesto ropa", "organizador")
    assert lookup.snapshot is snapshot
    assert lookup.cache_status == "STALE_FALLBACK"


def test_category_trends_returns_unavailable_without_snapshot_when_provider_fails(monkeypatch):
    monkeypatch.setattr(
        "app.keywords.service.MercadoLibreClient.category_trends",
        lambda *_: (_ for _ in ()).throw(MercadoLibreError("provider unavailable")),
    )

    lookup = get_category_trends(
        _TrendDb(), site_id="MLA", category_id="MLA1", access_token="token"
    )

    assert lookup.terms == ()
    assert lookup.snapshot is None
    assert lookup.cache_status == "UNAVAILABLE"


@pytest.mark.parametrize(
    ("status_code", "expected_retryable"),
    [(400, False), (503, True)],
)
def test_keyword_snapshot_preserves_trend_error_retryability(
    monkeypatch,
    status_code,
    expected_retryable,
):
    """Catches unavailable trend lookups being flattened to always retryable."""
    provider_error = MercadoLibreError(
        f"Mercado Libre HTTP {status_code}",
        status_code=status_code,
    )
    monkeypatch.setattr(
        "app.keywords.service.MercadoLibreClient.category_trends",
        lambda *_: (_ for _ in ()).throw(provider_error),
    )
    version = SimpleNamespace(id="version-1", category_id="MLA1")

    with pytest.raises(KeywordResearchError) as exc_info:
        build_ml_keyword_snapshot(
            _TrendDb(),
            version=version,
            site_id="MLA",
            category_name="Cestos",
            access_token="token",
        )

    assert exc_info.value.code == "ML_KEYWORD_TRENDS_UNAVAILABLE"
    assert exc_info.value.retryable is expected_retryable


def _product_evidence():
    return build_product_evidence(
        product_name="Mate Imperial Calabaza Cuero Vacuno Virola Acero",
        category_name="Mates",
        description="Mate artesanal con virola de acero y cuerpo de calabaza.",
        attributes={"MATERIAL": {"value_name": "Calabaza"}, "VIROLA": "Acero"},
        discovery_context={"brand": "", "model": "", "characteristics": "Cuero vacuno"},
    )


def test_factual_gate_rejects_related_but_false_trend():
    _, factual_tokens = _product_evidence()
    ranked = rank_trends(
        ["mate imperial", "mate imperial algarrobo", "mate calabaza", "mate stanley"],
        [0.95, 0.94, 0.90, 0.70],
        factual_tokens,
        min_semantic_similarity=0.35,
    )
    by_term = {item.term: item for item in ranked}

    assert by_term["mate imperial"].eligible is True
    assert by_term["mate calabaza"].eligible is True
    assert by_term["mate imperial algarrobo"].eligible is False
    assert "algarrobo" in by_term["mate imperial algarrobo"].unsupported_tokens
    assert by_term["mate stanley"].eligible is False


def test_semantic_threshold_is_only_a_deterministic_exact_match_signal():
    _, factual_tokens = _product_evidence()
    ranked = rank_trends(
        ["mate acero"],
        [0.20],
        factual_tokens,
        min_semantic_similarity=0.35,
    )
    assert ranked[0].eligible is False
    assert ranked[0].final_score > 0


def test_semantic_assessment_can_recover_popular_low_overlap_synonym():
    _, factual_tokens = _product_evidence()
    ranked = rank_trends(
        ["set matero", "mate imperial", "mate termico"],
        [0.08, 0.92, 0.70],
        factual_tokens,
        min_semantic_similarity=0.35,
    )

    phrases, _, scored = select_assessed_keywords(
        ranked,
        {
            "set matero": "SYNONYM",
            "mate imperial": "DIRECT_MATCH",
            "mate termico": "UNSUPPORTED",
        },
        limit=3,
    )

    assert "set matero" in phrases
    assert "mate imperial" in phrases
    assert "mate termico" not in phrases
    synonym = next(item for item in scored if item["term"] == "set matero")
    assert synonym["classification"] == "SYNONYM"
    assert synonym["popularity_rank"] == 1
    assert synonym["final_score"] > 0


def test_popularity_contributes_without_overriding_unsupported_classification():
    _, factual_tokens = _product_evidence()
    ranked = rank_trends(
        ["mate termico", "mate imperial"],
        [0.99, 0.70],
        factual_tokens,
        min_semantic_similarity=0.35,
    )

    phrases, _, scored = select_assessed_keywords(
        ranked,
        {
            "mate termico": "UNSUPPORTED",
            "mate imperial": "DIRECT_MATCH",
        },
        limit=5,
    )

    assert phrases == ["mate imperial"]
    assert all(item["term"] != "mate termico" for item in scored)


def test_product_evidence_includes_description_as_factual_data():
    product_text, factual_tokens = build_product_evidence(
        product_name="Organizador de cocina",
        category_name="Organizadores",
        description="Estructura metálica con dos niveles y bandeja removible",
        attributes={},
        discovery_context={},
    )

    assert "Descripción: Estructura metálica con dos niveles y bandeja removible" in product_text
    assert "metalica" in factual_tokens
    assert "nivel" in factual_tokens
    assert "bandeja" in factual_tokens
    assert "removible" in factual_tokens
