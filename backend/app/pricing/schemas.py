from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator

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


class PricingSimulationRequest(BaseModel):
    product_cost: Decimal = Field(ge=0)
    additional_unit_costs: list[AdditionalUnitCost] = Field(default_factory=list, max_length=30)
    sale_price: Decimal | None = Field(default=None, gt=0)
    target_margin_pct: Decimal | None = Field(default=None, ge=0, lt=100)
    vat_rate_pct: Decimal | None = Field(default=None, ge=0, lt=100)
    iibb_rate_pct: Decimal | None = Field(default=None, ge=0, lt=100)
    ads_rate_pct: Decimal | None = Field(default=None, ge=0, lt=100)
    refund_rate_pct: Decimal | None = Field(default=None, ge=0, lt=100)
    units_per_order: Decimal = Field(default=Decimal("1"), gt=0)
    channel: str = Field(default="MERCADOLIBRE", min_length=1, max_length=40)
