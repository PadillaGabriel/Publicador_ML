"""Mercado Libre adapter for pricing simulations."""

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING
from typing import Protocol
from uuid import UUID

from app.integrations.mercadolibre.client import MercadoLibreError
from app.pricing.domain.errors import PricingDomainError
from app.pricing.domain.models import MarketplaceEconomics
from app.pricing.infrastructure.cache import PricingCacheKey, PricingSimulationCache
from app.pricing.schemas import PackageInput

logger = logging.getLogger("uvicorn.error")


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
        billable_weight_grams: Decimal | None = None,
    ) -> object: ...

    def shipping_options_free(
        self,
        *,
        seller_id: str,
        dimensions: str,
        item_price: Decimal,
        listing_type_id: str,
        mode: str,
        condition: str,
        logistic_type: str,
        free_shipping: bool,
        category_id: str,
        currency_id: str,
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
    dimensions: str
    package_weight_grams: Decimal
    free_shipping: bool
    condition: str = "new"
    probe_index: int | None = None




@dataclass(frozen=True, slots=True)
class ProspectiveShippingQuote:
    gross_cost: Decimal
    subsidy: Decimal
    billable_weight: Decimal


@dataclass(frozen=True, slots=True)
class ExistingListingContext:
    category_id: str | None
    listing_type_id: str | None
    current_price: Decimal | None
    currency_id: str | None
    condition: str | None
    package: PackageInput | None


class MercadoLibrePricingProvider:
    def __init__(
        self,
        client: ListingPricesClient,
        *,
        seller_id: str | None = None,
        cache: PricingSimulationCache | None = None,
    ) -> None:
        self._client = client
        self._seller_id = seller_id.strip() if seller_id and seller_id.strip() else None
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
        shipping = shipping if isinstance(shipping, Mapping) else {}
        raw_dimensions = self._text(shipping.get("dimensions"))
        weight = self._weight_from_dimensions(raw_dimensions)
        dimensions = self._dimensions_without_weight(raw_dimensions)
        attribute_dimensions, attribute_weight = self._seller_package(item.get("attributes"))
        dimensions = dimensions or attribute_dimensions
        weight = weight or attribute_weight
        package = PackageInput(
            dimensions=dimensions,
            weight=weight,
            logistic_type=self._text(shipping.get("logistic_type")),
            shipping_mode=self._text(shipping.get("mode")),
            free_shipping=self._boolean(shipping.get("free_shipping")),
        )
        return ExistingListingContext(
            category_id=self._text(item.get("category_id")),
            listing_type_id=self._text(item.get("listing_type_id")),
            current_price=self._standard_price(prices),
            currency_id=self._text(item.get("currency_id")),
            condition=self._text(item.get("condition")),
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

        shipping_quote = self._shipping_quote(context, gross_price)
        response = self._client.listing_prices(
            site_id=context.site_id,
            category_id=context.category_id,
            listing_type_id=context.listing_type_id,
            price=gross_price,
            currency_id=context.currency_id,
            logistic_type=context.logistic_type,
            shipping_mode=context.shipping_mode,
            billable_weight_grams=shipping_quote.billable_weight,
        )
        logger.debug(
            "pricing_listing_prices_probe=%s",
            json.dumps(
                self._probe_diagnostic(
                    context, gross_price, response, shipping_quote.billable_weight
                ),
                sort_keys=True,
            ),
        )
        fees = self.parse_listing_prices(response, context.listing_type_id)
        economics = MarketplaceEconomics(
            percentage_fee=fees.percentage_fee,
            meli_percentage_fee=fees.meli_percentage_fee,
            financing_add_on_fee=fees.financing_add_on_fee,
            fixed_fee=fees.fixed_fee,
            shipping_cost=shipping_quote.gross_cost,
            shipping_subsidy=shipping_quote.subsidy,
            # The seller quote is already conditioned by free_shipping. Buyer freight is not
            # separate seller income in this prospective seller-cost calculation.
            buyer_shipping_amount=Decimal(0),
        )
        if self._cache is not None and cache_key is not None:
            self._cache.put(cache_key, economics)
        return economics

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
            site_id=context.site_id,
            category_or_item_id=context.category_id,
            listing_type_id=context.listing_type_id,
            currency_id=context.currency_id,
            condition=context.condition,
            gross_price=gross_price,
            logistic_type=context.logistic_type,
            shipping_mode=context.shipping_mode,
            dimensions=context.dimensions,
            package_weight_grams=context.package_weight_grams,
            free_shipping=context.free_shipping,
        )

    def _shipping_quote(
        self,
        context: MarketplaceSimulationContext,
        gross_price: Decimal,
    ) -> ProspectiveShippingQuote:
        if self._seller_id is None or context.logistic_type is None or context.shipping_mode is None:
            raise PricingDomainError(
                "SIN_CONTEXTO_LOGISTICO",
                "Prospective logistics pricing is unavailable for this Mercado Libre context.",
            )
        try:
            response = self._client.shipping_options_free(
                seller_id=self._seller_id,
                dimensions=self._marketplace_dimensions(
                    context.dimensions, context.package_weight_grams
                ),
                item_price=gross_price,
                listing_type_id=context.listing_type_id,
                mode=context.shipping_mode,
                condition=context.condition,
                logistic_type=context.logistic_type,
                free_shipping=context.free_shipping,
                category_id=context.category_id,
                currency_id=context.currency_id,
            )
        except MercadoLibreError as exc:
            message = self._marketplace_error_message(exc)
            raise PricingDomainError(
                "SIN_CONTEXTO_LOGISTICO",
                f"Mercado Libre no pudo cotizar el envío prospectivo: {message}",
            ) from exc
        if not isinstance(response, Mapping):
            raise PricingDomainError("SIN_CONTEXTO_LOGISTICO", "Invalid Mercado Libre shipping quote.")
        coverage = response.get("coverage")
        if not isinstance(coverage, Mapping):
            raise PricingDomainError("SIN_CONTEXTO_LOGISTICO", "Missing Mercado Libre shipping coverage.")
        all_country = coverage.get("all_country")
        if not isinstance(all_country, Mapping):
            raise PricingDomainError("SIN_CONTEXTO_LOGISTICO", "Missing Mercado Libre nationwide shipping quote.")
        currency_id = self._text(all_country.get("currency_id"))
        if currency_id != context.currency_id:
            raise PricingDomainError("SIN_CONTEXTO_LOGISTICO", "Mercado Libre shipping quote currency mismatch.")
        final_cost = self._non_negative_decimal(
            all_country.get("list_cost"), "Mercado Libre seller shipping cost"
        )
        billable_weight = self._positive_decimal(
            all_country.get("billable_weight"), "Mercado Libre billable weight"
        )
        discount = all_country.get("discount")
        if not isinstance(discount, Mapping):
            discount = coverage.get("discount")
        gross_cost = final_cost
        subsidy = Decimal(0)
        if isinstance(discount, Mapping):
            rate = self._non_negative_decimal(
                discount.get("rate", 0), "Mercado Libre shipping discount rate"
            )
            promoted_amount = self._non_negative_decimal(
                discount.get("promoted_amount", 0),
                "Mercado Libre shipping promoted amount",
            )
            if rate > 0:
                if promoted_amount <= 0 or promoted_amount < final_cost:
                    raise PricingDomainError(
                        "SIN_CONTEXTO_LOGISTICO",
                        "Inconsistent Mercado Libre shipping discount.",
                    )
                gross_cost = promoted_amount
                subsidy = promoted_amount - final_cost
        return ProspectiveShippingQuote(
            gross_cost=gross_cost,
            subsidy=subsidy,
            billable_weight=billable_weight,
        )

    def parse_listing_prices(
        self,
        response: object,
        listing_type_id: str,
    ) -> MarketplaceEconomics:
        candidates = self._listing_price_candidates(response)
        matching = next(
            (
                candidate
                for candidate in candidates
                if isinstance(candidate, Mapping)
                and candidate.get("listing_type_id") == listing_type_id
            ),
            None,
        )
        if not isinstance(matching, Mapping):
            raise PricingDomainError(
                "SIN_TARIFA_ML",
                "Missing Mercado Libre tariff for the requested listing type.",
            )

        details = matching.get("sale_fee_details")
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
    def _listing_price_candidates(response: object) -> list[object]:
        if isinstance(response, Mapping):
            return [response]
        if isinstance(response, list):
            return response
        raise PricingDomainError("SIN_TARIFA_ML", "Invalid Mercado Libre listing prices response.")

    @classmethod
    def _probe_diagnostic(
        cls,
        context: MarketplaceSimulationContext,
        gross_price: Decimal,
        response: object,
        billable_weight: Decimal,
    ) -> dict[str, object]:
        try:
            candidates = cls._listing_price_candidates(response)
        except PricingDomainError:
            candidates = []
        matching = next(
            (
                candidate
                for candidate in candidates
                if isinstance(candidate, Mapping)
                and candidate.get("listing_type_id") == context.listing_type_id
            ),
            None,
        )
        details = matching.get("sale_fee_details") if isinstance(matching, Mapping) else None
        return {
            "probe_index": context.probe_index,
            "price": str(gross_price),
            "category_id": context.category_id,
            "listing_type_id": context.listing_type_id,
            "logistic_type": context.logistic_type,
            "shipping_mode": context.shipping_mode,
            "billable_weight": str(billable_weight),
            "free_shipping": context.free_shipping,
            "response_type": type(response).__name__,
            "candidate_count": len(candidates),
            "matching_listing_type_found": matching is not None,
            "sale_fee_details_keys": (
                sorted(str(key) for key in details) if isinstance(details, Mapping) else []
            ),
            "percentage_fee": details.get("percentage_fee") if isinstance(details, Mapping) else None,
            "meli_percentage_fee": (
                details.get("meli_percentage_fee") if isinstance(details, Mapping) else None
            ),
            "financing_add_on_fee": (
                details.get("financing_add_on_fee") if isinstance(details, Mapping) else None
            ),
            "fixed_fee": details.get("fixed_fee") if isinstance(details, Mapping) else None,
        }

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

    @classmethod
    def _marketplace_dimensions(cls, dimensions: str, weight_grams: Decimal) -> str:
        """Convert internal LxWxH centimeters to Mercado Libre HxWxL,grams."""
        normalized = dimensions.replace("×", "x").replace("X", "x")
        raw_parts = [part.strip() for part in normalized.split("x")]
        if len(raw_parts) != 3 or any(not part for part in raw_parts):
            raise PricingDomainError(
                "SIN_DIMENSIONES",
                "Las dimensiones deben tener formato Largo×Ancho×Alto en centímetros.",
            )

        parsed: list[Decimal] = []
        for raw in raw_parts:
            try:
                value = Decimal(raw.replace(",", "."))
            except ArithmeticError as exc:
                raise PricingDomainError(
                    "SIN_DIMENSIONES",
                    "Las dimensiones deben ser valores numéricos en centímetros.",
                ) from exc
            if not value.is_finite() or value <= 0:
                raise PricingDomainError(
                    "SIN_DIMENSIONES",
                    "Las dimensiones deben ser mayores que cero.",
                )
            parsed.append(value.to_integral_value(rounding=ROUND_CEILING))

        if not weight_grams.is_finite() or weight_grams <= 0:
            raise PricingDomainError(
                "SIN_DIMENSIONES",
                "El peso del paquete debe ser mayor que cero.",
            )
        whole_grams = weight_grams.to_integral_value(rounding=ROUND_CEILING)
        length, width, height = parsed
        return (
            f"{cls._decimal_text(height)}x{cls._decimal_text(width)}x"
            f"{cls._decimal_text(length)},{cls._decimal_text(whole_grams)}"
        )

    @staticmethod
    def _weight_from_dimensions(dimensions: str | None) -> Decimal | None:
        if not dimensions:
            return None
        try:
            grams = Decimal(dimensions.rsplit(",", maxsplit=1)[1].strip())
        except (ArithmeticError, IndexError):
            return None
        return grams / Decimal(1000) if grams > 0 else None

    @classmethod
    def _seller_package(cls, attributes: object) -> tuple[str | None, Decimal | None]:
        if not isinstance(attributes, list):
            return None, None
        expected_units = {
            "SELLER_PACKAGE_HEIGHT": "cm",
            "SELLER_PACKAGE_WIDTH": "cm",
            "SELLER_PACKAGE_LENGTH": "cm",
            "SELLER_PACKAGE_WEIGHT": "g",
        }
        values: dict[str, Decimal] = {}
        for attribute in attributes:
            if not isinstance(attribute, Mapping):
                continue
            attribute_id = cls._text(attribute.get("id"))
            expected_unit = expected_units.get(attribute_id or "")
            if expected_unit is None:
                continue
            value = cls._measurement(attribute, expected_unit)
            if value is not None and value > 0:
                values[attribute_id] = value

        dimensions = (
            "x".join(
                cls._decimal_text(values[attribute_id])
                for attribute_id in (
                    "SELLER_PACKAGE_LENGTH",
                    "SELLER_PACKAGE_WIDTH",
                    "SELLER_PACKAGE_HEIGHT",
                )
            )
            if all(
                attribute_id in values
                for attribute_id in (
                    "SELLER_PACKAGE_HEIGHT",
                    "SELLER_PACKAGE_WIDTH",
                    "SELLER_PACKAGE_LENGTH",
                )
            )
            else None
        )
        weight = values.get("SELLER_PACKAGE_WEIGHT")
        return dimensions, weight / Decimal(1000) if weight is not None else None

    @classmethod
    def _measurement(cls, attribute: Mapping[object, object], expected_unit: str) -> Decimal | None:
        value_struct = attribute.get("value_struct")
        if isinstance(value_struct, Mapping):
            unit = cls._text(value_struct.get("unit"))
            value = value_struct.get("number")
            if unit == expected_unit and isinstance(value, (str, int, float, Decimal)) and not isinstance(value, bool):
                try:
                    return Decimal(str(value))
                except ArithmeticError:
                    return None
        value_name = cls._text(attribute.get("value_name"))
        if value_name is None:
            return None
        number, separator, unit = value_name.partition(" ")
        if not separator or unit.strip() != expected_unit:
            return None
        try:
            return Decimal(number)
        except ArithmeticError:
            return None

    @staticmethod
    def _dimensions_without_weight(dimensions: str | None) -> str | None:
        if dimensions is None:
            return None
        geometry = dimensions.split(",", maxsplit=1)[0].strip()
        parts = [part.strip() for part in geometry.replace("×", "x").replace("X", "x").split("x")]
        if len(parts) != 3 or any(not part for part in parts):
            return geometry or None
        height, width, length = parts
        return f"{length}x{width}x{height}"

    @staticmethod
    def _boolean(value: object) -> bool | None:
        return value if isinstance(value, bool) else None

    @staticmethod
    def _non_negative_decimal(value: object, name: str) -> Decimal:
        if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
            raise PricingDomainError("SIN_CONTEXTO_LOGISTICO", f"Missing {name}.")
        try:
            result = Decimal(str(value))
        except ArithmeticError as exc:
            raise PricingDomainError("SIN_CONTEXTO_LOGISTICO", f"Invalid {name}.") from exc
        if not result.is_finite() or result < 0:
            raise PricingDomainError("SIN_CONTEXTO_LOGISTICO", f"Invalid {name}.")
        return result

    @classmethod
    def _positive_decimal(cls, value: object, name: str) -> Decimal:
        result = cls._non_negative_decimal(value, name)
        if result <= 0:
            raise PricingDomainError("SIN_CONTEXTO_LOGISTICO", f"Invalid {name}.")
        return result

    @staticmethod
    def _marketplace_error_message(exc: MercadoLibreError) -> str:
        for key in ("message", "error", "cause"):
            value = exc.payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return str(exc)

    @staticmethod
    def _decimal_text(value: Decimal) -> str:
        return format(value.normalize(), "f")

    @staticmethod
    def _text(value: object) -> str | None:
        return value.strip() if isinstance(value, str) and value.strip() else None

    @staticmethod
    def _fee(details: Mapping[object, object], field: str) -> Decimal:
        value = details.get(field)
        if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
            raise PricingDomainError("SIN_TARIFA_ML", f"Missing Mercado Libre {field}.")
        try:
            return Decimal(str(value))
        except ArithmeticError as exc:
            raise PricingDomainError("SIN_TARIFA_ML", f"Invalid Mercado Libre {field}.") from exc
