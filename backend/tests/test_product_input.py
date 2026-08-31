from pydantic import ValidationError

from app.products.schemas import ProductCreate


def _payload(attributes: dict):
    return {
        "internal_sku": "SKU-1",
        "internal_name": "Producto",
        "category_id": "MLA1",
        "title_reference": "Producto",
        "price": 1000,
        "quantity": 1,
        "attributes": attributes,
    }


def test_product_create_rejects_text_placeholder_as_gtin():
    try:
        ProductCreate(**_payload({"GTIN": "Otros"}))
    except ValidationError as exc:
        assert "GTIN debe contener un código universal numérico real" in str(exc)
    else:
        raise AssertionError("GTIN textual placeholder should be rejected")


def test_product_create_rejects_gtin_and_empty_reason_together():
    try:
        ProductCreate(**_payload({
            "GTIN": "7791234567890",
            "EMPTY_GTIN_REASON": {
                "value_id": "17055159",
                "value_name": "El producto es un kit o un pack",
            },
        }))
    except ValidationError as exc:
        assert "no ambos" in str(exc)
    else:
        raise AssertionError("GTIN and EMPTY_GTIN_REASON cannot coexist")


def test_product_create_accepts_empty_gtin_reason_without_gtin():
    product = ProductCreate(**_payload({
        "EMPTY_GTIN_REASON": {
            "value_id": "17055159",
            "value_name": "El producto es un kit o un pack",
        }
    }))
    assert product.attributes["EMPTY_GTIN_REASON"]["value_id"] == "17055159"
