from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING

ZERO = Decimal("0")
HUNDRED = Decimal("100")


@dataclass(frozen=True, slots=True)
class CostComponentValue:
    name: str
    kind: str
    value: Decimal


@dataclass(frozen=True, slots=True)
class PricingInputs:
    product_cost: Decimal
    additional_unit_costs: tuple[tuple[str, Decimal], ...]
    components: tuple[CostComponentValue, ...]
    monthly_units_projection: int | None
    units_per_order: Decimal
    target_margin_pct: Decimal
    minimum_margin_pct: Decimal
    rounding_step: Decimal
    sale_price: Decimal | None = None


def _pct(value: Decimal) -> Decimal:
    return value / HUNDRED


def _round_up(value: Decimal, step: Decimal) -> Decimal:
    if step <= 0:
        return value
    units = (value / step).to_integral_value(rounding=ROUND_CEILING)
    return (units * step).quantize(Decimal("0.01"))


def calculate_pricing(inputs: PricingInputs) -> dict:
    direct_cost = inputs.product_cost + sum((amount for _, amount in inputs.additional_unit_costs), ZERO)
    fixed_per_unit = ZERO
    fixed_per_order = ZERO
    allocated_monthly = ZERO
    pct_of_price = ZERO
    pct_of_cost = ZERO
    warnings: list[str] = []
    breakdown: list[dict] = [
        {"name": "Costo del producto", "kind": "PRODUCT_COST", "amount": inputs.product_cost}
    ]
    breakdown.extend(
        {"name": name, "kind": "ADDITIONAL_UNIT_COST", "amount": amount}
        for name, amount in inputs.additional_unit_costs
    )

    for component in inputs.components:
        if component.kind == "FIXED_PER_UNIT":
            fixed_per_unit += component.value
            breakdown.append({"name": component.name, "kind": component.kind, "amount": component.value})
        elif component.kind == "FIXED_PER_ORDER":
            allocated = component.value / inputs.units_per_order
            fixed_per_order += allocated
            breakdown.append({"name": component.name, "kind": component.kind, "amount": allocated})
        elif component.kind == "FIXED_MONTHLY":
            if inputs.monthly_units_projection:
                allocated = component.value / Decimal(inputs.monthly_units_projection)
                allocated_monthly += allocated
                breakdown.append({"name": component.name, "kind": component.kind, "amount": allocated})
            else:
                warnings.append(
                    f"{component.name}: falta una proyección mensual de unidades para asignar este costo fijo."
                )
        elif component.kind == "PERCENTAGE_OF_PRICE":
            pct_of_price += _pct(component.value)
        elif component.kind == "PERCENTAGE_OF_COST":
            pct_of_cost += _pct(component.value)

    cost_percentage_amount = direct_cost * pct_of_cost
    if cost_percentage_amount:
        breakdown.append({
            "name": "Costos porcentuales sobre costo",
            "kind": "PERCENTAGE_OF_COST",
            "amount": cost_percentage_amount,
        })

    marginal_unit_cost = direct_cost + fixed_per_unit + fixed_per_order + cost_percentage_amount
    variable_base_cost = marginal_unit_cost + allocated_monthly
    target_margin = _pct(inputs.target_margin_pct)
    minimum_margin = _pct(inputs.minimum_margin_pct)

    floor_denominator = Decimal("1") - pct_of_price
    target_denominator = Decimal("1") - pct_of_price - target_margin
    minimum_denominator = Decimal("1") - pct_of_price - minimum_margin
    if floor_denominator <= 0:
        raise ValueError("Los costos porcentuales sobre precio deben ser menores al 100%.")
    if target_denominator <= 0:
        raise ValueError("Costos porcentuales + margen objetivo deben ser menores al 100%.")
    if minimum_denominator <= 0:
        raise ValueError("Costos porcentuales + margen mínimo deben ser menores al 100%.")

    break_even_price = variable_base_cost / floor_denominator
    minimum_price = variable_base_cost / minimum_denominator
    target_price = variable_base_cost / target_denominator
    recommended_price = _round_up(target_price, inputs.rounding_step)

    result = {
        "direct_unit_cost": direct_cost.quantize(Decimal("0.01")),
        "marginal_unit_cost": marginal_unit_cost.quantize(Decimal("0.01")),
        "allocated_fixed_cost": allocated_monthly.quantize(Decimal("0.01")),
        "fixed_per_unit_and_order": (fixed_per_unit + fixed_per_order).quantize(Decimal("0.01")),
        "variable_base_cost": variable_base_cost.quantize(Decimal("0.01")),
        "price_cost_rate_pct": (pct_of_price * HUNDRED).quantize(Decimal("0.0001")),
        "break_even_price": break_even_price.quantize(Decimal("0.01")),
        "minimum_price": minimum_price.quantize(Decimal("0.01")),
        "target_price": target_price.quantize(Decimal("0.01")),
        "recommended_price": recommended_price,
        "target_margin_pct": inputs.target_margin_pct,
        "minimum_margin_pct": inputs.minimum_margin_pct,
        "breakdown": breakdown,
        "warnings": warnings,
    }

    if inputs.sale_price:
        percentage_cost_at_sale = inputs.sale_price * pct_of_price
        effective_variable_cost = variable_base_cost + percentage_cost_at_sale
        contribution = inputs.sale_price - effective_variable_cost
        contribution_margin_pct = contribution / inputs.sale_price * HUNDRED
        markup_pct = (
            (inputs.sale_price - effective_variable_cost) / effective_variable_cost * HUNDRED
            if effective_variable_cost > 0 else ZERO
        )
        if contribution < 0:
            health = "NEGATIVE_CONTRIBUTION"
        elif contribution_margin_pct < inputs.minimum_margin_pct:
            health = "BELOW_MINIMUM"
        elif contribution_margin_pct < inputs.target_margin_pct:
            health = "BELOW_TARGET"
        else:
            health = "HEALTHY"
        result["at_sale_price"] = {
            "sale_price": inputs.sale_price.quantize(Decimal("0.01")),
            "percentage_cost_amount": percentage_cost_at_sale.quantize(Decimal("0.01")),
            "effective_variable_cost": effective_variable_cost.quantize(Decimal("0.01")),
            "contribution_amount": contribution.quantize(Decimal("0.01")),
            "contribution_margin_pct": contribution_margin_pct.quantize(Decimal("0.01")),
            "markup_pct": markup_pct.quantize(Decimal("0.01")),
            "health": health,
        }
    else:
        result["at_sale_price"] = None

    return result
