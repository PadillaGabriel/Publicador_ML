import uuid
from decimal import Decimal

import pytest

from app.persistence import PricingCostComponent, PricingProfile
from app.pricing.application import resolve_effective_economic_parameters
from app.pricing.schemas import PricingProfileUpsert
from app.pricing.service import upsert_default_profile


class _ProfileSession:
    def __init__(self, profile: PricingProfile):
        self.profile = profile
        self.added = []

    def scalar(self, statement):
        return self.profile

    def add(self, entity):
        self.added.append(entity)

    def execute(self, statement):
        return None

    def flush(self):
        return None

    def commit(self):
        return None

    def refresh(self, entity):
        return None


def test_profile_upsert_preserves_explicit_economic_percentages():
    """Catches accidental fallback of explicitly configured economics to zero/defaults."""
    payload = PricingProfileUpsert(
        vat_rate_pct=Decimal("21"),
        iibb_rate_pct=Decimal("3"),
        ads_rate_pct=Decimal("5"),
        refund_rate_pct=Decimal("1"),
        target_margin_pct=Decimal("20"),
        minimum_margin_pct=Decimal("10"),
    )

    assert payload.vat_rate_pct == Decimal("21")
    assert payload.iibb_rate_pct == Decimal("3")
    assert payload.ads_rate_pct == Decimal("5")
    assert payload.refund_rate_pct == Decimal("1")
    assert payload.target_margin_pct == Decimal("20")
    assert payload.minimum_margin_pct == Decimal("10")


def test_upsert_default_profile_persists_every_explicit_economic_rate():
    """Catches dropping configured rate fields while the default profile is saved."""
    profile = PricingProfile(id=uuid.uuid4(), channel="MERCADOLIBRE", is_default=True)
    payload = PricingProfileUpsert(
        vat_rate_pct=Decimal("21"),
        iibb_rate_pct=Decimal("3"),
        ads_rate_pct=Decimal("5"),
        refund_rate_pct=Decimal("1"),
    )

    saved = upsert_default_profile(_ProfileSession(profile), payload)

    assert saved.vat_rate_pct == Decimal("21")
    assert saved.iibb_rate_pct == Decimal("3")
    assert saved.ads_rate_pct == Decimal("5")
    assert saved.refund_rate_pct == Decimal("1")


def test_simulation_override_is_resolved_without_mutating_global_profile():
    """Catches an override leaking back into the persisted global advertising rate."""
    profile = PricingProfile(
        vat_rate_pct=Decimal("21"),
        iibb_rate_pct=Decimal("3"),
        ads_rate_pct=Decimal("5"),
        refund_rate_pct=Decimal("1"),
    )

    effective = resolve_effective_economic_parameters(
        profile,
        {"ads_rate_pct": Decimal("8")},
    )

    assert effective.ads_rate_pct == Decimal("8")
    assert effective.sources == {
        "vat_rate_pct": "GLOBAL_PROFILE",
        "iibb_rate_pct": "GLOBAL_PROFILE",
        "ads_rate_pct": "SIMULATION_OVERRIDE",
        "refund_rate_pct": "GLOBAL_PROFILE",
    }
    assert profile.ads_rate_pct == Decimal("5")


def test_effective_parameters_preserve_active_component_basis():
    """Catches losing the persisted calculation basis while resolving a profile."""
    profile = PricingProfile(
        vat_rate_pct=Decimal("21"),
        iibb_rate_pct=Decimal("0"),
        ads_rate_pct=Decimal("0"),
        refund_rate_pct=Decimal("0"),
        components=[
            PricingCostComponent(
                name="Comisión",
                kind="PERCENTAGE_OF_PRICE",
                value=Decimal("15"),
                basis="NET_SALE_EX_VAT",
                active=True,
            )
        ],
    )

    effective = resolve_effective_economic_parameters(profile, {})

    assert effective.components[0].basis == "NET_SALE_EX_VAT"


@pytest.mark.parametrize(
    "basis",
    [
        "GROSS_SALE",
        "NET_SALE_EX_VAT",
        "TAXABLE_REVENUE",
        "PRODUCT_COST",
        "FIXED_PER_UNIT",
        "FIXED_PER_ORDER",
    ],
)
def test_cost_component_accepts_each_supported_calculation_basis(basis):
    """Catches rejecting a valid persisted component basis at the input boundary."""
    payload = PricingProfileUpsert(components=[{"name": "Costo", "kind": "FIXED_PER_UNIT", "value": "1", "basis": basis}])

    assert payload.components[0].basis == basis


def test_cost_component_rejects_a_basis_outside_the_supported_set():
    """Catches accepting a persisted component basis with no defined calculation meaning."""
    with pytest.raises(ValueError):
        PricingProfileUpsert(
            components=[
                {"name": "Costo", "kind": "FIXED_PER_UNIT", "value": "1", "basis": "NET_PROFIT"}
            ]
        )
