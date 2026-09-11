from dataclasses import replace
import json
import logging
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest

from app.integrations.mercadolibre.client import MercadoLibreClient, MercadoLibreError
from app.pricing.domain.errors import PricingDomainError
from app.pricing.domain.models import MarketplaceEconomics
from app.pricing.infrastructure import mercadolibre
from app.pricing.infrastructure.cache import PricingSimulationCache

FIXTURES_DIR = Path(__file__).parents[1] / "fixtures" / "ml"


class ListingPricesFixtureClient:
    def __init__(self, response: object, shipping_response: object | None = None) -> None:
        self.response = response
        self.shipping_response = shipping_response or load_fixture("shipping_quote.json")
        self.shipping_calls: list[dict[str, object]] = []
        self.listing_calls: list[dict[str, object]] = []

    def shipping_options_free(self, **context: object) -> object:
        self.shipping_calls.append(context)
        return self.shipping_response

    def listing_prices(self, **context: object) -> object:
        self.listing_calls.append(context)
        return self.response


class CountingListingPricesClient(ListingPricesFixtureClient):
    def __init__(self, response: object) -> None:
        super().__init__(response)
        self.calls = 0

    def listing_prices(self, **context: object) -> object:
        self.calls += 1
        return super().listing_prices(**context)


class ExistingListingFixtureClient(ListingPricesFixtureClient):
    def __init__(self, response: object, item: dict[str, object] | None = None) -> None:
        super().__init__(response)
        self._item = item

    def item(self, item_id: str) -> dict[str, object]:
        assert item_id == "MLA123"
        if self._item is not None:
            return self._item
        return {
            "id": item_id,
            "category_id": "MLA412517",
            "listing_type_id": "gold_special",
            "currency_id": "ARS",
            "condition": "new",
            "shipping": {
                "dimensions": "10x10x10,450",
                "logistic_type": "cross_docking",
                "mode": "me2",
                "free_shipping": False,
            },
        }

    def item_prices(self, item_id: str, *, show_all: bool = True) -> dict[str, object]:
        assert item_id == "MLA123"
        assert show_all is True
        return {
            "id": item_id,
            "prices": [
                {"type": "promotion", "amount": Decimal("15199.20"), "currency_id": "ARS"},
                {"type": "standard", "amount": Decimal("17745.05"), "currency_id": "ARS"},
            ],
        }


def load_fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


def simulation_context(listing_type_id: str = "gold_special") -> object:
    return mercadolibre.MarketplaceSimulationContext(
        account_id=uuid4(),
        site_id="MLA",
        category_id="MLA412517",
        listing_type_id=listing_type_id,
        currency_id="ARS",
        logistic_type="cross_docking",
        shipping_mode="me2",
        dimensions="10x10x10",
        package_weight_grams=Decimal(450),
        free_shipping=True,
    )


def complete_marketplace_economics() -> MarketplaceEconomics:
    return MarketplaceEconomics(
        percentage_fee=Decimal(16),
        meli_percentage_fee=Decimal(16),
        financing_add_on_fee=Decimal(0),
        fixed_fee=Decimal(2740),
        shipping_cost=Decimal(1200),
        shipping_subsidy=Decimal(0),
        buyer_shipping_amount=Decimal(0),
    )



def test_existing_listing_converts_marketplace_hwl_dimensions_back_to_internal_lwh() -> None:
    item = {
        "id": "MLA123",
        "category_id": "MLA412517",
        "listing_type_id": "gold_special",
        "currency_id": "ARS",
        "condition": "new",
        "shipping": {
            "dimensions": "10x20x30,450",
            "logistic_type": "cross_docking",
            "mode": "me2",
            "free_shipping": False,
        },
    }
    provider = mercadolibre.MercadoLibrePricingProvider(
        ExistingListingFixtureClient(load_fixture("listing_prices.json"), item),
        seller_id="244878077",
    )

    baseline = provider.resolve_existing_listing(account_id=uuid4(), item_id="MLA123")

    assert baseline.package is not None
    assert baseline.package.dimensions == "30x20x10"
    assert baseline.package.weight == Decimal("0.45")

