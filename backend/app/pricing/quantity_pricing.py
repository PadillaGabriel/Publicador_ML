from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal


@dataclass(frozen=True, slots=True)
class OptimalQuantityPrice:
    amount: Decimal
    status: Literal["OPTIMO", "SIN_VENTAJA"]
    discount_pct: Decimal


def quote_optimal_quantity_price(
    *,
    retail_price: Decimal,
    minimum_sustainable_price: Decimal,
) -> OptimalQuantityPrice:
    """Return the deepest sustainable unit discount without crossing the configured margin floor."""
    if retail_price <= 0 or minimum_sustainable_price <= 0:
        raise ValueError("Retail and minimum sustainable prices must be greater than zero.")

    if minimum_sustainable_price >= retail_price:
        return OptimalQuantityPrice(
            amount=minimum_sustainable_price,
            status="SIN_VENTAJA",
            discount_pct=Decimal(0),
        )

    discount_pct = (
        (retail_price - minimum_sustainable_price) / retail_price * Decimal(100)
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return OptimalQuantityPrice(
        amount=minimum_sustainable_price,
        status="OPTIMO",
        discount_pct=discount_pct,
    )
