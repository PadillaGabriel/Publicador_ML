"""Mercado Libre adapter for pricing simulations."""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from app.pricing.domain.errors import PricingDomainError
from app.pricing.domain.models import MarketplaceEconomics
from app.pricing.infrastructure.cache import PricingCacheKey, PricingSimulationCache
from app.pricing.schemas import PackageInput


class ListingPricesClient(Protocol):
    def listing_prices(
        self,
        *,
        site_id: str,
        category_id: str,
        listing_type_id: str,
        price: Decimal,
        currency_id: str,
        logistic_type: str | None = None,
        shipping_mode: str | None = None,
    ) -> object: ...

    def item(self, item_id: str) -> dict: ...

    def item_prices(self, item_id: str, *, show_all: bool = True) -> dict: ...


@dataclass(frozen=True, slots=True)
class MarketplaceSimulationContext:
    account_id: UUID
    site_id: str
    category_id: str
    listing_type_id: str
    currency_id: str
    logistic_type: str | None
    shipping_mode: str | None
    billable_weight: Decimal


@dataclass(frozen=True, slots=True)
class ExistingListingContext:
    category_id: str | None
    listing_type_id: str | None
    current_price: Decimal | None
    currency_id: str | None
    package: PackageInput | None


class MercadoLibrePricingProvider:
    def __init__(
        self,
        client: ListingPricesClient,
        *,
        cache: PricingSimulationCache | None = None,
    ) -> None:
        self._client = client
        self._cache = cache

    def resolve_existing_listing(
        self, *, account_id: UUID, item_id: str
    ) -> ExistingListingContext:
        del account_id  # The account is carried by the application simulation context.
        item = self._client.item(item_id)
        prices = self._client.item_prices(item_id, show_all=True)
        if not isinstance(item, Mapping) or not isinstance(prices, Mapping):
            raise PricingDomainError("SIN_BASELINE_CONFIABLE", "Invalid existing listing baseline.")
        shipping = item.get("shipping")
        if not isinstance(shipping, Mapping):
            raise PricingDomainError("SIN_DIMENSIONES", "Missing existing listing shipping context.")
        dimensions = self._text(shipping.get("dimensions"))
        package = PackageInput(
            dimensions=dimensions,
            weight=self._weight_from_dimensions(dimensions),
            logistic_type=self._text(shipping.get("logistic_type")),
            shipping_mode=self._text(shipping.get("mode")),
        )
        return ExistingListingContext(
            category_id=self._text(item.get("category_id")),
            listing_type_id=self._text(item.get("listing_type_id")),
            current_price=self._standard_price(prices),
            currency_id=self._text(item.get("currency_id")),
            package=package,
        )

    def simulate(
        self,
        context: MarketplaceSimulationContext,
        gross_price: Decimal,
    ) -> MarketplaceEconomics:
        cache_key: PricingCacheKey | None = None
        if self._cache is not None:
            cache_key = self._cache_key(context, gross_price)
            cached = self._cache.get(cache_key)
            if cached is not None:
                return cached

        response = self._client.listing_prices(
            site_id=context.site_id,
            category_id=context.category_id,
            listing_type_id=context.listing_type_id,
            price=gross_price,
            currency_id=context.currency_id,
            logistic_type=context.logistic_type,
            shipping_mode=context.shipping_mode,
        )
        economics = self.parse_listing_prices(response, context.listing_type_id)
        if self._cache is not None and cache_key is not None and self._cache.put(cache_key, economics):
            return economics
        raise PricingDomainError(
            "SIN_CONTEXTO_LOGISTICO",
            "Prospective logistics pricing is unavailable for this Mercado Libre context.",
        )

    @staticmethod
    def _cache_key(
        context: MarketplaceSimulationContext,
        gross_price: Decimal,
    ) -> PricingCacheKey:
        if context.logistic_type is None or context.shipping_mode is None:
            raise PricingDomainError(
                "SIN_CONTEXTO_LOGISTICO",
                "Prospective logistics pricing is unavailable for this Mercado Libre context.",
            )
        return PricingCacheKey(
            account_id=context.account_id,
            category_or_item_id=context.category_id,
            listing_type_id=context.listing_type_id,
            gross_price=gross_price,
            logistic_type=context.logistic_type,
            shipping_mode=context.shipping_mode,
            billable_weight=context.billable_weight,
        )

    def parse_listing_prices(
        self,
        response: object,
        listing_type_id: str,
    ) -> MarketplaceEconomics:
        if not isinstance(response, Mapping) or response.get("listing_type_id") != listing_type_id:
            raise PricingDomainError(
                "SIN_TARIFA_ML",
                "Missing Mercado Libre tariff for the requested listing type.",
            )

        details = response.get("sale_fee_details")
        if not isinstance(details, Mapping):
            raise PricingDomainError("SIN_TARIFA_ML", "Missing Mercado Libre sale fee details.")

        return MarketplaceEconomics(
            percentage_fee=self._fee(details, "percentage_fee"),
            meli_percentage_fee=self._fee(details, "meli_percentage_fee"),
            financing_add_on_fee=self._fee(details, "financing_add_on_fee"),
            fixed_fee=self._fee(details, "fixed_fee"),
            shipping_cost=None,
            shipping_subsidy=None,
            buyer_shipping_amount=None,
        )

    @staticmethod
    def _standard_price(prices: Mapping[object, object]) -> Decimal:
        entries = prices.get("prices")
        if not isinstance(entries, list):
            raise PricingDomainError("SIN_BASELINE_CONFIABLE", "Missing existing listing prices.")
        for entry in entries:
            if not isinstance(entry, Mapping) or entry.get("type") != "standard":
                continue
            amount = entry.get("amount")
            if isinstance(amount, bool) or not isinstance(amount, (str, int, float, Decimal)):
                break
            try:
                price = Decimal(str(amount))
            except ArithmeticError as exc:
                raise PricingDomainError("SIN_BASELINE_CONFIABLE", "Invalid standard listing price.") from exc
            if price > 0:
                return price
            break
        raise PricingDomainError("SIN_BASELINE_CONFIABLE", "Missing standard listing price.")

    @staticmethod
    def _weight_from_dimensions(dimensions: str | None) -> Decimal | None:
        if not dimensions:
            return None
        try:
            grams = Decimal(dimensions.rsplit(",", maxsplit=1)[1].strip())
        except (ArithmeticError, IndexError):
            return None
        return grams / Decimal(1000) if grams > 0 else None

    @staticmethod
    def _text(value: object) -> str | None:
        return value.strip() if isinstance(value, str) and value.strip() else None

    @staticmethod
    def _fee(details: Mapping[object, object], field: str) -> Decimal:
        value = details.get(field)
        if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
            raise PricingDomainError("SIN_TARIFA_ML", f"Missing Mercado Libre {field}.")
        try:
            return Decimal(value)
        except ArithmeticError as exc:
            raise PricingDomainError("SIN_TARIFA_ML", f"Invalid Mercado Libre {field}.") from exc
