from datetime import datetime, timezone
from types import SimpleNamespace

from app.core.spreadsheet import excel_safe_value
from app.publication.payload import attribute_payload, build_item_payload
from app.integrations.mercadolibre.product_identifiers import (
    attribute_has_value,
    is_valid_identifier_format,
    normalized_identifier_value,
    value_matches_allowed_option,
)


def test_zero_product_identifier_is_treated_as_absent():
    assert normalized_identifier_value(0) is None
    assert normalized_identifier_value("0") is None
    assert attribute_payload({"GTIN": 0, "BRAND": "Marca"}) == [
        {"id": "BRAND", "value_name": "Marca"}
    ]


def test_obviously_invalid_product_identifier_is_rejected_locally():
    assert not is_valid_identifier_format("ABC123")
    assert is_valid_identifier_format("7791234567890")


def test_payload_includes_pickup_and_seller_warranty_contract():
    version = SimpleNamespace(
        title_reference="Producto",
        category_id="MLA1",
        price=1000,
        currency_id="ARS",
        quantity=1,
        commercial={
            "buying_mode": "buy_it_now",
            "warranty": {"type": "SELLER", "duration": 30, "unit": "days"},
        },
        logistics={
            "local_pick_up": True,
            "pricing_package": {
                "logistic_type": "drop_off",
                "shipping_mode": "me2",
                "free_shipping": False,
            },
        },
        condition="new",
        attributes={},
    )
    draft = SimpleNamespace(
        title="Producto prueba",
        commercial_config={"listing_type_id": "gold_special"},
    )

    payload = build_item_payload(
        version,
        draft,
        ["https://example.test/image.jpg"],
        seller_sku="SKU-TEST-001",
    )

    assert payload["shipping"] == {
        "mode": "me2",
        "logistic_type": "drop_off",
        "local_pick_up": True,
        "free_shipping": False,
    }
    assert payload["sale_terms"] == [
        {"id": "WARRANTY_TYPE", "value_name": "Garantía del vendedor"},
        {"id": "WARRANTY_TIME", "value_name": "30 días"},
    ]




def test_payload_requires_and_normalizes_seller_sku():
    version = SimpleNamespace(
        title_reference="Producto",
        category_id="MLA1",
        price=1000,
        currency_id="ARS",
        quantity=1,
        commercial={"buying_mode": "buy_it_now"},
        logistics={},
        condition="new",
        attributes={},
    )
    draft = SimpleNamespace(
        title="Producto prueba",
        commercial_config={"listing_type_id": "gold_special"},
    )

    payload = build_item_payload(
        version,
        draft,
        ["https://example.test/image.jpg"],
        seller_sku="  SKU-123  ",
    )

    assert payload["seller_custom_field"] == "SKU-123"
    seller_sku = [row for row in payload["attributes"] if row["id"] == "SELLER_SKU"]
    assert seller_sku == [{"id": "SELLER_SKU", "value_name": "SKU-123"}]


def test_excel_datetime_is_converted_to_naive_business_timezone():
    value = datetime(2026, 8, 18, 19, 0, tzinfo=timezone.utc)
    result = excel_safe_value(value, "America/Argentina/Buenos_Aires")
    assert result.tzinfo is None
    assert result.hour == 16


def test_empty_gtin_reason_is_preserved_in_attribute_payload():
    reason = {"value_id": "17055159", "value_name": "El producto es un kit o un pack"}
    assert attribute_payload({"GTIN": 0, "EMPTY_GTIN_REASON": reason}) == [
        {
            "id": "EMPTY_GTIN_REASON",
            "value_id": "17055159",
            "value_name": "El producto es un kit o un pack",
        }
    ]


def test_empty_gtin_reason_must_match_provider_option():
    allowed = [
        {"id": "17055159", "name": "El producto es un kit o un pack"},
        {"id": "17055160", "name": "El producto no está registrado"},
    ]
    assert attribute_has_value({"value_id": "17055159", "value_name": "El producto es un kit o un pack"})
    assert value_matches_allowed_option({"value_id": "17055159"}, allowed)
    assert not value_matches_allowed_option({"value_id": "INVENTED"}, allowed)


def test_all_guarded_empty_gtin_reason_ids_are_stable():
    from app.integrations.mercadolibre.attribute_contracts import EMPTY_GTIN_REASON_FALLBACK_VALUES

    assert [value["id"] for value in EMPTY_GTIN_REASON_FALLBACK_VALUES] == [
        "17055158", "17055159", "17055160", "17055161"
    ]


def test_payload_accepts_mercadolibre_picture_ids_without_treating_them_as_urls():
    version = SimpleNamespace(
        title_reference="Producto",
        category_id="MLA1",
        price=1000,
        currency_id="ARS",
        quantity=1,
        commercial={"buying_mode": "buy_it_now"},
        logistics={},
        condition="new",
        attributes={},
    )
    draft = SimpleNamespace(
        title="Producto prueba",
        commercial_config={"listing_type_id": "gold_special"},
    )

    payload = build_item_payload(
        version,
        draft,
        [{"id": "123-MLA456_092026"}],
        seller_sku="SKU-123",
    )

    assert payload["pictures"] == [{"id": "123-MLA456_092026"}]
