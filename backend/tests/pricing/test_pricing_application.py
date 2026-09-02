from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.persistence import PricingCostComponent, PricingProfile
from app.pricing import service
from app.pricing.application import resolve_effective_economic_parameters
from app.pricing.application.calculator import (
    ExistingListingContext,
    PricingCalculatorService,
)
from app.pricing.domain import PricingDomainError
from app.pricing.domain.models import MarketplaceEconomics
from app.pricing.infrastructure.cache import PricingCacheKey, PricingSimulationCache
from app.pricing.schemas import (
    EconomicOverrides,
    ExistingListingPricingRequest,
    NewProductPricingRequest,
    PackageInput,
    PricingProfileUpsert,
)


class CountingMarketplaceProvider:
    def __init__(self) -> None:
        self.calls = 0

    def simulate(self) -> MarketplaceEconomics:
        self.calls += 1
        return MarketplaceEconomics(
            percentage_fee=Decimal(16),
            meli_percentage_fee=Decimal(16),
            financing_add_on_fee=Decimal(0),
            fixed_fee=Decimal(2740),
            shipping_cost=Decimal(1200),
            shipping_subsidy=Decimal(0),
            buyer_shipping_amount=Decimal(0),
        )


def simulation_key(*, account_id: UUID, gross_price: str = "20000") -> PricingCacheKey:
    return PricingCacheKey(
        account_id=account_id,
        category_or_item_id="MLA412517",
        listing_type_id="gold_special",
        gross_price=Decimal(gross_price),
        logistic_type="cross_docking",
        shipping_mode="me2",
        billable_weight=Decimal("0.45"),
    )


def cached_marketplace_economics(
    cache: PricingSimulationCache,
    key: PricingCacheKey,
    provider: CountingMarketplaceProvider,
) -> MarketplaceEconomics:
    cached = cache.get(key)
    if cached is not None:
        return cached
    economics = provider.simulate()
    cache.put(key, economics)
    return economics


def test_identical_complete_simulation_context_reuses_marketplace_provider_result():
    """Catches repeating a provider request for an identical simulation context."""
    cache = PricingSimulationCache(max_entries=8, ttl_seconds=60)
    provider = CountingMarketplaceProvider()
    key = simulation_key(account_id=uuid4())

    first = cached_marketplace_economics(cache, key, provider)
    second = cached_marketplace_economics(cache, key, provider)

    assert first == second
    assert provider.calls == 1


def test_simulation_context_with_a_different_price_does_not_reuse_marketplace_result():
    """Catches a cache key that omits gross price and returns another price's economics."""
    cache = PricingSimulationCache(max_entries=8, ttl_seconds=60)
    provider = CountingMarketplaceProvider()
    account_id = uuid4()

    cached_marketplace_economics(
        cache, simulation_key(account_id=account_id, gross_price="20000"), provider
    )
    cached_marketplace_economics(
        cache, simulation_key(account_id=account_id, gross_price="25000"), provider
    )

    assert provider.calls == 2


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


