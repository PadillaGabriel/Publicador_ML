"""Pricing-calculator application use cases without publication side effects."""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from decimal import ROUND_CEILING, Decimal
from typing import Literal, Protocol
from uuid import UUID

from app.pricing.application.effective_parameters import (
    EffectiveEconomicParameters,
    PricingProfileSource,
    resolve_effective_economic_parameters,
)
from app.pricing.application.optimizer import PriceOptimizer, PriceTargetResult
from app.pricing.domain import (
    EconomicInputs,
    EconomicResult,
    PricingDomainError,
    evaluate_economics,
)
from app.pricing.domain.models import MarketplaceEconomics
from app.pricing.infrastructure.mercadolibre import (
    ExistingListingContext,
    MarketplaceSimulationContext,
)
from app.pricing.schemas import (
    ExistingListingPricingRequest,
    NewProductPricingRequest,
    PackageInput,
    QuantityTierInput,
)

HUNDRED = Decimal(100)


class MarketplacePricingProvider(Protocol):
    def simulate(
        self, context: MarketplaceSimulationContext, gross_price: Decimal
    ) -> MarketplaceEconomics: ...


@dataclass(frozen=True, slots=True)
class PricingAudit:
    parameter_sources: Mapping[str, str]
    overrides: Mapping[str, Decimal]
    marketplace_context: Mapping[str, str | Decimal]
    analyzed_price: Decimal
    scenario_units: int
    target_margin_pct: Decimal
    target_margin_source: str
    minimum_margin_pct: Decimal
    recommended_target_margin_pct: Decimal
    rounding_step: Decimal


@dataclass(frozen=True, slots=True)
class QuantityTierAnalysis:
    min_purchase_unit: int
    amount: Decimal
    analyzed: EconomicResult
    status: Literal["VIABLE", "BAJO_MINIMO"]
    minimum_price: Decimal
    target_price: Decimal


@dataclass(frozen=True, slots=True)
class QuantityPricingResponse:
    minimum: PriceTargetResult
    target: PriceTargetResult
    tiers: tuple[QuantityTierAnalysis, ...]


@dataclass(frozen=True, slots=True)
class PricingCalculationResponse:
    scenario: Literal["NEW_PRODUCT", "EXISTING_LISTING"]
    scenario_units: int
    analyzed: EconomicResult
    mc0: PriceTargetResult
    mc15: PriceTargetResult
    mc20: PriceTargetResult
    minimum: PriceTargetResult
    target: PriceTargetResult
    custom: PriceTargetResult | None
    recommended_price: Decimal
    breakdowns: Mapping[str, EconomicResult]
    audit: PricingAudit


