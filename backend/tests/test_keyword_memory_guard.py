from types import SimpleNamespace

import pytest

from app.keywords import prerank
from app.keywords.relevance import rank_trends, select_assessed_keywords


def test_semantic_prerank_does_not_instantiate_local_ranker_when_disabled(monkeypatch):
    class ForbiddenLocalRanker:
        def __init__(self, *_args, **_kwargs):
            pytest.fail("LocalSemanticRanker must not load when local embeddings are disabled")

    monkeypatch.setattr(prerank, "LocalSemanticRanker", ForbiddenLocalRanker)
    settings = SimpleNamespace(
        keyword_local_embeddings_enabled=False,
        keyword_embedding_model="sentence-transformers/test-model",
    )

    similarities, status, model = prerank.semantic_prerank(
        settings=settings,
        product_version_id="version-1",
        product_text="mate imperial de calabaza",
        trends=["mate imperial", "mate calabaza"],
    )

    assert similarities == [None, None]
    assert status == "DISABLED_MEMORY_GUARD"
    assert model is None


def test_semantic_prerank_uses_none_when_enabled_model_is_unavailable(monkeypatch):
    class FailingLocalRanker:
        def __init__(self, *_args, **_kwargs):
            pass

        def similarities(self, *_args, **_kwargs):
            raise prerank.SemanticModelError("model unavailable")

    monkeypatch.setattr(prerank, "LocalSemanticRanker", FailingLocalRanker)
    settings = SimpleNamespace(
        keyword_local_embeddings_enabled=True,
        keyword_embedding_model="sentence-transformers/test-model",
    )

    similarities, status, model = prerank.semantic_prerank(
        settings=settings,
        product_version_id="version-1",
        product_text="mate imperial de calabaza",
        trends=["mate imperial"],
    )

    assert similarities == [None]
    assert status == "UNAVAILABLE"
    assert model == "sentence-transformers/test-model"


def test_rank_trends_preserves_missing_semantic_similarity():
    ranked = rank_trends(
        ["mate imperial"],
        [None],
        {"mate", "imperial"},
        min_semantic_similarity=0.35,
    )

    assert ranked[0].semantic_similarity is None
    assert ranked[0].eligible is True


def test_keyword_score_renormalizes_when_local_embedding_signal_is_missing():
    ranked = rank_trends(
        ["mate premium"],
        [None],
        {"mate"},
        min_semantic_similarity=0.35,
    )

    _, _, scored = select_assessed_keywords(
        ranked,
        {"mate premium": "SYNONYM"},
        limit=1,
    )

    expected = ((0.45 * 0.95) + (0.30 * 1.0) + (0.05 * 0.5)) / 0.80
    assert scored[0]["semantic_similarity"] is None
    assert scored[0]["final_score"] == pytest.approx(expected, abs=1e-6)


def test_keyword_score_is_unchanged_when_embedding_signal_exists():
    ranked = rank_trends(
        ["mate premium"],
        [0.8],
        {"mate"},
        min_semantic_similarity=0.35,
    )

    _, _, scored = select_assessed_keywords(
        ranked,
        {"mate premium": "SYNONYM"},
        limit=1,
    )

    expected = (0.45 * 0.95) + (0.30 * 1.0) + (0.20 * 0.8) + (0.05 * 0.5)
    assert scored[0]["semantic_similarity"] == 0.8
    assert scored[0]["final_score"] == pytest.approx(expected, abs=1e-6)
