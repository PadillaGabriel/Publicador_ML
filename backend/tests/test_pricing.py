from decimal import Decimal

import pytest

from app.pricing.calculator import CostComponentValue, PricingInputs, calculate_pricing
from app.publication.quantity_pricing import b2b_quantity_price_payload, normalize_b2b_quantity_prices


def test_pricing_engine_solves_break_even_and_target_margin():
    result = calculate_pricing(PricingInputs(
        product_cost=Decimal("5000"),
        additional_unit_costs=(("Packaging", Decimal("300")),),
        components=(
            CostComponentValue("Cargo fijo", "FIXED_PER_UNIT", Decimal("200")),
            CostComponentValue("Comisión", "PERCENTAGE_OF_PRICE", Decimal("15")),
            CostComponentValue("Publicidad", "PERCENTAGE_OF_PRICE", Decimal("5")),
        ),
        monthly_units_projection=None,
        units_per_order=Decimal("1"),
        target_margin_pct=Decimal("20"),
        minimum_margin_pct=Decimal("10"),
        rounding_step=Decimal("1"),
        sale_price=Decimal("10000"),
    ))
    assert result["variable_base_cost"] == Decimal("5500.00")
    assert result["price_cost_rate_pct"] == Decimal("20.0000")
    assert result["break_even_price"] == Decimal("6875.00")
    assert result["target_price"] == Decimal("9166.67")
    assert result["recommended_price"] == Decimal("9167.00")
    assert result["at_sale_price"]["contribution_margin_pct"] == Decimal("25.00")
    assert result["at_sale_price"]["health"] == "HEALTHY"


def test_monthly_fixed_cost_requires_volume_projection_to_allocate():
    result = calculate_pricing(PricingInputs(
        product_cost=Decimal("1000"),
        additional_unit_costs=(),
        components=(CostComponentValue("Alquiler", "FIXED_MONTHLY", Decimal("100000")),),
        monthly_units_projection=None,
        units_per_order=Decimal("1"),
        target_margin_pct=Decimal("20"),
        minimum_margin_pct=Decimal("10"),
        rounding_step=Decimal("1"),
    ))
    assert result["allocated_fixed_cost"] == Decimal("0.00")
    assert result["warnings"]


def test_b2b_quantity_prices_are_sorted_and_must_decrease():
    tiers = normalize_b2b_quantity_prices(
        {"quantity_prices": [
            {"min_purchase_unit": 10, "amount": 800},
            {"min_purchase_unit": 3, "amount": 900},
        ]},
        base_price=1000,
    )
    assert [row["min_purchase_unit"] for row in tiers] == [3, 10]
    with pytest.raises(ValueError):
        normalize_b2b_quantity_prices(
            {"quantity_prices": [
                {"min_purchase_unit": 3, "amount": 800},
                {"min_purchase_unit": 10, "amount": 850},
            ]},
            base_price=1000,
        )


def test_b2b_payload_preserves_non_b2b_prices_and_replaces_old_b2b_nodes():
    current = {
        "prices": [
            {"id": "1", "conditions": {"context_restrictions": []}},
            {"id": "2", "conditions": {"context_restrictions": ["channel_marketplace"]}},
            {"id": "3", "conditions": {"context_restrictions": ["channel_marketplace", "user_type_business"], "min_purchase_unit": 5}},
        ]
    }
    payload = b2b_quantity_price_payload(
        current,
        [{"min_purchase_unit": 5, "amount": Decimal("850")}],
        "ARS",
    )
    assert payload["prices"][0:2] == [{"id": "1"}, {"id": "2"}]
    assert all(price.get("id") != "3" for price in payload["prices"])
    assert payload["prices"][-1]["conditions"]["context_restrictions"] == [
        "channel_marketplace", "user_type_business"
    ]
