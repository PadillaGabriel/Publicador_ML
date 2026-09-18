from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

from app.pricing.application.calculator import PricingCalculatorService
from app.pricing.domain.models import MarketplaceEconomics
from app.pricing.infrastructure.mercadolibre import MarketplaceSimulationContext
from app.pricing.schemas import NewProductPricingRequest, PackageInput, QuantityTierInput


class ConstantMarketplaceProvider:
    def simulate(
        self, context: MarketplaceSimulationContext, gross_price: Decimal
    ) -> MarketplaceEconomics:
        del context, gross_price
        return MarketplaceEconomics(
            percentage_fee=Decimal("0"),
            meli_percentage_fee=Decimal("0"),
            financing_add_on_fee=Decimal("0"),
            fixed_fee=Decimal("0"),
            shipping_cost=Decimal("0"),
            shipping_subsidy=Decimal("0"),
            buyer_shipping_amount=Decimal("0"),
        )


def profile(*, target: str = "35", minimum: str = "20"):
    return SimpleNamespace(
        target_margin_pct=Decimal(target),
        minimum_margin_pct=Decimal(minimum),
        rounding_step=Decimal("1"),
        monthly_units_projection=None,
        vat_rate_pct=Decimal("0"),
        iibb_rate_pct=Decimal("0"),
        ads_rate_pct=Decimal("0"),
        refund_rate_pct=Decimal("0"),
        components=[],
    )


def request() -> NewProductPricingRequest:
    return NewProductPricingRequest(
        account_id=UUID(int=1),
        category_id="MLA1",
        listing_type_id="gold_special",
        gross_cmv=Decimal("500"),
        sale_price=Decimal("1500"),
        package=PackageInput(
            dimensions="10x10x10",
            weight=Decimal("1"),
            logistic_type="drop_off",
            shipping_mode="me2",
            free_shipping=False,
        ),
    )


def test_quantity_tiers_step_down_from_target_margin_to_minimum_floor():
    service = PricingCalculatorService(
        profile=profile(target="35", minimum="20"),
        provider=ConstantMarketplaceProvider(),
    )

    result = service.calculate_quantity_tiers(
        request(),
        [
            QuantityTierInput(min_purchase_unit=2),
            QuantityTierInput(min_purchase_unit=3),
            QuantityTierInput(min_purchase_unit=4),
        ],
    )

    assert [tier.target_margin_pct for tier in result.tiers] == [
        Decimal("30"),
        Decimal("25"),
        Decimal("20"),
    ]
    assert result.tiers[0].amount > result.tiers[1].amount > result.tiers[2].amount
    assert all(tier.status == "OPTIMO" for tier in result.tiers)
    assert all(tier.analyzed.contribution_margin_pct >= tier.target_margin_pct for tier in result.tiers)


def test_quantity_tiers_never_step_below_minimum_margin():
    service = PricingCalculatorService(
        profile=profile(target="25", minimum="20"),
        provider=ConstantMarketplaceProvider(),
    )

    result = service.calculate_quantity_tiers(
        request(),
        [
            QuantityTierInput(min_purchase_unit=2),
            QuantityTierInput(min_purchase_unit=3),
            QuantityTierInput(min_purchase_unit=4),
        ],
    )

    assert [tier.target_margin_pct for tier in result.tiers] == [
        Decimal("20"),
        Decimal("20"),
        Decimal("20"),
    ]
    assert result.tiers[0].status == "OPTIMO"
    assert result.tiers[1].status == "SIN_VENTAJA"
    assert result.tiers[2].status == "SIN_VENTAJA"
