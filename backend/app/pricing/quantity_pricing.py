from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP


def quantity_discount_pct(*, retail_price: Decimal, amount: Decimal) -> Decimal:
    """Return the unit discount percentage against the retail price."""
    if retail_price <= 0 or amount <= 0:
        raise ValueError("Retail and quantity prices must be greater than zero.")
    if amount >= retail_price:
        return Decimal(0)
    return (
        (retail_price - amount) / retail_price * Decimal(100)
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
