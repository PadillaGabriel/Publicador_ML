import json
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from app.integrations.mercadolibre.client import MercadoLibreClient, MercadoLibreError
from app.pricing.domain.errors import PricingDomainError
from app.pricing.infrastructure import mercadolibre

FIXTURES_DIR = Path(__file__).parents[1] / "fixtures" / "ml"


class ListingPricesFixtureClient:
    def __init__(self, response: object) -> None:
        self.response = response

    def listing_prices(self, **_context: object) -> object:
        return self.response


def load_fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


def simulation_context(listing_type_id: str = "gold_special") -> object:
    return mercadolibre.MarketplaceSimulationContext(
        site_id="MLA",
        category_id="MLA412517",
        listing_type_id=listing_type_id,
        currency_id="ARS",
        logistic_type="cross_docking",
        shipping_mode="me2",
    )


@pytest.fixture
def client() -> MercadoLibreClient:
    return object.__new__(MercadoLibreClient)


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


def test_provider_raises_sin_tarifa_ml_when_response_has_no_matching_listing_type() -> None:
    """Catches accepting a tariff response for a listing type other than the simulated one."""
    provider = mercadolibre.MercadoLibrePricingProvider(
        ListingPricesFixtureClient(load_fixture("listing_prices.json"))
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
