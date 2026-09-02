from decimal import Decimal
from importlib import import_module

import pytest

from app.pricing.domain import EconomicResult, PricingDomainError


def _economic_result(margin_pct: Decimal) -> EconomicResult:
    values = {name: Decimal(0) for name in EconomicResult.__dataclass_fields__}
    values["contribution_margin_pct"] = margin_pct
    return EconomicResult(**values)


def _optimizer() -> object:
    return import_module("app.pricing.application.optimizer").PriceOptimizer()


def test_optimizer_finds_lowest_price_that_reaches_target():
    optimizer = _optimizer()

    result = optimizer.solve(
        evaluator=lambda price: _economic_result(price / Decimal(100)),
        target_margin_pct=Decimal(20),
        seed_price=Decimal(1000),
    )

    assert result.gross_price == Decimal(2000)
    assert result.achieved_margin_pct == Decimal(20)
    assert result.target_margin_pct == Decimal(20)


def test_optimizer_finds_lowest_price_after_fixed_fee_discontinuity():
    optimizer = _optimizer()

    def evaluator(price: Decimal) -> EconomicResult:
        fixed_fee = Decimal(1000) if price < Decimal(33000) else Decimal(0)
        return _economic_result(Decimal(20) if fixed_fee == Decimal(0) else Decimal(19))

    result = optimizer.solve(
        evaluator=evaluator,
        target_margin_pct=Decimal(20),
        seed_price=Decimal(30000),
    )

    assert result.gross_price == Decimal(33000)
    assert result.achieved_margin_pct >= Decimal(20)


def test_optimizer_finds_lowest_price_after_logistic_subsidy_discontinuity():
    optimizer = _optimizer()

    def evaluator(price: Decimal) -> EconomicResult:
        shipping_subsidy = Decimal(0) if price < Decimal(40000) else Decimal(1500)
        return _economic_result(Decimal(15) if shipping_subsidy == Decimal(0) else Decimal(20))

    result = optimizer.solve(
        evaluator=evaluator,
        target_margin_pct=Decimal(20),
        seed_price=Decimal(30000),
    )

    assert result.gross_price == Decimal(40000)
    assert result.achieved_margin_pct >= Decimal(20)


def test_optimizer_raises_when_probe_limit_does_not_reach_target():
    with pytest.raises(PricingDomainError) as exc:
        _optimizer().solve(
            evaluator=lambda price: _economic_result(Decimal(0)),
            target_margin_pct=Decimal(20),
            seed_price=Decimal(100),
            max_probes=3,
        )

    assert exc.value.code == "OBJETIVO_NO_CONVERGE"
