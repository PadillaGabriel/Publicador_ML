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

    assert "RATTAN" not in result.recommended_title
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