def test_provider_reuses_a_complete_simulation_from_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Catches bypassing the cache before repeating the marketplace client request."""
    client = CountingListingPricesClient(load_fixture("listing_prices.json"))
    provider = mercadolibre.MercadoLibrePricingProvider(
        client, seller_id="244878077", cache=PricingSimulationCache(max_entries=8, ttl_seconds=60)
    )
    monkeypatch.setattr(provider, "parse_listing_prices", lambda *_args: complete_marketplace_economics())
    context = simulation_context()

    first = provider.simulate(context, Decimal(20000))
    second = provider.simulate(context, Decimal(20000))

    assert first == second
    assert client.calls == 1


def test_provider_cache_key_separates_currency_and_condition_contexts() -> None:
    """Catches unsafe cache reuse when Mercado Libre context changes without changing price."""
    context = simulation_context()
    price = Decimal(20000)

    base = mercadolibre.MercadoLibrePricingProvider._cache_key(context, price)
    other_currency = mercadolibre.MercadoLibrePricingProvider._cache_key(
        replace(context, currency_id="USD"), price
    )
    other_condition = mercadolibre.MercadoLibrePricingProvider._cache_key(
        replace(context, condition="used"), price
    )

    assert base != other_currency
    assert base != other_condition


def test_provider_does_not_reuse_a_simulation_with_a_different_price(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches a provider cache key that omits the gross price discriminator."""
    client = CountingListingPricesClient(load_fixture("listing_prices.json"))
    provider = mercadolibre.MercadoLibrePricingProvider(
        client, seller_id="244878077", cache=PricingSimulationCache(max_entries=8, ttl_seconds=60)
    )
    monkeypatch.setattr(provider, "parse_listing_prices", lambda *_args: complete_marketplace_economics())
    context = simulation_context()

    provider.simulate(context, Decimal(20000))
    provider.simulate(context, Decimal(25000))

    assert client.calls == 2


@pytest.fixture
def client() -> MercadoLibreClient:
    return object.__new__(MercadoLibreClient)


