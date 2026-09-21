from decimal import Decimal

import pytest

from app.pricing.application.optimizer import PriceOptimizer
from app.pricing.domain import EconomicInputs, MarketplaceEconomics, evaluate_economics
from app.publication.quantity_pricing import (
    QuantityPricingSyncError,
    b2b_percentage_payload,
    normalize_b2b_quantity_prices,
)


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


def test_b2b_percentage_payload_reuses_ids_and_preserves_margin_safe_amounts():
    current = {
        "price_per_quantity": [
            {
                "id": "20",
                "type": "discount_percentage",
                "percentage": 5,
                "conditions": {
                    "context_restrictions": ["channel_marketplace", "user_type_business"],
                    "min_purchase_unit": 2,
                    "eligible": True,
                },
            }
        ]
    }
    recommendations = {
        "recommendations": [
            {
                "quantity": 2,
                "amount": 960,
                "is_incoherent_quantity": False,
                "discount": {"percentage": 4},
            },
            {
                "quantity": 3,
                "amount": 910,
                "is_incoherent_quantity": False,
                "discount": {"percentage": 9},
            },
        ]
    }
    payload = b2b_percentage_payload(
        current,
        [
            {"min_purchase_unit": 2, "amount": Decimal("950")},
            {"min_purchase_unit": 3, "amount": Decimal("900")},
        ],
        recommendations,
        standard_amount=Decimal("1000"),
    )

    assert payload["price_per_quantity"][0]["id"] == "20"
    assert payload["price_per_quantity"][0]["percentage"] == 5.0
    assert payload["price_per_quantity"][1]["percentage"] == 10.0
    assert payload["price_per_quantity"][1]["conditions"]["eligible"] is True


def test_b2b_percentage_payload_refuses_marketplace_discount_that_would_erode_margin():
    with pytest.raises(QuantityPricingSyncError, match="proteger el margen"):
        b2b_percentage_payload(
            {},
            [{"min_purchase_unit": 2, "amount": Decimal("950")}],
            {
                "recommendations": [
                    {
                        "quantity": 2,
                        "amount": 900,
                        "is_incoherent_quantity": False,
                        "discount": {"percentage": 10},
                    }
                ]
            },
            standard_amount=Decimal("1000"),
        )


def test_pricing_separates_base_commission_financing_and_fixed_fee():
    result = evaluate_economics(
        EconomicInputs(
            gross_price=Decimal("1210"),
            gross_cmv=Decimal("0"),
            vat_rate=Decimal("0.21"),
            iibb_rate=Decimal("0"),
            ads_rate=Decimal("0"),
            refund_rate=Decimal("0"),
            additional_unit_cost=Decimal("0"),
        ),
        MarketplaceEconomics(
            percentage_fee=Decimal("36"),
            meli_percentage_fee=Decimal("13"),
            financing_add_on_fee=Decimal("23"),
            fixed_fee=Decimal("242"),
            shipping_cost=Decimal("0"),
            shipping_subsidy=Decimal("0"),
            buyer_shipping_amount=Decimal("0"),
        ),
    )

    assert result.net_price == Decimal("1000.00")
    assert result.ml_commission_net == Decimal("130.00")
    assert result.financing_net == Decimal("230.00")
    assert result.fixed_fee == Decimal("242.00")
    assert result.ml_fixed_fee_net == Decimal("200.00")
    assert result.contribution_margin == Decimal("440.00")
