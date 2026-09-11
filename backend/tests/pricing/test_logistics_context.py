from decimal import Decimal
from uuid import uuid4

import pytest

from app.pricing.application.calculator import PricingCalculatorService
from app.pricing.domain.errors import PricingDomainError
from app.pricing.schemas import PackageInput


def test_simulation_context_preserves_explicit_shipping_policy_and_physical_weight() -> None:
    """Catches losing free-shipping intent or treating physical kg as already billable grams."""
    context = PricingCalculatorService._simulation_context(
        account_id=uuid4(),
        category_id="MLA412517",
        listing_type_id="gold_special",
        currency_id="ARS",
        package=PackageInput(
            dimensions="10x20x30",
            weight=Decimal("0.45"),
            logistic_type="cross_docking",
            shipping_mode="me2",
            free_shipping=True,
        ),
    )

    assert context.dimensions == "10x20x30"
    assert context.package_weight_grams == Decimal(450)
    assert context.free_shipping is True


def test_new_product_logistics_requires_an_explicit_free_shipping_policy() -> None:
    """Catches silently assuming who pays freight for a prospective listing."""
    with pytest.raises(PricingDomainError) as exc:
        PricingCalculatorService._simulation_context(
            account_id=uuid4(),
            category_id="MLA412517",
            listing_type_id="gold_special",
            currency_id="ARS",
            package=PackageInput(
                dimensions="10x20x30",
                weight=Decimal("0.45"),
                logistic_type="cross_docking",
                shipping_mode="me2",
            ),
        )

    assert exc.value.code == "SIN_CONTEXTO_LOGISTICO"
