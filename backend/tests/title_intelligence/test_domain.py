import pytest

from app.title_intelligence import domain
from app.title_intelligence.domain import (
    ProductTitleContext,
    TitleConstraints,
    recommend_title,
)


def test_recommendation_never_adds_an_incompatible_trend_token():
    context = ProductTitleContext(
        category_id="MLA1",
        product_name="Cesto plástico plegable",
        attributes={"capacity": "40 L", "use": "ropa"},
    )

    result = recommend_title(context, ("cesto rattan",), TitleConstraints(max_length=60))

    candidates = (result.recommended_title, *result.alternatives)

    assert all("RATTAN" not in candidate for candidate in candidates)
    assert result.fallback_used is True


def test_recommendation_falls_back_to_factual_terms_with_a_maximum_length():
    context = ProductTitleContext(
        category_id="MLA1",
        product_name="Cesto plástico plegable",
        attributes={"capacity": "40 L", "use": "ropa"},
    )

    result = recommend_title(context, (), TitleConstraints(max_length=30))

    assert result.recommended_title
    assert len(result.recommended_title) <= 30


def test_recommendation_uses_supported_terms_from_a_compatible_trend_to_improve_title():
    context = ProductTitleContext(
        category_id="MLA1",
        product_name="Cesto plástico plegable",
        attributes={"capacity": "40 L", "use": "ropa"},
    )

    result = recommend_title(context, ("cesto ropa sucia",), TitleConstraints(max_length=60))

    assert result.recommended_title == "CESTO PLEGABLE PARA ROPA 40L"
    assert result.matched_trends == ("cesto ropa sucia",)
    assert result.fallback_used is False


def test_recommendation_removes_duplicate_tokens_case_and_plural_insensitively():
    context = ProductTitleContext(
        category_id="MLA1",
        product_name="Cesto cestos plegable",
        attributes={"capacity": "40 L", "use": "ropa ropa"},
    )

    result = recommend_title(context, (), TitleConstraints(max_length=60))

    assert result.recommended_title == "CESTO PLEGABLE 40 L ROPA"


def test_recommendation_is_deterministic_for_the_same_input():
    context = ProductTitleContext(
        category_id="MLA1",
        product_name="Cesto plástico plegable",
        attributes={"capacity": "40 L", "use": "ropa"},
    )
    constraints = TitleConstraints(max_length=60)

    first = recommend_title(context, ("cesto ropa sucia",), constraints)
    second = recommend_title(context, ("cesto ropa sucia",), constraints)

    assert first == second


def test_constraints_reject_a_zero_maximum_length():
    with pytest.raises(ValueError, match="max_length"):
        TitleConstraints(max_length=0)


def test_recommendation_generates_deduplicated_candidates_within_the_explicit_limit():
    context = ProductTitleContext(
        category_id="MLA1",
        product_name="Cesto plástico plegable",
        attributes={"capacity": "40 L", "use": "ropa"},
    )

    result = recommend_title(context, ("cesto ropa sucia",), TitleConstraints(max_length=60))
    candidates = (result.recommended_title, *result.alternatives)

    assert 3 <= len(candidates) <= 10
    assert len(candidates) == len(set(candidates))
    assert all(len(candidate) <= 60 for candidate in candidates)


def test_recommendation_rejects_oversized_candidates_without_cutting_a_word():
    context = ProductTitleContext(
        category_id="MLA1",
        product_name="Cesto plástico plegable",
        attributes={"capacity": "40 L", "use": "ropa"},
    )

    result = recommend_title(context, (), TitleConstraints(max_length=7))

    assert result.recommended_title == "CESTO"
    assert all(len(candidate) <= 7 for candidate in (result.recommended_title, *result.alternatives))


def test_recommendation_rejects_the_whole_oversized_trend_title_without_a_dangling_connector():
    context = ProductTitleContext(
        category_id="MLA1",
        product_name="Cesto plástico plegable",
        attributes={"capacity": "40 L", "use": "ropa"},
    )

    result = recommend_title(context, ("cesto ropa sucia",), TitleConstraints(max_length=10))

    candidates = (result.recommended_title, *result.alternatives)
    assert all(len(candidate) <= 10 for candidate in candidates)
    assert all("PARA" not in candidate for candidate in candidates)
    assert result.fallback_used is True


def test_recommendation_raises_when_no_complete_factual_token_fits_the_limit():
    context = ProductTitleContext(
        category_id="MLA1",
        product_name="Cesto",
        attributes={},
    )

    with pytest.raises(ValueError, match="no factual token fits"):
        recommend_title(context, (), TitleConstraints(max_length=4))


def test_recommendation_generates_complete_factual_candidates_under_a_short_limit():
    context = ProductTitleContext(
        category_id="MLA1",
        product_name="Caja azul",
        attributes={"size": "M"},
    )

    result = recommend_title(context, (), TitleConstraints(max_length=11))
    candidates = (result.recommended_title, *result.alternatives)

    assert 3 <= len(candidates) <= 10
    assert all(len(candidate) <= 11 for candidate in candidates)
    assert all(set(candidate.split()) == {"CAJA", "AZUL", "M"} for candidate in candidates)
    assert result.fallback_used is True


def test_recommendation_uses_generic_attributes_without_an_unsupported_connector():
    context = ProductTitleContext(
        category_id="MLA1",
        product_name="Caja organizadora",
        attributes={"color": "azul", "material": "tela"},
    )

    result = recommend_title(context, ("caja organizadora",), TitleConstraints(max_length=60))
    candidates = (result.recommended_title, *result.alternatives)

    assert 3 <= len(candidates) <= 10
    assert all("PARA" not in candidate for candidate in candidates)
    assert all(set(candidate.split()) <= {"CAJA", "ORGANIZADORA", "AZUL", "TELA"} for candidate in candidates)
    assert any("AZUL" in candidate for candidate in candidates)
    assert any("TELA" in candidate for candidate in candidates)
    assert result.fallback_used is True


def test_recommendation_bounds_candidate_work_with_fifty_factual_attributes(monkeypatch):
    """Catches a return to combinatorial subset enumeration for large factual inputs."""
    real_complete_title = domain._complete_title
    complete_title_calls = 0

    def bounded_complete_title(terms, max_length):
        nonlocal complete_title_calls
        complete_title_calls += 1
        if complete_title_calls > 600:
            raise AssertionError("candidate generation exceeded its bounded work budget")
        return real_complete_title(terms, max_length)

    monkeypatch.setattr(domain, "_complete_title", bounded_complete_title)
    attributes = {
        f"attribute_{index:02d}": f"value{index:02d}"
        for index in range(50)
    }
    context = ProductTitleContext(
        category_id="MLA1",
        product_name="Caja",
        attributes=attributes,
    )

    result = recommend_title(context, (), TitleConstraints(max_length=15))
    candidates = (result.recommended_title, *result.alternatives)
    factual_words = {"CAJA", *(value.upper() for value in attributes.values())}

    assert complete_title_calls <= 600
    assert 1 <= len(candidates) <= 10
    assert all(len(candidate) <= 15 for candidate in candidates)
    assert all(set(candidate.split()) <= factual_words for candidate in candidates)
