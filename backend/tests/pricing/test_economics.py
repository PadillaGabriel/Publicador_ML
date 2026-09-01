from decimal import Decimal

import pytest

from app.pricing.domain import (
    EconomicInputs,
    MarketplaceEconomics,
    PricingDomainError,
    evaluate_economics,
)


def _inputs(**overrides: Decimal | None) -> EconomicInputs:
    values = {
        "gross_price": Decimal(24200),
        "gross_cmv": Decimal(12100),
        "vat_rate": Decimal("0.21"),
        "iibb_rate": Decimal("0.03"),
        "ads_rate": Decimal("0.05"),
        "refund_rate": Decimal("0.01"),
        "additional_unit_cost": Decimal(0),
    }
    values.update(overrides)
    return EconomicInputs(**values)


def test_cmv_gross_is_converted_to_net_by_vat():
    """Catches treating gross sale price or CMV as an economic net amount."""
    result = evaluate_economics(_inputs(), MarketplaceEconomics.zero())

    assert result.net_price == Decimal("20000.00")
    assert result.net_cmv == Decimal("10000.00")


def test_logistics_remain_auditable_when_net_result_is_zero():
    """Catches collapsing offsetting logistics nodes before exposing the result."""
    marketplace = MarketplaceEconomics(
        percentage_fee=Decimal(0),
        meli_percentage_fee=Decimal(0),
        financing_add_on_fee=Decimal(0),
        fixed_fee=Decimal(0),
        shipping_cost=Decimal(3000),
        shipping_subsidy=Decimal(1000),
        buyer_shipping_amount=Decimal(2000),
    )

    result = evaluate_economics(_inputs(), marketplace)

    assert result.shipping_cost == Decimal("3000.00")
    assert result.shipping_subsidy == Decimal("1000.00")
    assert result.buyer_shipping_amount == Decimal("2000.00")
    assert result.net_logistic_cost == Decimal("0.00")


def test_iibb_uses_taxable_revenue_instead_of_contribution_margin():
    """Catches calculating IIBB from margin after costs instead of taxable revenue."""
    result = evaluate_economics(_inputs(), MarketplaceEconomics.zero())

    assert result.taxable_revenue == Decimal("20000.00")
    assert result.iibb == Decimal("600.00")


def test_economics_exposes_each_fee_and_contribution_component():
    """Catches omitting a marketplace fee or a configured economic deduction from MC."""
    marketplace = MarketplaceEconomics(
        percentage_fee=Decimal(16),
        meli_percentage_fee=Decimal(16),
        financing_add_on_fee=Decimal(2),
        fixed_fee=Decimal(1210),
        shipping_cost=Decimal(3000),
        shipping_subsidy=Decimal(1000),
        buyer_shipping_amount=Decimal(2000),
    )

    result = evaluate_economics(_inputs(), marketplace)

    assert result.ml_commission_net == Decimal("3200.00")
    assert result.financing_net == Decimal("400.00")
    assert result.ml_fixed_fee_net == Decimal("1000.00")
    assert result.ads_expected == Decimal("1000.00")
    assert result.refunds_expected == Decimal("200.00")
    assert result.contribution_margin == Decimal("3600.00")
    assert result.contribution_margin_pct == Decimal("18.00")


@pytest.mark.parametrize("meli_percentage_fee", [Decimal(15), Decimal(17)])
def test_economics_rejects_ambiguous_marketplace_percentage_fees(meli_percentage_fee: Decimal):
    """Catches silently choosing a fee when Mercado Libre fields disagree."""
    marketplace = MarketplaceEconomics(
        percentage_fee=Decimal(16),
        meli_percentage_fee=meli_percentage_fee,
        financing_add_on_fee=Decimal(2),
        fixed_fee=Decimal(0),
        shipping_cost=Decimal(0),
        shipping_subsidy=Decimal(0),
        buyer_shipping_amount=Decimal(0),
    )

    with pytest.raises(PricingDomainError, match="TARIFA_ML_INCONSISTENTE"):
        evaluate_economics(_inputs(), marketplace)


def test_missing_cmv_raises_an_explicit_domain_error():
    """Catches silently treating absent CMV as a known zero cost."""
    with pytest.raises(PricingDomainError, match="SIN_CMV"):
        evaluate_economics(_inputs(gross_cmv=None), MarketplaceEconomics.zero())
