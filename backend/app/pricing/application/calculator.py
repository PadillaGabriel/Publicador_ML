"""Pricing-calculator application use cases without publication side effects."""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, Protocol
from uuid import UUID

from app.persistence import PricingProfile
from app.pricing.application.effective_parameters import (
    EffectiveEconomicParameters,
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


@dataclass(frozen=True, slots=True)
class PricingCalculationResponse:
    scenario: Literal["NEW_PRODUCT", "EXISTING_LISTING"]
    scenario_units: int
    analyzed: EconomicResult
    mc0: PriceTargetResult
    mc15: PriceTargetResult
    mc20: PriceTargetResult
    custom: PriceTargetResult | None
    recommended_price: Decimal
    audit: PricingAudit


class PricingCalculatorService:
    """Compose profile defaults, a provider simulation, and the pure economics domain."""

    def __init__(
        self,
        *,
        profile: PricingProfile,
        provider: MarketplacePricingProvider,
        optimizer: PriceOptimizer | None = None,
    ) -> None:
        self._profile = profile
        self._provider = provider
        self._optimizer = optimizer or PriceOptimizer()

    def calculate_new_product(self, request: NewProductPricingRequest) -> PricingCalculationResponse:
        self._require_gross_cmv(request.gross_cmv)
        self._require_text(request.category_id, "SIN_CATEGORIA", "category")
        self._require_text(request.listing_type_id, "SIN_LISTING_TYPE", "listing type")
        context = self._simulation_context(
            account_id=request.account_id,
            category_id=request.category_id,
            listing_type_id=request.listing_type_id,
            currency_id=request.currency_id,
            package=request.package,
        )
        return self._calculate(
            scenario="NEW_PRODUCT",
            gross_cmv=request.gross_cmv,
            additional_unit_cost_net=request.additional_unit_cost_net,
            target_margin_pct=request.target_margin_pct,
            overrides=request.overrides.model_dump(),
            context=context,
            seed_price=request.sale_price or request.gross_cmv * Decimal(2),
        )

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
        if baseline.current_price is None or baseline.current_price <= 0:
            raise PricingDomainError("SIN_BASELINE_CONFIABLE", "Missing current listing price.")
        context = self._simulation_context(
            account_id=request.account_id,
            category_id=baseline.category_id,
            listing_type_id=baseline.listing_type_id,
            currency_id=baseline.currency_id or "ARS",
            package=baseline.package,
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

        def evaluate(price: Decimal) -> EconomicResult:
            return self._evaluate(price, gross_cmv, additional_unit_cost_net, effective, context)

        analyzed = evaluate(seed_price)
        mc0 = self._optimizer.solve(evaluate, Decimal(0), seed_price)
        mc15 = self._optimizer.solve(evaluate, Decimal(15), seed_price)
        mc20 = self._optimizer.solve(evaluate, Decimal(20), seed_price)
        custom = (
            self._optimizer.solve(evaluate, target_margin_pct, seed_price)
            if target_margin_pct is not None
            else None
        )
        recommended_price = custom.gross_price if custom is not None else mc20.gross_price
        audit = PricingAudit(
            parameter_sources=effective.sources,
            overrides={key: value for key, value in overrides.items() if value is not None},
            marketplace_context={
                "category_id": context.category_id,
                "listing_type_id": context.listing_type_id,
                "currency_id": context.currency_id,
                "logistic_type": context.logistic_type or "",
                "shipping_mode": context.shipping_mode or "",
                "billable_weight": context.billable_weight,
            },
            analyzed_price=seed_price,
            scenario_units=1,
        )
        return PricingCalculationResponse(
            scenario=scenario,
            scenario_units=1,
            analyzed=analyzed,
            mc0=mc0,
            mc15=mc15,
            mc20=mc20,
            custom=custom,
            recommended_price=recommended_price,
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

    @staticmethod
    def _simulation_context(
        *,
        account_id: UUID | None,
        category_id: str,
        listing_type_id: str,
        currency_id: str,
        package: PackageInput | None,
    ) -> MarketplaceSimulationContext:
        if package is None or not package.dimensions or package.weight is None:
            raise PricingDomainError("SIN_DIMENSIONES", "Missing package dimensions or weight.")
        if account_id is None:
            raise PricingDomainError("SIN_PARAMETROS_ECONOMICOS", "Missing Mercado Libre account.")
        if not package.logistic_type or not package.shipping_mode:
            raise PricingDomainError("SIN_CONTEXTO_LOGISTICO", "Missing package logistics context.")
        return MarketplaceSimulationContext(
            account_id=account_id,
            site_id="MLA",
            category_id=category_id,
            listing_type_id=listing_type_id,
            currency_id=currency_id,
            logistic_type=package.logistic_type,
            shipping_mode=package.shipping_mode,
            billable_weight=package.weight,
        )

    @staticmethod
    def _require_gross_cmv(value: Decimal | None) -> None:
        if value is None:
            raise PricingDomainError("SIN_CMV", "Missing gross CMV.")

    @staticmethod
    def _require_text(value: str | None, code: str, name: str) -> None:
        if value is None or not value.strip():
            raise PricingDomainError(code, f"Missing {name}.")