def test_shipping_options_free_sends_complete_prospective_context(
    client: MercadoLibreClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches omitting a field Mercado Libre uses to price prospective seller freight."""
    request_paths: list[str] = []
    response = load_fixture("shipping_quote.json")

    def fake_get(path: str, **_kwargs: object) -> dict[str, object]:
        request_paths.append(path)
        return response

    monkeypatch.setattr(client, "get", fake_get)

    result = client.shipping_options_free(
        seller_id="244878077",
        dimensions="10x10x10,450",
        item_price=Decimal("20000"),
        listing_type_id="gold_special",
        mode="me2",
        condition="new",
        logistic_type="cross_docking",
        free_shipping=True,
        category_id="MLA412517",
        currency_id="ARS",
    )

    assert result == response
    assert request_paths[0].startswith("/users/244878077/shipping_options/free?")
    assert parse_qs(urlsplit(request_paths[0]).query) == {
        "dimensions": ["10x10x10,450"],
        "verbose": ["true"],
        "item_price": ["20000"],
        "listing_type_id": ["gold_special"],
        "mode": ["me2"],
        "condition": ["new"],
        "logistic_type": ["cross_docking"],
        "free_shipping": ["true"],
        "category_id": ["MLA412517"],
        "currency_id": ["ARS"],
    }



def test_provider_formats_internal_lwh_dimensions_for_mercado_libre_shipping_contract() -> None:
    """Internal LxWxH centimeters must cross the ML boundary as HxWxL,whole_grams."""
    client = ListingPricesFixtureClient(load_fixture("listing_prices.json"))
    provider = mercadolibre.MercadoLibrePricingProvider(client, seller_id="244878077")
    context = replace(
        simulation_context(),
        dimensions="30x20x10",
        package_weight_grams=Decimal("450"),
    )

    provider.simulate(context, Decimal("20000"))

    assert client.shipping_calls[0]["dimensions"] == "10x20x30,450"


def test_provider_rounds_fractional_package_dimensions_up_at_ml_boundary() -> None:
    """Mercado Libre only accepts whole centimeters/grams for this contract."""
    client = ListingPricesFixtureClient(load_fixture("listing_prices.json"))
    provider = mercadolibre.MercadoLibrePricingProvider(client, seller_id="244878077")
    context = replace(
        simulation_context(),
        dimensions="30.2x20x10.1",
        package_weight_grams=Decimal("450.1"),
    )

    provider.simulate(context, Decimal("20000"))

    assert client.shipping_calls[0]["dimensions"] == "11x20x31,451"


def test_provider_rejects_invalid_internal_dimensions_before_calling_mercado_libre() -> None:
    client = ListingPricesFixtureClient(load_fixture("listing_prices.json"))
    provider = mercadolibre.MercadoLibrePricingProvider(client, seller_id="244878077")
    context = replace(simulation_context(), dimensions="30x20")

    with pytest.raises(PricingDomainError) as exc:
        provider.simulate(context, Decimal("20000"))

    assert exc.value.code == "SIN_DIMENSIONES"
    assert client.shipping_calls == []

def test_provider_uses_shipping_quote_billable_weight_and_economic_components() -> None:
    """Catches using physical weight as billable weight or losing the seller freight discount."""
    client = ListingPricesFixtureClient(load_fixture("listing_prices.json"))
    provider = mercadolibre.MercadoLibrePricingProvider(client, seller_id="244878077")

    result = provider.simulate(simulation_context(), Decimal("20000"))

    assert client.shipping_calls == [{
        "seller_id": "244878077",
        "dimensions": "10x10x10,450",
        "item_price": Decimal("20000"),
        "listing_type_id": "gold_special",
        "mode": "me2",
        "condition": "new",
        "logistic_type": "cross_docking",
        "free_shipping": True,
        "category_id": "MLA412517",
        "currency_id": "ARS",
    }]
    assert client.listing_calls[0]["billable_weight_grams"] == Decimal(5828)
    assert result.shipping_cost == Decimal(200)
    assert result.shipping_subsidy == Decimal(80)
    assert result.buyer_shipping_amount == Decimal(0)


def test_provider_rejects_shipping_quote_currency_mismatch() -> None:
    """Catches combining a freight quote denominated in another currency with ARS economics."""
    shipping = load_fixture("shipping_quote.json")
    shipping["coverage"]["all_country"]["currency_id"] = "USD"
    provider = mercadolibre.MercadoLibrePricingProvider(
        ListingPricesFixtureClient(load_fixture("listing_prices.json"), shipping),
        seller_id="244878077",
    )

    with pytest.raises(PricingDomainError) as exc:
        provider.simulate(simulation_context(), Decimal("20000"))

    assert exc.value.code == "SIN_CONTEXTO_LOGISTICO"


def test_listing_prices_sends_the_pricing_context_in_the_query(
    client: MercadoLibreClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches regressions that omit price or marketplace listing context."""
    request_paths: list[str] = []
    response = [{"listing_type_id": "gold_special", "sale_fee_amount": 3200}]

    def fake_get(path: str, **_kwargs: object) -> list[dict]:
        request_paths.append(path)
        return response

    monkeypatch.setattr(client, "get", fake_get)

    result = client.listing_prices(
        site_id="MLA",
        category_id="MLA412517",
        listing_type_id="gold_special",
        price=Decimal("20000"),  # noqa: FURB157 - contractual acceptance input
        currency_id="ARS",
        logistic_type="drop_off",
        shipping_mode="me2",
        billable_weight_grams=Decimal(450),
    )

    assert result == response
    assert request_paths[0].startswith("/sites/MLA/listing_prices?")
    assert "price=20000" in request_paths[0]
    assert parse_qs(urlsplit(request_paths[0]).query) == {
        "category_id": ["MLA412517"],
        "listing_type_id": ["gold_special"],
        "price": ["20000"],
        "currency_id": ["ARS"],
        "logistic_type": ["drop_off"],
        "shipping_mode": ["me2"],
        "billable_weight": ["450"],
    }


def test_item_rejects_a_non_mapping_response(
    client: MercadoLibreClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches accepting a malformed item-detail response as a usable item."""
    monkeypatch.setattr(client, "get", lambda _path: ["not", "an", "item"])

    with pytest.raises(MercadoLibreError, match="Unexpected item response"):
        client.item("MLA123")


def test_item_returns_the_item_mapping(client: MercadoLibreClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Catches using an item-detail path other than the requested item ID."""
    response = {"id": "MLA123", "price": 20000}
    request_paths: list[str] = []

    def fake_get(path: str) -> dict:
        request_paths.append(path)
        return response

    monkeypatch.setattr(client, "get", fake_get)

    assert client.item("MLA123") == response
    assert request_paths == ["/items/MLA123"]


def test_provider_maps_listing_fee_details_without_losing_components() -> None:
    """Catches collapsing independently reported Mercado Libre fee components."""
    provider = mercadolibre.MercadoLibrePricingProvider(
        ListingPricesFixtureClient(load_fixture("listing_prices.json"))
    )

    result = provider.parse_listing_prices(load_fixture("listing_prices.json"), "gold_special")

    assert result.percentage_fee == Decimal(16)
    assert result.meli_percentage_fee == Decimal(16)
    assert result.financing_add_on_fee == Decimal(0)
    assert result.fixed_fee == Decimal(2740)


def test_provider_accepts_decimal_fee_values_from_json_numbers() -> None:
    """Mercado Libre may return percentage fees as JSON floating-point numbers."""
    response = load_fixture("listing_prices.json")
    details = response["sale_fee_details"]
    assert isinstance(details, dict)
    details["percentage_fee"] = 15.5
    details["meli_percentage_fee"] = 15.5
    provider = mercadolibre.MercadoLibrePricingProvider(ListingPricesFixtureClient(response))

    result = provider.parse_listing_prices(response, "gold_special")

    assert result.percentage_fee == Decimal("15.5")
    assert result.meli_percentage_fee == Decimal("15.5")


def test_provider_maps_a_list_listing_prices_response_for_the_requested_listing_type() -> None:
    """Catches assuming that Mercado Libre always returns a mapping for listing prices."""
    provider = mercadolibre.MercadoLibrePricingProvider(
        ListingPricesFixtureClient(load_fixture("listing_prices.json"))
    )

    result = provider.parse_listing_prices([load_fixture("listing_prices.json")], "gold_special")

    assert result.percentage_fee == Decimal(16)


@pytest.mark.parametrize(
    "missing_field",
    ("percentage_fee", "meli_percentage_fee", "financing_add_on_fee", "fixed_fee"),
)
def test_provider_rejects_a_missing_listing_fee_component(missing_field: str) -> None:
    """Catches treating a contractually absent Mercado Libre fee as an economic zero."""
    response = load_fixture("listing_prices.json")
    details = response["sale_fee_details"]
    assert isinstance(details, dict)
    details.pop(missing_field)
    provider = mercadolibre.MercadoLibrePricingProvider(ListingPricesFixtureClient(response))

    with pytest.raises(PricingDomainError) as exc:
        provider.parse_listing_prices(response, "gold_special")

    assert exc.value.code == "SIN_TARIFA_ML"


def test_provider_logs_the_exact_later_optimizer_probe_with_an_incomplete_fee(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Catches losing the price and probe index of the ML response that lacks percentage_fee."""
    response = load_fixture("listing_prices.json")
    details = response["sale_fee_details"]
    assert isinstance(details, dict)
    details.pop("percentage_fee")
    context = mercadolibre.MarketplaceSimulationContext(
        account_id=uuid4(),
        site_id="MLA",
        category_id="MLA376317",
        listing_type_id="gold_special",
        currency_id="ARS",
        logistic_type="self_service",
        shipping_mode="me2",
        dimensions="10x10x10",
        package_weight_grams=Decimal(1000),
        free_shipping=False,
        probe_index=7,
    )
    provider = mercadolibre.MercadoLibrePricingProvider(
        ListingPricesFixtureClient([response]), seller_id="244878077"
    )

    caplog.set_level(logging.DEBUG, logger="uvicorn.error")
    with pytest.raises(PricingDomainError, match="percentage_fee"):
        provider.simulate(context, Decimal(46081))

    record = next(record for record in caplog.records if record.name == "uvicorn.error")
    assert '"probe_index": 7' in record.getMessage()
    assert '"price": "46081"' in record.getMessage()
    assert '"percentage_fee": null' in record.getMessage()
    assert '"candidate_count": 1' in record.getMessage()
    assert record.levelno == logging.DEBUG


def test_provider_raises_sin_tarifa_ml_when_response_has_no_matching_listing_type() -> None:
    """Catches accepting a tariff response for a listing type other than the simulated one."""
    provider = mercadolibre.MercadoLibrePricingProvider(
        ListingPricesFixtureClient(load_fixture("listing_prices.json")),
        seller_id="244878077",
    )

    with pytest.raises(PricingDomainError) as exc:
        provider.simulate(simulation_context("gold_pro"), Decimal("17745.05"))

    assert exc.value.code == "SIN_TARIFA_ML"


def test_provider_rejects_unavailable_prospective_logistics_without_zero_shipping_cost() -> None:
    """Catches silently treating unavailable freight quotation data as free shipping."""
    provider = mercadolibre.MercadoLibrePricingProvider(
        ListingPricesFixtureClient(load_fixture("listing_prices.json"))
    )

    with pytest.raises(PricingDomainError) as exc:
        provider.simulate(simulation_context(), Decimal("17745.05"))

    assert exc.value.code == "SIN_CONTEXTO_LOGISTICO"


def test_provider_resolves_existing_listing_from_item_and_standard_item_price() -> None:
    """Catches calculator baselines that bypass the confirmed item and item-prices transport."""
    provider = mercadolibre.MercadoLibrePricingProvider(
        ExistingListingFixtureClient(load_fixture("listing_prices.json"))
    )

    baseline = provider.resolve_existing_listing(account_id=uuid4(), item_id="MLA123")

    assert baseline.category_id == "MLA412517"
    assert baseline.listing_type_id == "gold_special"
    assert baseline.current_price == Decimal("17745.05")
    assert baseline.currency_id == "ARS"
    assert baseline.condition == "new"
    assert baseline.package.dimensions == "10x10x10"
    assert baseline.package.free_shipping is False


def test_provider_resolves_existing_listing_package_from_seller_package_attributes() -> None:
    """Catches rejecting an item whose reliable package data is exposed as ML attributes."""
    item = load_fixture("item_detail.json")
    item["id"] = "MLA123"
    provider = mercadolibre.MercadoLibrePricingProvider(
        ExistingListingFixtureClient(load_fixture("listing_prices.json"), item)
    )

    baseline = provider.resolve_existing_listing(account_id=uuid4(), item_id="MLA123")

    assert baseline.package.dimensions == "31x25x6"
    assert baseline.package.weight == Decimal("0.214")


class FailingShippingClient(ListingPricesFixtureClient):
    def shipping_options_free(self, **context: object) -> object:
        raise MercadoLibreError(
            "Mercado Libre HTTP 404",
            404,
            {"message": "shipping option not found", "error": "not_found"},
        )


def test_provider_maps_shipping_http_error_to_domain_error() -> None:
    provider = mercadolibre.MercadoLibrePricingProvider(
        FailingShippingClient(load_fixture("listing_prices.json")),
        seller_id="244878077",
    )

    with pytest.raises(PricingDomainError) as exc_info:
        provider.simulate(simulation_context(), Decimal("20000"))

    assert exc_info.value.code == "SIN_CONTEXTO_LOGISTICO"
    assert "shipping option not found" in str(exc_info.value)
