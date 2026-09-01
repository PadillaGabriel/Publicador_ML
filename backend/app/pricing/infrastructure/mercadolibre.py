"""Mercado Libre adapter for pricing simulations."""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from app.pricing.domain.errors import PricingDomainError
from app.pricing.domain.models import MarketplaceEconomics


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


@dataclass(frozen=True, slots=True)
class MarketplaceSimulationContext:
    site_id: str
    category_id: str
    listing_type_id: str
    currency_id: str
    logistic_type: str | None
    shipping_mode: str | None


class MercadoLibrePricingProvider:
    def __init__(self, client: ListingPricesClient) -> None:
        self._client = client

    def simulate(
        self,
        context: MarketplaceSimulationContext,
        gross_price: Decimal,
    ) -> MarketplaceEconomics:
        response = self._client.listing_prices(
            site_id=context.site_id,
            category_id=context.category_id,
            listing_type_id=context.listing_type_id,
            price=gross_price,
            currency_id=context.currency_id,
            logistic_type=context.logistic_type,
            shipping_mode=context.shipping_mode,
        )
        self.parse_listing_prices(response, context.listing_type_id)
        raise PricingDomainError(
            "SIN_CONTEXTO_LOGISTICO",
            "Prospective logistics pricing is unavailable for this Mercado Libre context.",
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
    def _fee(details: Mapping[object, object], field: str) -> Decimal:
        value = details.get(field)
        if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
            raise PricingDomainError("SIN_TARIFA_ML", f"Missing Mercado Libre {field}.")
        try:
            return Decimal(value)
        except ArithmeticError as exc:
            raise PricingDomainError("SIN_TARIFA_ML", f"Invalid Mercado Libre {field}.") from exc
