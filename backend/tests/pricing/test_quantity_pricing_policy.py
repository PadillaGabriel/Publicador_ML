from decimal import Decimal

import pytest

from app.pricing.quantity_pricing import quantity_discount_pct


def test_quantity_discount_percentage_uses_retail_as_baseline():
    assert quantity_discount_pct(
        retail_price=Decimal("25000"),
        amount=Decimal("22000"),
    ) == Decimal("12.00")


def test_quantity_discount_reports_zero_without_advantage():
    assert quantity_discount_pct(
        retail_price=Decimal("22000"),
        amount=Decimal("22000"),
    ) == Decimal("0")


def test_quantity_discount_rejects_non_positive_prices():
    with pytest.raises(ValueError):
        quantity_discount_pct(
            retail_price=Decimal("0"),
            amount=Decimal("22000"),
        )
