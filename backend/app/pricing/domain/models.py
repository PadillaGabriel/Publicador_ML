from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class EconomicInputs:
    gross_price: Decimal | None
    gross_cmv: Decimal | None
    vat_rate: Decimal | None
    iibb_rate: Decimal | None
    ads_rate: Decimal | None
    refund_rate: Decimal | None
    additional_unit_cost: Decimal | None


@dataclass(frozen=True, slots=True)
class MarketplaceEconomics:
    percentage_fee: Decimal | None
    meli_percentage_fee: Decimal | None
    financing_add_on_fee: Decimal | None
    fixed_fee: Decimal | None
    shipping_cost: Decimal | None
    shipping_subsidy: Decimal | None
    buyer_shipping_amount: Decimal | None

    @classmethod
    def zero(cls) -> "MarketplaceEconomics":
        return cls(
            percentage_fee=Decimal(0),
            meli_percentage_fee=Decimal(0),
            financing_add_on_fee=Decimal(0),
            fixed_fee=Decimal(0),
            shipping_cost=Decimal(0),
            shipping_subsidy=Decimal(0),
            buyer_shipping_amount=Decimal(0),
        )


@dataclass(frozen=True, slots=True)
class EconomicResult:
    gross_price: Decimal
    net_price: Decimal
    vat_debit: Decimal
    gross_cmv: Decimal
    net_cmv: Decimal
    cmv_vat_credit: Decimal
    taxable_revenue: Decimal
    percentage_fee: Decimal
    meli_percentage_fee: Decimal
    financing_add_on_fee: Decimal
    ml_commission_net: Decimal
    financing_net: Decimal
    fixed_fee: Decimal
    ml_fixed_fee_net: Decimal
    shipping_cost: Decimal
    shipping_subsidy: Decimal
    buyer_shipping_amount: Decimal
    net_logistic_cost: Decimal
    iibb: Decimal
    ads_expected: Decimal
    refunds_expected: Decimal
    additional_unit_cost_net: Decimal
    contribution_margin: Decimal
    contribution_margin_pct: Decimal