class PricingCalculatorService:
    """Compose profile defaults, a provider simulation, and the pure economics domain."""

    def __init__(
        self,
        *,
        profile: PricingProfileSource,
        provider: MarketplacePricingProvider,
        optimizer: PriceOptimizer | None = None,
    ) -> None:
        self._profile = profile
        self._provider = provider
        self._optimizer = optimizer or PriceOptimizer()

    def calculate_new_product(self, request: NewProductPricingRequest) -> PricingCalculationResponse:
        context = self._new_product_context(request)
        return self._calculate(
            scenario="NEW_PRODUCT",
            gross_cmv=request.gross_cmv,
            additional_unit_cost_net=request.additional_unit_cost_net,
            target_margin_pct=request.target_margin_pct,
            overrides=request.overrides.model_dump(),
            context=context,
            seed_price=request.sale_price or request.gross_cmv * Decimal(2),
        )

    def calculate_quantity_tiers(
        self,
        request: NewProductPricingRequest,
        tiers: list[QuantityTierInput],
    ) -> QuantityPricingResponse:
        """Evaluate B2B unit prices with the same economic engine used by the calculator."""
        context = self._new_product_context(request)
        effective = resolve_effective_economic_parameters(
            self._profile, request.overrides.model_dump()
        )
        probe_index = 0
        evaluations: dict[Decimal, EconomicResult] = {}

        def evaluate(price: Decimal) -> EconomicResult:
            nonlocal probe_index
            cached = evaluations.get(price)
            if cached is not None:
                return cached
            probe_index += 1
            result = self._evaluate(
                price,
                request.gross_cmv,
                request.additional_unit_cost_net,
                effective,
                replace(context, probe_index=probe_index),
            )
            evaluations[price] = result
            return result

        seed_price = request.sale_price or request.gross_cmv * Decimal(2)
        rounding_step = self._profile.rounding_step
        target_margin = (
            request.target_margin_pct
            if request.target_margin_pct is not None
            else self._profile.target_margin_pct
        )
        solved_targets: dict[Decimal, PriceTargetResult] = {}

        def solve_target(margin: Decimal) -> PriceTargetResult:
            cached = solved_targets.get(margin)
            if cached is not None:
                return cached
            solved = self._optimizer.solve(
                evaluate, margin, seed_price, tolerance_price=rounding_step
            )
            solved_targets[margin] = solved
            return solved

        minimum = solve_target(self._profile.minimum_margin_pct)
        target = solve_target(target_margin)
        analyzed_tiers = tuple(
            QuantityTierAnalysis(
                min_purchase_unit=tier.min_purchase_unit,
                amount=tier.amount,
                analyzed=(analyzed := evaluate(tier.amount)),
                status=(
                    "VIABLE"
                    if analyzed.contribution_margin_pct >= self._profile.minimum_margin_pct
                    else "BAJO_MINIMO"
                ),
                minimum_price=minimum.gross_price,
                target_price=target.gross_price,
            )
            for tier in tiers
        )
        return QuantityPricingResponse(minimum=minimum, target=target, tiers=analyzed_tiers)

    def calculate_existing_listing(
        self, request: ExistingListingPricingRequest
    ) -> PricingCalculationResponse:
        self._require_gross_cmv(request.gross_cmv)
        item_id = request.item_id or request.mla_id
        if not item_id:
            if request.sku:
                raise PricingDomainError(
                    "SIN_BASELINE_CONFIABLE",
                    "An SKU cannot be resolved to a Mercado Libre listing without a reliable baseline.",
                )
            raise PricingDomainError("SIN_BASELINE_CONFIABLE", "Missing Mercado Libre listing identifier.")
        if request.account_id is None:
            raise PricingDomainError("SIN_PARAMETROS_ECONOMICOS", "Missing Mercado Libre account.")
        resolver = getattr(self._provider, "resolve_existing_listing", None)
        if not callable(resolver):
            raise PricingDomainError(
                "SIN_BASELINE_CONFIABLE",
                "The marketplace provider cannot resolve an existing listing baseline.",
            )
        baseline = resolver(account_id=request.account_id, item_id=item_id)
        if not isinstance(baseline, ExistingListingContext):
            raise PricingDomainError("SIN_BASELINE_CONFIABLE", "Invalid existing listing baseline.")
        self._require_text(baseline.category_id, "SIN_CATEGORIA", "category")
        self._require_text(baseline.listing_type_id, "SIN_LISTING_TYPE", "listing type")
        self._require_text(baseline.condition, "SIN_BASELINE_CONFIABLE", "condition")
        if baseline.current_price is None or baseline.current_price <= 0:
            raise PricingDomainError("SIN_BASELINE_CONFIABLE", "Missing current listing price.")
        context = self._simulation_context(
            account_id=request.account_id,
            category_id=baseline.category_id,
            listing_type_id=baseline.listing_type_id,
            currency_id=baseline.currency_id or "ARS",
            package=baseline.package,
            condition=baseline.condition,
        )
        return self._calculate(
            scenario="EXISTING_LISTING",
            gross_cmv=request.gross_cmv,
            additional_unit_cost_net=Decimal(0),
            target_margin_pct=request.target_margin_pct,
            overrides=request.overrides.model_dump(),
            context=context,
            seed_price=baseline.current_price,
        )

    def _calculate(
        self,
        *,
        scenario: Literal["NEW_PRODUCT", "EXISTING_LISTING"],
        gross_cmv: Decimal,
        additional_unit_cost_net: Decimal,
        target_margin_pct: Decimal | None,
        overrides: Mapping[str, Decimal | None],
        context: MarketplaceSimulationContext,
        seed_price: Decimal,
    ) -> PricingCalculationResponse:
        effective = resolve_effective_economic_parameters(self._profile, overrides)

        probe_index = 0
        evaluations: dict[Decimal, EconomicResult] = {}

        def evaluate(price: Decimal) -> EconomicResult:
            nonlocal probe_index
            cached = evaluations.get(price)
            if cached is not None:
                return cached
            probe_index += 1
            result = self._evaluate(
                price,
                gross_cmv,
                additional_unit_cost_net,
                effective,
                replace(context, probe_index=probe_index),
            )
            evaluations[price] = result
            return result

        rounding_step = self._profile.rounding_step
        effective_target_margin_pct = (
            target_margin_pct if target_margin_pct is not None else self._profile.target_margin_pct
        )
        recommended_target_margin_pct = max(
            effective_target_margin_pct, self._profile.minimum_margin_pct
        )

        analyzed = evaluate(seed_price)
        solved_targets: dict[Decimal, PriceTargetResult] = {}

        def solve_target(target_margin: Decimal) -> PriceTargetResult:
            cached = solved_targets.get(target_margin)
            if cached is not None:
                return cached
            solved = self._optimizer.solve(
                evaluate, target_margin, seed_price, tolerance_price=rounding_step
            )
            solved_targets[target_margin] = solved
            return solved

        mc0 = solve_target(Decimal(0))
        mc15 = solve_target(Decimal(15))
        mc20 = solve_target(Decimal(20))
        minimum = solve_target(self._profile.minimum_margin_pct)
        target = solve_target(effective_target_margin_pct)
        custom = solve_target(target_margin_pct) if target_margin_pct is not None else None
        recommended = solve_target(recommended_target_margin_pct)
        recommended_price = recommended.gross_price
        breakdowns: dict[str, EconomicResult] = {
            "mc0": evaluate(mc0.gross_price),
            "mc15": evaluate(mc15.gross_price),
            "mc20": evaluate(mc20.gross_price),
            "minimum": evaluate(minimum.gross_price),
            "target": evaluate(target.gross_price),
            "recommended": evaluate(recommended_price),
        }
        if custom is not None:
            breakdowns["custom"] = evaluate(custom.gross_price)
        audit = PricingAudit(
            parameter_sources=effective.sources,
            overrides={key: value for key, value in overrides.items() if value is not None},
            marketplace_context={
                "category_id": context.category_id,
                "listing_type_id": context.listing_type_id,
                "currency_id": context.currency_id,
                "logistic_type": context.logistic_type or "",
                "shipping_mode": context.shipping_mode or "",
                "dimensions": context.dimensions,
                "package_weight_grams": context.package_weight_grams,
                "free_shipping": str(context.free_shipping).lower(),
            },
            analyzed_price=seed_price,
            scenario_units=1,
            target_margin_pct=effective_target_margin_pct,
            target_margin_source=(
                "SIMULATION_OVERRIDE" if target_margin_pct is not None else "GLOBAL_PROFILE"
            ),
            minimum_margin_pct=self._profile.minimum_margin_pct,
            recommended_target_margin_pct=recommended_target_margin_pct,
            rounding_step=rounding_step,
        )
        return PricingCalculationResponse(
            scenario=scenario,
            scenario_units=1,
            analyzed=analyzed,
            mc0=mc0,
            mc15=mc15,
            mc20=mc20,
            minimum=minimum,
            target=target,
            custom=custom,
            recommended_price=recommended_price,
            breakdowns=breakdowns,
            audit=audit,
        )

    def _evaluate(
        self,
        price: Decimal,
        gross_cmv: Decimal,
        additional_unit_cost_net: Decimal,
        effective: EffectiveEconomicParameters,
        context: MarketplaceSimulationContext,
    ) -> EconomicResult:
        marketplace = self._provider.simulate(context, price)
        additional_unit_cost = additional_unit_cost_net + self._additional_unit_cost(
            price, gross_cmv, effective
        )
        return evaluate_economics(
            EconomicInputs(
                gross_price=price,
                gross_cmv=gross_cmv,
                vat_rate=effective.vat_rate_pct / HUNDRED,
                iibb_rate=effective.iibb_rate_pct / HUNDRED,
                ads_rate=effective.ads_rate_pct / HUNDRED,
                refund_rate=effective.refund_rate_pct / HUNDRED,
                additional_unit_cost=additional_unit_cost,
            ),
            marketplace,
        )

    def _additional_unit_cost(
        self,
        price: Decimal,
        gross_cmv: Decimal,
        effective: EffectiveEconomicParameters,
    ) -> Decimal:
        vat_factor = Decimal(1) + effective.vat_rate_pct / HUNDRED
        bases = {
            "GROSS_SALE": price,
            "NET_SALE_EX_VAT": price / vat_factor,
            "TAXABLE_REVENUE": price / vat_factor,
            "PRODUCT_COST": gross_cmv / vat_factor,
            "FIXED_PER_UNIT": Decimal(1),
            "FIXED_PER_ORDER": Decimal(1),
        }
        additional_cost = Decimal(0)
        for component in effective.components:
            if component.kind in {"FIXED_PER_UNIT", "FIXED_PER_ORDER"}:
                additional_cost += component.value
                continue
            if component.kind == "FIXED_MONTHLY":
                units = self._profile.monthly_units_projection
                if units is None or units <= 0:
                    raise PricingDomainError(
                        "SIN_PARAMETROS_ECONOMICOS",
                        "A monthly units projection is required to allocate fixed monthly costs.",
                    )
                additional_cost += component.value / Decimal(units)
                continue
            base = bases.get(component.basis)
            if base is None:
                raise PricingDomainError(
                    "SIN_PARAMETROS_ECONOMICOS",
                    f"Unsupported calculation basis: {component.basis}.",
                )
            if component.kind in {"PERCENTAGE_OF_PRICE", "PERCENTAGE_OF_COST"}:
                additional_cost += base * component.value / HUNDRED
                continue
            raise PricingDomainError(
                "SIN_PARAMETROS_ECONOMICOS",
                f"Unsupported cost component kind: {component.kind}.",
            )
        return additional_cost

    def _new_product_context(
        self, request: NewProductPricingRequest
    ) -> MarketplaceSimulationContext:
        self._require_gross_cmv(request.gross_cmv)
        self._require_text(request.category_id, "SIN_CATEGORIA", "category")
        self._require_text(request.listing_type_id, "SIN_LISTING_TYPE", "listing type")
        return self._simulation_context(
            account_id=request.account_id,
            category_id=request.category_id,
            listing_type_id=request.listing_type_id,
            currency_id=request.currency_id,
            package=request.package,
            condition=request.condition,
        )

    @staticmethod
    def _simulation_context(
        *,
        account_id: UUID | None,
        category_id: str,
        listing_type_id: str,
        currency_id: str,
        package: PackageInput | None,
        condition: str = "new",
    ) -> MarketplaceSimulationContext:
        if package is None or not package.dimensions or package.weight is None:
            raise PricingDomainError("SIN_DIMENSIONES", "Missing package dimensions or weight.")
        if account_id is None:
            raise PricingDomainError("SIN_PARAMETROS_ECONOMICOS", "Missing Mercado Libre account.")
        if not package.logistic_type or not package.shipping_mode:
            raise PricingDomainError("SIN_CONTEXTO_LOGISTICO", "Missing package logistics context.")
        if package.free_shipping is None:
            raise PricingDomainError(
                "SIN_CONTEXTO_LOGISTICO",
                "Missing explicit free-shipping policy for the marketplace simulation.",
            )
        return MarketplaceSimulationContext(
            account_id=account_id,
            site_id="MLA",
            category_id=category_id,
            listing_type_id=listing_type_id,
            currency_id=currency_id,
            logistic_type=package.logistic_type,
            shipping_mode=package.shipping_mode,
            dimensions=package.dimensions,
            package_weight_grams=PricingCalculatorService._billable_weight_in_grams(package.weight),
            free_shipping=package.free_shipping,
            condition=condition,
        )

    @staticmethod
    def _billable_weight_in_grams(weight_in_kg: Decimal) -> Decimal:
        """Convert the calculator's kg input to Mercado Libre's whole-gram contract."""
        if weight_in_kg <= 0:
            raise PricingDomainError("SIN_DIMENSIONES", "Package weight must be greater than zero.")
        return (weight_in_kg * Decimal(1000)).to_integral_value(rounding=ROUND_CEILING)

    @staticmethod
    def _require_gross_cmv(value: Decimal | None) -> None:
        if value is None:
            raise PricingDomainError("SIN_CMV", "Missing gross CMV.")

    @staticmethod
    def _require_text(value: str | None, code: str, name: str) -> None:
        if value is None or not value.strip():
            raise PricingDomainError(code, f"Missing {name}.")
