from decimal import Decimal

import pytest

from app.pricing.quantity_pricing import quote_optimal_quantity_price


def test_quote_uses_the_minimum_sustainable_price_as_the_wholesale_amount():
    quote = quote_optimal_quantity_price(
        retail_price=Decimal("25000"),
        minimum_sustainable_price=Decimal("22000"),
    )

    assert quote.amount == Decimal("22000")
    assert quote.status == "OPTIMO"
    assert quote.discount_pct == Decimal("12.00")


def test_quote_reports_no_advantage_when_floor_is_not_below_retail():
    quote = quote_optimal_quantity_price(
        retail_price=Decimal("22000"),
        minimum_sustainable_price=Decimal("22000"),
    )

    assert quote.amount == Decimal("22000")
    assert quote.status == "SIN_VENTAJA"
    assert quote.discount_pct == Decimal("0")


def test_quote_rejects_non_positive_prices():
    with pytest.raises(ValueError):
        quote_optimal_quantity_price(
            retail_price=Decimal("0"),
            minimum_sustainable_price=Decimal("22000"),
        )
