from types import SimpleNamespace

import pytest

from app.publication.payload import build_item_payload
from app.publication.shipping import ShippingCapabilityError, resolve_shipping_capabilities


def _user_preferences():
    return {
        "modes": ["me2", "me1", "custom", "not_specified"],
        "logistics": [
            {
                "mode": "me2",
                "types": [
                    {"type": "drop_off", "default": True, "status": "active"},
                    {"type": "self_service", "default": False, "status": "active"},
                ],
            },
            {
                "mode": "me1",
                "types": [{"type": "default", "default": True, "status": "active"}],
            },
        ],
    }


def _category_preferences():
    return {
        "logistics": [
            {"mode": "me1", "types": ["default"]},
            {"mode": "me2", "types": ["drop_off", "self_service", "cross_docking"]},
        ]
    }


def test_shipping_capabilities_prefer_default_me2_and_expose_flex_separately():
    result = resolve_shipping_capabilities(_user_preferences(), _category_preferences())

    assert result.mode == "me2"
    assert result.base_logistic_type == "drop_off"
    assert result.flex_available is True
    assert result.flex_logistic_type == "self_service"


def test_shipping_capabilities_never_fall_back_to_me1_when_me2_has_no_resolvable_base():
    user = _user_preferences()
    user["logistics"][0]["types"] = [
        {"type": "self_service", "default": False, "status": "active"}
    ]

    with pytest.raises(ShippingCapabilityError, match="Mercado Envíos"):
        resolve_shipping_capabilities(user, _category_preferences())


def test_payload_uses_resolved_me2_shipping_contract_from_product_logistics():
    version = SimpleNamespace(
        title_reference="Producto",
        category_id="MLA1",
        price=1000,
        currency_id="ARS",
        quantity=1,
        commercial={"buying_mode": "buy_it_now"},
        logistics={
            "local_pick_up": False,
            "pricing_package": {
                "dimensions": "30x20x10",
                "weight_kg": 1,
                "logistic_type": "self_service",
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
        seller_sku="SKU-1",
    )

    assert payload["shipping"] == {
        "mode": "me2",
        "logistic_type": "self_service",
        "local_pick_up": False,
        "free_shipping": False,
    }


def test_payload_rejects_incompatible_me1_default_contract_in_publication_flow():
    version = SimpleNamespace(
        title_reference="Producto",
        category_id="MLA1",
        price=1000,
        currency_id="ARS",
        quantity=1,
        commercial={"buying_mode": "buy_it_now"},
        logistics={
            "pricing_package": {
                "logistic_type": "default",
                "shipping_mode": "me1",
                "free_shipping": False,
            }
        },
        condition="new",
        attributes={},
    )
    draft = SimpleNamespace(
        title="Producto prueba",
        commercial_config={"listing_type_id": "gold_special"},
    )

    with pytest.raises(ShippingCapabilityError, match="Mercado Envíos"):
        build_item_payload(version, draft, [], seller_sku="SKU-1")