def test_upsert_default_profile_persists_every_explicit_economic_rate(monkeypatch):
    """Catches lost economic rates after a real commit and independent re-query."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    PricingProfile.__table__.create(engine)
    PricingCostComponent.__table__.create(engine)
    monkeypatch.setattr(service, "audit", lambda *args, **kwargs: None)
    payload = PricingProfileUpsert(
        vat_rate_pct=Decimal("21"),
        iibb_rate_pct=Decimal("3"),
        ads_rate_pct=Decimal("5"),
        refund_rate_pct=Decimal("1"),
    )

    with Session(engine) as db:
        saved = service.upsert_default_profile(db, payload)
        profile_id = saved.id
        db.expunge_all()

    with Session(engine) as db:
        persisted = db.scalar(select(PricingProfile).where(PricingProfile.id == profile_id))

    assert persisted is not None
    assert persisted.vat_rate_pct == Decimal("21")
    assert persisted.iibb_rate_pct == Decimal("3")
    assert persisted.ads_rate_pct == Decimal("5")
    assert persisted.refund_rate_pct == Decimal("1")


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


class CalculatorProvider:
    def simulate(self, context, gross_price):
        return MarketplaceEconomics(
            percentage_fee=Decimal("16"),
            meli_percentage_fee=Decimal("16"),
            financing_add_on_fee=Decimal("0"),
            fixed_fee=Decimal("0"),
            shipping_cost=Decimal("0"),
            shipping_subsidy=Decimal("0"),
            buyer_shipping_amount=Decimal("0"),
        )

    def resolve_existing_listing(self, *, account_id, item_id):
        return ExistingListingContext(
            category_id="MLA412517",
            listing_type_id="gold_special",
            current_price=Decimal("24200"),
            currency_id="ARS",
            package=PackageInput(
                dimensions="10x10x10", weight=Decimal("0.45"),
                logistic_type="cross_docking", shipping_mode="me2",
            ),
        )


def calculator_profile() -> PricingProfile:
    return PricingProfile(
        vat_rate_pct=Decimal("21"),
        iibb_rate_pct=Decimal("3"),
        ads_rate_pct=Decimal("5"),
        refund_rate_pct=Decimal("1"),
    )


def test_new_product_uses_global_defaults_and_simulation_override():
    """Catches calculator calls that ignore a simulation override or mutate the profile."""
    profile = calculator_profile()
    service = PricingCalculatorService(profile=profile, provider=CalculatorProvider())

    response = service.calculate_new_product(
        NewProductPricingRequest(
            sku="SKU-1",
            account_id=uuid4(),
            category_id="MLA412517",
            listing_type_id="gold_special",
            gross_cmv=Decimal("12100"),
            target_margin_pct=Decimal("25"),
            overrides=EconomicOverrides(ads_rate_pct=Decimal("8")),
            package=PackageInput(
                dimensions="10x10x10", weight=Decimal("0.45"),
                logistic_type="cross_docking", shipping_mode="me2",
            ),
        )
    )

    assert response.scenario == "NEW_PRODUCT"
    assert response.scenario_units == 1
    assert response.audit.parameter_sources["ads_rate_pct"] == "SIMULATION_OVERRIDE"
    assert response.audit.parameter_sources["iibb_rate_pct"] == "GLOBAL_PROFILE"
    assert response.recommended_price == response.custom.gross_price
    assert profile.ads_rate_pct == Decimal("5")


@pytest.mark.parametrize(
    ("pricing_request", "code"),
    [
        (NewProductPricingRequest(), "SIN_CMV"),
        (NewProductPricingRequest(gross_cmv=Decimal("1")), "SIN_CATEGORIA"),
        (
            NewProductPricingRequest(gross_cmv=Decimal("1"), category_id="MLA1"),
            "SIN_LISTING_TYPE",
        ),
        (
            NewProductPricingRequest(
                category_id="MLA1", listing_type_id="gold_special", gross_cmv=Decimal("1")
            ),
            "SIN_DIMENSIONES",
        ),
    ],
)
def test_new_product_rejects_missing_economic_or_marketplace_context(pricing_request, code):
    """Catches absent calculator inputs being silently converted to known zero values."""
    service = PricingCalculatorService(profile=calculator_profile(), provider=CalculatorProvider())

    with pytest.raises(PricingDomainError) as exc:
        service.calculate_new_product(pricing_request)

    assert exc.value.code == code


def test_existing_listing_resolves_marketplace_context_and_current_price():
    """Catches requiring manually duplicated MLA category, listing type, or current price."""
    service = PricingCalculatorService(profile=calculator_profile(), provider=CalculatorProvider())

    response = service.calculate_existing_listing(
        ExistingListingPricingRequest(account_id=uuid4(), item_id="MLA123", gross_cmv=Decimal("12100"))
    )

    assert response.scenario == "EXISTING_LISTING"
    assert response.analyzed.gross_price == Decimal("24200.00")
    assert response.audit.marketplace_context["category_id"] == "MLA412517"


def test_existing_listing_sku_without_a_reliable_baseline_lookup_is_explicitly_rejected():
    """Catches inventing an SKU-to-MLA baseline lookup that is not available."""
    service = PricingCalculatorService(profile=calculator_profile(), provider=CalculatorProvider())

    with pytest.raises(PricingDomainError) as exc:
        service.calculate_existing_listing(
            ExistingListingPricingRequest(account_id=uuid4(), sku="SKU-1", gross_cmv=Decimal("12100"))
        )

    assert exc.value.code == "SIN_BASELINE_CONFIABLE"
