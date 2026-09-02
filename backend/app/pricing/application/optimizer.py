from collections.abc import Callable
from dataclasses import dataclass
from decimal import ROUND_FLOOR, Decimal

from app.pricing.domain.errors import PricingDomainError
from app.pricing.domain.models import EconomicResult


@dataclass(frozen=True, slots=True)
class PriceTargetResult:
    target_margin_pct: Decimal
    gross_price: Decimal
    achieved_margin_pct: Decimal
    probes: int


class PriceOptimizer:
    def solve(
        self,
        evaluator: Callable[[Decimal], EconomicResult],
        target_margin_pct: Decimal,
        seed_price: Decimal,
        *,
        tolerance_price: Decimal = Decimal(1),
        max_probes: int = 40,
    ) -> PriceTargetResult:
        if not all(
            isinstance(value, Decimal)
            for value in (target_margin_pct, seed_price, tolerance_price)
        ):
            raise PricingDomainError("SIN_PARAMETROS_ECONOMICOS", "Optimizer inputs must be Decimal.")
        if seed_price <= 0 or tolerance_price <= 0 or max_probes < 1:
            raise PricingDomainError("SIN_PARAMETROS_ECONOMICOS", "Invalid optimizer bounds.")

        evaluations: dict[Decimal, EconomicResult] = {}

        def evaluate(price: Decimal) -> EconomicResult:
            if price not in evaluations:
                if len(evaluations) >= max_probes:
                    raise PricingDomainError(
                        "OBJETIVO_NO_CONVERGE",
                        "Target contribution margin was not reached within the probe limit.",
                    )
                evaluations[price] = evaluator(price)
            return evaluations[price]

        def meets_target(price: Decimal) -> bool:
            return evaluate(price).contribution_margin_pct >= target_margin_pct

        seed_matches = meets_target(seed_price)
        if seed_matches:
            high = seed_price
            low = Decimal(0)
            while high > tolerance_price:
                candidate = high / Decimal(2)
                if meets_target(candidate):
                    high = candidate
                else:
                    low = candidate
                    break
        else:
            low = seed_price
            high = seed_price * Decimal(2)
            while not meets_target(high):
                low = high
                high *= Decimal(2)

        while high - low > tolerance_price:
            candidate = (low + high) / Decimal(2)
            if meets_target(candidate):
                high = candidate
            else:
                low = candidate

        grid_price = (high / tolerance_price).to_integral_value(rounding=ROUND_FLOOR) * tolerance_price
        neighborhood = (grid_price - tolerance_price, grid_price, grid_price + tolerance_price)
        satisfying = [
            price
            for price in neighborhood
            if price > 0 and meets_target(price)
        ]
        if not satisfying:
            raise PricingDomainError(
                "OBJETIVO_NO_CONVERGE",
                "Target contribution margin was not reached within the probe limit.",
            )

        gross_price = min(satisfying)
        achieved_margin_pct = evaluate(gross_price).contribution_margin_pct
        return PriceTargetResult(
            target_margin_pct=target_margin_pct,
            gross_price=gross_price,
            achieved_margin_pct=achieved_margin_pct,
            probes=len(evaluations),
        )
