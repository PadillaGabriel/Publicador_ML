from collections.abc import Callable
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

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
    def solve_many(
        self,
        evaluator: Callable[[Decimal], EconomicResult],
        target_margin_pcts: list[Decimal] | tuple[Decimal, ...],
        seed_price: Decimal,
        *,
        tolerance_price: Decimal = Decimal(1),
        max_probes: int = 80,
    ) -> dict[Decimal, PriceTargetResult]:
        """Solve multiple margin targets on one shared price-probe tree.

        The single-target solver assumes contribution margin is monotonic in price.
        This method keeps the same contract but lets all requested targets reuse the
        exact same provider evaluations, which materially reduces Mercado Libre
        round-trips when a calculator needs several margin scenarios at once.
        """
        targets = sorted(set(target_margin_pcts))
        if not targets:
            return {}
        if not isinstance(seed_price, Decimal) or not isinstance(tolerance_price, Decimal):
            raise PricingDomainError(
                "SIN_PARAMETROS_ECONOMICOS", "Optimizer inputs must be Decimal."
            )
        if not all(isinstance(target, Decimal) for target in targets):
            raise PricingDomainError(
                "SIN_PARAMETROS_ECONOMICOS", "Optimizer inputs must be Decimal."
            )
        if seed_price <= 0 or tolerance_price <= 0 or max_probes < 1:
            raise PricingDomainError(
                "SIN_PARAMETROS_ECONOMICOS", "Invalid optimizer bounds."
            )

        evaluations: dict[int, EconomicResult] = {}

        def evaluate_index(index: int) -> EconomicResult:
            if index < 1:
                index = 1
            if index not in evaluations:
                if len(evaluations) >= max_probes:
                    raise PricingDomainError(
                        "OBJETIVO_NO_CONVERGE",
                        "Target contribution margins were not reached within the probe limit.",
                    )
                evaluations[index] = evaluator(tolerance_price * Decimal(index))
            return evaluations[index]

        seed_index = max(
            1,
            int((seed_price / tolerance_price).to_integral_value(rounding=ROUND_CEILING)),
        )
        minimum_index = 1
        minimum_margin = evaluate_index(minimum_index).contribution_margin_pct
        maximum_target = targets[-1]

        upper_index = max(seed_index, minimum_index)
        while evaluate_index(upper_index).contribution_margin_pct < maximum_target:
            upper_index *= 2

        solved_indices: dict[Decimal, int] = {}
        pending = []
        for target in targets:
            if minimum_margin >= target:
                solved_indices[target] = minimum_index
            else:
                pending.append(target)

        def locate(low_index: int, high_index: int, unresolved: list[Decimal]) -> None:
            if not unresolved:
                return
            if high_index - low_index <= 1:
                for target in unresolved:
                    solved_indices[target] = high_index
                return

            middle_index = (low_index + high_index) // 2
            middle_margin = evaluate_index(middle_index).contribution_margin_pct
            left = [target for target in unresolved if middle_margin >= target]
            right = [target for target in unresolved if middle_margin < target]
            locate(low_index, middle_index, left)
            locate(middle_index, high_index, right)

        locate(minimum_index, upper_index, pending)
        probe_count = len(evaluations)
        return {
            target: PriceTargetResult(
                target_margin_pct=target,
                gross_price=tolerance_price * Decimal(solved_indices[target]),
                achieved_margin_pct=evaluate_index(solved_indices[target]).contribution_margin_pct,
                probes=probe_count,
            )
            for target in targets
        }

