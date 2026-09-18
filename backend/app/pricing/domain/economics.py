from decimal import ROUND_HALF_UP, Decimal

from .errors import PricingDomainError
from .models import EconomicInputs, EconomicResult, MarketplaceEconomics

MONEY = Decimal("0.01")
HUNDRED = Decimal(100)


def _money(value: Decimal) -> Decimal:
    return value.quantize(MONEY, rounding=ROUND_HALF_UP)


def _rate_from_marketplace_percentage(value: Decimal) -> Decimal:
    return value / HUNDRED


def _required_decimal(value: Decimal | None, *, code: str, name: str) -> Decimal:
    if value is None:
        raise PricingDomainError(code, f"Missing {name}.")
    if not isinstance(value, Decimal):
        raise PricingDomainError("SIN_PARAMETROS_ECONOMICOS", f"{name} must be a Decimal.")
    return value


def evaluate_economics(
    inputs: EconomicInputs,
    marketplace: MarketplaceEconomics,
) -> EconomicResult:
    """Evaluate one candidate price using only explicit, auditable economic inputs."""
    gross_price = _required_decimal(
        inputs.gross_price, code="SIN_PARAMETROS_ECONOMICOS", name="gross price"
    )
    gross_cmv = _required_decimal(inputs.gross_cmv, code="SIN_CMV", name="gross CMV")
    vat_rate = _required_decimal(
        inputs.vat_rate, code="SIN_PARAMETROS_ECONOMICOS", name="VAT rate"
    )
    iibb_rate = _required_decimal(
        inputs.iibb_rate, code="SIN_PARAMETROS_ECONOMICOS", name="IIBB rate"
    )
    ads_rate = _required_decimal(
        inputs.ads_rate, code="SIN_PARAMETROS_ECONOMICOS", name="Ads rate"
    )
    refund_rate = _required_decimal(
        inputs.refund_rate, code="SIN_PARAMETROS_ECONOMICOS", name="refund rate"
    )
    additional_unit_cost = _required_decimal(
        inputs.additional_unit_cost,
        code="SIN_PARAMETROS_ECONOMICOS",
        name="additional unit cost",
    )
    percentage_fee = _required_decimal(
        marketplace.percentage_fee, code="SIN_TARIFA_ML", name="marketplace percentage fee"
    )
    meli_percentage_fee = _required_decimal(
        marketplace.meli_percentage_fee,
        code="SIN_TARIFA_ML",
        name="Mercado Libre percentage fee",
    )
    financing_add_on_fee = _required_decimal(
        marketplace.financing_add_on_fee,
        code="SIN_TARIFA_ML",
        name="financing add-on fee",
    )
    if meli_percentage_fee < Decimal(0) or financing_add_on_fee < Decimal(0):
        raise PricingDomainError(
            "TARIFA_ML_INCONSISTENTE",
            "Mercado Libre percentage fee components cannot be negative.",
        )
    expected_percentage_fee = meli_percentage_fee + financing_add_on_fee
    if abs(percentage_fee - expected_percentage_fee) > Decimal("0.01"):
        raise PricingDomainError(
            "TARIFA_ML_INCONSISTENTE",
            "Mercado Libre total percentage fee does not match base commission plus financing.",
        )
    fixed_fee = _required_decimal(
        marketplace.fixed_fee, code="SIN_TARIFA_ML", name="marketplace fixed fee"
    )
    shipping_cost = _required_decimal(
        marketplace.shipping_cost, code="SIN_CONTEXTO_LOGISTICO", name="shipping cost"
    )
    shipping_subsidy = _required_decimal(
        marketplace.shipping_subsidy,
        code="SIN_CONTEXTO_LOGISTICO",
        name="shipping subsidy",
    )
    buyer_shipping_amount = _required_decimal(
        marketplace.buyer_shipping_amount,
        code="SIN_CONTEXTO_LOGISTICO",
        name="buyer shipping amount",
    )
    if vat_rate < Decimal(0) or vat_rate >= Decimal(1):
        raise PricingDomainError("SIN_PARAMETROS_ECONOMICOS", "VAT rate must be between 0 and 1.")

    vat_factor = Decimal(1) + vat_rate
    net_price = _money(gross_price / vat_factor)
    net_cmv = _money(gross_cmv / vat_factor)
    taxable_revenue = net_price
    # Mercado Libre exposes the base selling commission separately from financing.
    # ``percentage_fee`` is the provider's aggregate percentage and may already include
    # financing (for example, Premium listings). Use ``meli_percentage_fee`` for the
    # base commission so financing is never counted twice.
    ml_commission_net = _money(
        taxable_revenue * _rate_from_marketplace_percentage(meli_percentage_fee)
    )
    financing_net = _money(
        taxable_revenue * _rate_from_marketplace_percentage(financing_add_on_fee)
    )
    ml_fixed_fee_net = _money(fixed_fee / vat_factor)
    net_logistic_cost = _money(shipping_cost - shipping_subsidy - buyer_shipping_amount)
    iibb = _money(taxable_revenue * iibb_rate)
    ads_expected = _money(taxable_revenue * ads_rate)
    refunds_expected = _money(taxable_revenue * refund_rate)
    contribution_margin = _money(
        taxable_revenue
        - net_cmv
        - ml_commission_net
        - financing_net
        - ml_fixed_fee_net
        - net_logistic_cost
        - iibb
        - ads_expected
        - refunds_expected
        - additional_unit_cost
    )
    contribution_margin_pct = _money(
        contribution_margin / taxable_revenue * HUNDRED if taxable_revenue else Decimal(0)
    )

    return EconomicResult(
        gross_price=_money(gross_price),
        net_price=net_price,
        vat_debit=_money(gross_price - net_price),
        gross_cmv=_money(gross_cmv),
        net_cmv=net_cmv,
        cmv_vat_credit=_money(gross_cmv - net_cmv),
        taxable_revenue=taxable_revenue,
        percentage_fee=percentage_fee,
        meli_percentage_fee=meli_percentage_fee,
        financing_add_on_fee=financing_add_on_fee,
        ml_commission_net=ml_commission_net,
        financing_net=financing_net,
        fixed_fee=_money(fixed_fee),
        ml_fixed_fee_net=ml_fixed_fee_net,
        shipping_cost=_money(shipping_cost),
        shipping_subsidy=_money(shipping_subsidy),
        buyer_shipping_amount=_money(buyer_shipping_amount),
        net_logistic_cost=net_logistic_cost,
        iibb=iibb,
        ads_expected=ads_expected,
        refunds_expected=refunds_expected,
        additional_unit_cost_net=_money(additional_unit_cost),
        contribution_margin=contribution_margin,
        contribution_margin_pct=contribution_margin_pct,
    )
