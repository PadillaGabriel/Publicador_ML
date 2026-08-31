from decimal import Decimal
from urllib.parse import parse_qs, urlsplit

import pytest

from app.integrations.mercadolibre.client import MercadoLibreClient, MercadoLibreError


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
    """Catches dropping fields from the item-detail response."""
    response = {"id": "MLA123", "price": 20000}
    monkeypatch.setattr(client, "get", lambda _path: response)

    assert client.item("MLA123") == response
