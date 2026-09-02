from decimal import Decimal

import pytest

from app.pricing.application.optimizer import PriceOptimizer
from app.pricing.domain import EconomicInputs, MarketplaceEconomics, evaluate_economics
from app.publication.quantity_pricing import b2b_quantity_price_payload, normalize_b2b_quantity_prices


def test_pricing_engine_solves_break_even_and_target_margin():
    marketplace = MarketplaceEconomics(
        percentage_fee=Decimal("15"),
        meli_percentage_fee=Decimal("15"),
        financing_add_on_fee=Decimal(0),
        fixed_fee=Decimal(0),
        shipping_cost=Decimal(0),
        shipping_subsidy=Decimal(0),
        buyer_shipping_amount=Decimal(0),
    )

    def evaluate(price: Decimal):
        return evaluate_economics(
            EconomicInputs(
                gross_price=price,
                gross_cmv=Decimal("5000"),
                vat_rate=Decimal(0),
                iibb_rate=Decimal(0),
                ads_rate=Decimal("0.05"),
                refund_rate=Decimal(0),
                additional_unit_cost=Decimal("500"),
            ),
            marketplace,
        )

    optimizer = PriceOptimizer()
    analyzed = evaluate(Decimal("10000"))
    mc0 = optimizer.solve(evaluate, Decimal(0), Decimal("10000"))
    mc20 = optimizer.solve(evaluate, Decimal("20"), Decimal("10000"))

    assert analyzed.additional_unit_cost_net == Decimal("500.00")
    assert analyzed.contribution_margin_pct == Decimal("25.00")
    assert mc0.gross_price == Decimal("6875")
    assert mc20.gross_price == Decimal("9166")


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
