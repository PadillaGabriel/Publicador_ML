from decimal import Decimal
from uuid import uuid4

from app.pricing.application.calculator import PricingCalculatorService
from app.pricing.domain.models import MarketplaceEconomics
from app.pricing.infrastructure.mercadolibre import ExistingListingContext
from app.pricing.schemas import ExistingListingPricingRequest, PackageInput


class _Profile:
    target_margin_pct = Decimal("20")
    minimum_margin_pct = Decimal("10")
    vat_rate_pct = Decimal("21")
    iibb_rate_pct = Decimal("3.5")
    ads_rate_pct = Decimal("0")
    refund_rate_pct = Decimal("0")
    monthly_units_projection = None
    rounding_step = Decimal("1")
    components = []


class _Provider:
    def resolve_existing_listing(self, *, account_id, item_id):
        return ExistingListingContext(
            category_id="MLA1",
            listing_type_id="gold_special",
            currency_id="ARS",
            current_price=Decimal("20000"),
            condition="new",
            package=PackageInput(
                dimensions="30x20x10",
                weight=Decimal("0.5"),
                logistic_type="drop_off",
                shipping_mode="me2",
                free_shipping=False,
            ),
        )

    def simulate(self, context, gross_price):
        return MarketplaceEconomics.zero()


def test_existing_listing_can_analyze_an_explicit_sale_price():
    service = PricingCalculatorService(profile=_Profile(), provider=_Provider())

    result = service.calculate_existing_listing(
        ExistingListingPricingRequest(
            account_id=uuid4(),
            item_id="MLA123",
            gross_cmv=Decimal("10000"),
            sale_price=Decimal("25000"),
        )
    )

    assert result.analyzed.gross_price == Decimal("25000")
    assert result.audit.analyzed_price == Decimal("25000")
