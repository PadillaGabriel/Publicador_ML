from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.publication.payload import resolved_price_for_draft


def version(price="1000", increments=None):
    return SimpleNamespace(price=Decimal(price), commercial={"installment_increments_pct": increments or {}})


def draft(**config):
    return SimpleNamespace(commercial_config=config)


def test_classic_and_installment_prices_are_independent():
    current = version(increments={"3": 10, "6": 20})
    assert resolved_price_for_draft(current, draft()) == Decimal("1000")
    assert resolved_price_for_draft(current, draft(installments_count=3)) == Decimal("1100.00")
    assert resolved_price_for_draft(current, draft(installments_count=6)) == Decimal("1200.00")


def test_manual_override_wins_over_installment_rule():
    current = version(increments={"6": 50})
    assert resolved_price_for_draft(
        current, draft(installments_count=6, price_override="1333.50")
    ) == Decimal("1333.50")


def test_invalid_installment_plan_fails_explicitly():
    with pytest.raises(ValueError):
        resolved_price_for_draft(version(), draft(installments_count=12))
