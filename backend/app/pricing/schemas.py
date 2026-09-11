from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

CostKind = Literal[
    "FIXED_MONTHLY",
    "FIXED_PER_UNIT",
    "FIXED_PER_ORDER",
    "PERCENTAGE_OF_PRICE",
    "PERCENTAGE_OF_COST",
]

CostBasis = Literal[
    "GROSS_SALE",
    "NET_SALE_EX_VAT",
    "TAXABLE_REVENUE",
    "PRODUCT_COST",
    "FIXED_PER_UNIT",
    "FIXED_PER_ORDER",
]


class CostComponentInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: CostKind
    value: Decimal = Field(ge=0)
    basis: CostBasis = "PRODUCT_COST"
    active: bool = True


class PricingProfileUpsert(BaseModel):
    name: str = Field(default="Mercado Libre", min_length=1, max_length=120)
    channel: str = Field(default="MERCADOLIBRE", min_length=1, max_length=40)
    currency_id: str = Field(default="ARS", min_length=3, max_length=10)
    target_margin_pct: Decimal = Field(default=Decimal("20"), ge=0, lt=100)
    minimum_margin_pct: Decimal = Field(default=Decimal("10"), ge=0, lt=100)
    vat_rate_pct: Decimal = Field(default=Decimal("21"), ge=0, lt=100)
    iibb_rate_pct: Decimal = Field(default=Decimal("0"), ge=0, lt=100)
    ads_rate_pct: Decimal = Field(default=Decimal("0"), ge=0, lt=100)
    refund_rate_pct: Decimal = Field(default=Decimal("0"), ge=0, lt=100)
    monthly_units_projection: int | None = Field(default=None, gt=0)
    rounding_step: Decimal = Field(default=Decimal("1"), gt=0)
    components: list[CostComponentInput] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def validate_margins(self):
        if self.minimum_margin_pct > self.target_margin_pct:
            raise ValueError("El margen mínimo no puede superar el margen objetivo.")
        return self


class AdditionalUnitCost(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    amount: Decimal = Field(ge=0)


class EconomicOverrides(BaseModel):
    vat_rate_pct: Decimal | None = Field(default=None, ge=0, lt=100)
    iibb_rate_pct: Decimal | None = Field(default=None, ge=0, lt=100)
    ads_rate_pct: Decimal | None = Field(default=None, ge=0, lt=100)
    refund_rate_pct: Decimal | None = Field(default=None, ge=0, lt=100)


class PackageInput(BaseModel):
    dimensions: str | None = Field(default=None, max_length=120)
    weight: Decimal | None = Field(default=None, gt=0)
    logistic_type: str | None = Field(default=None, max_length=80)
    shipping_mode: str | None = Field(default=None, max_length=80)
    free_shipping: bool | None = None


class PricingSimulationRequest(BaseModel):
    """Temporary publisher contract backed by the pricing application service."""

    account_id: UUID | None = None
    category_id: str | None = Field(default=None, max_length=40)
    listing_type_id: str | None = Field(default=None, max_length=40)
    product_cost: Decimal = Field(ge=0)
    additional_unit_costs: list[AdditionalUnitCost] = Field(default_factory=list, max_length=30)
    sale_price: Decimal | None = Field(default=None, gt=0)
    target_margin_pct: Decimal | None = Field(default=None, ge=0, lt=100)
    vat_rate_pct: Decimal | None = Field(default=None, ge=0, lt=100)
    iibb_rate_pct: Decimal | None = Field(default=None, ge=0, lt=100)
    ads_rate_pct: Decimal | None = Field(default=None, ge=0, lt=100)
    refund_rate_pct: Decimal | None = Field(default=None, ge=0, lt=100)
    package: PackageInput | None = None
    condition: str = Field(default="new", min_length=1, max_length=40)
    currency_id: str = Field(default="ARS", min_length=3, max_length=10)


class QuantityTierInput(BaseModel):
    min_purchase_unit: int = Field(gt=1)
    amount: Decimal = Field(gt=0)


class QuantityPricingSimulationRequest(PricingSimulationRequest):
    tiers: list[QuantityTierInput] = Field(min_length=1, max_length=5)


class NewProductPricingRequest(BaseModel):
    sku: str | None = Field(default=None, max_length=120)
    account_id: UUID | None = None
    category_id: str | None = Field(default=None, max_length=40)
    listing_type_id: str | None = Field(default=None, max_length=40)
    gross_cmv: Decimal | None = Field(default=None, ge=0)
    additional_unit_cost_net: Decimal = Field(default=Decimal("0"), ge=0)
    sale_price: Decimal | None = Field(default=None, gt=0)
    target_margin_pct: Decimal | None = Field(default=None, ge=0, lt=100)
    overrides: EconomicOverrides = Field(default_factory=EconomicOverrides)
    package: PackageInput | None = None
    condition: str = Field(default="new", min_length=1, max_length=40)
    currency_id: str = Field(default="ARS", min_length=3, max_length=10)


class ExistingListingPricingRequest(BaseModel):
    account_id: UUID | None = None
    item_id: str | None = Field(default=None, max_length=80)
    mla_id: str | None = Field(default=None, max_length=80)
    sku: str | None = Field(default=None, max_length=120)
    gross_cmv: Decimal | None = Field(default=None, ge=0)
    target_margin_pct: Decimal | None = Field(default=None, ge=0, lt=100)
    overrides: EconomicOverrides = Field(default_factory=EconomicOverrides)


class EconomicResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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


class PriceTargetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    target_margin_pct: Decimal
    gross_price: Decimal
    achieved_margin_pct: Decimal
    probes: int


class PricingAuditResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    parameter_sources: dict[str, str]
    overrides: dict[str, Decimal]
    marketplace_context: dict[str, str | Decimal]
    analyzed_price: Decimal
    scenario_units: int
    target_margin_pct: Decimal
    target_margin_source: str
    minimum_margin_pct: Decimal
    recommended_target_margin_pct: Decimal
    rounding_step: Decimal


class QuantityTierAnalysisResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    min_purchase_unit: int
    amount: Decimal
    analyzed: EconomicResultResponse
    status: Literal["VIABLE", "BAJO_MINIMO"]
    minimum_price: Decimal
    target_price: Decimal


class QuantityPricingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    minimum: PriceTargetResponse
    target: PriceTargetResponse
    tiers: list[QuantityTierAnalysisResponse]


class PricingCalculatorResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    scenario: Literal["NEW_PRODUCT", "EXISTING_LISTING"]
    scenario_units: int
    analyzed: EconomicResultResponse
    mc0: PriceTargetResponse
    mc15: PriceTargetResponse
    mc20: PriceTargetResponse
    minimum: PriceTargetResponse
    target: PriceTargetResponse
    custom: PriceTargetResponse | None
    recommended_price: Decimal
    breakdowns: dict[str, EconomicResultResponse]
    audit: PricingAuditResponse
