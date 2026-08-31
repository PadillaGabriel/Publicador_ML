from types import SimpleNamespace

import pytest

from app.integrations.mercadolibre.client import MercadoLibreError
from app.publication.commercial import (
    WITH_INSTALLMENTS,
    WITHOUT_INSTALLMENTS,
    CommercialOption,
    ListingTypeOption,
    commercial_options_from_listing_types,
    commercial_sequence,
    normalize_commercial_distribution,
    normalize_listing_type_options,
    validate_selected_listing_type,
)
from app.publication.payload import (
    build_item_payload,
    family_name_for_draft,
    family_name_for_version,
    publication_title_intent,
)


def test_listing_type_availability_is_normalized_from_seller_category_payload():
    options = normalize_listing_type_options(
        {
            "category_id": "MLA392279",
            "available": [
                {"id": "gold_pro", "name": "Premium"},
                {"id": "gold_special", "name": "Clásica"},
            ],
        }
    )

    assert options == [
        ListingTypeOption(id="gold_pro", name="Premium"),
        ListingTypeOption(id="gold_special", name="Clásica"),
    ]


def test_argentina_commercial_intents_are_derived_only_from_available_listing_types():
    options = [
        ListingTypeOption(id="gold_pro", name="Premium"),
        ListingTypeOption(id="gold_special", name="Clásica"),
        ListingTypeOption(id="free", name="Gratuita"),
    ]

    commercial = commercial_options_from_listing_types(options, site_id="MLA")

    assert commercial == [
        CommercialOption(
            commercial_intent=WITHOUT_INSTALLMENTS,
            label="No agregar cuotas",
            listing_type_id="gold_special",
            listing_type_name="Clásica",
        ),
        CommercialOption(
            commercial_intent=WITH_INSTALLMENTS,
            label="Agregar cuotas",
            listing_type_id="gold_pro",
            listing_type_name="Premium",
        ),
    ]


def test_non_mla_site_does_not_invent_installment_semantics():
    options = [ListingTypeOption(id="gold_special", name="Premium")]
    assert commercial_options_from_listing_types(options, site_id="MLU") == []


def test_selected_listing_type_must_be_in_current_availability():
    options = [ListingTypeOption(id="gold_special", name="Clásica")]

    assert validate_selected_listing_type("gold_special", options) == "gold_special"
    with pytest.raises(MercadoLibreError):
        validate_selected_listing_type("free", options)


def test_commercial_distribution_resolves_installment_intent_to_current_ml_contract():
    options = [
        CommercialOption(
            commercial_intent=WITHOUT_INSTALLMENTS,
            label="No agregar cuotas",
            listing_type_id="gold_special",
            listing_type_name="Clásica",
        ),
        CommercialOption(
            commercial_intent=WITH_INSTALLMENTS,
            label="Agregar cuotas",
            listing_type_id="gold_pro",
            listing_type_name="Premium",
        ),
    ]
    distribution = normalize_commercial_distribution(
        count=3,
        requested=[
            {"commercial_intent": WITHOUT_INSTALLMENTS, "count": 2},
            {"commercial_intent": WITH_INSTALLMENTS, "count": 1},
        ],
        options=options,
    )

    sequence = commercial_sequence(distribution)
    assert sum(row["count"] for row in distribution) == 3
    assert [row["commercial_intent"] for row in sequence] == [
        WITHOUT_INSTALLMENTS,
        WITH_INSTALLMENTS,
        WITHOUT_INSTALLMENTS,
    ]
    assert [row["listing_type_id"] for row in sequence] == [
        "gold_special",
        "gold_pro",
        "gold_special",
    ]


def test_payload_keeps_independent_title_intent_but_uses_current_family_name_create_contract():
    version = SimpleNamespace(
        title_reference="  Kit Boca Juniors con Mate y Yerbera  ",
        category_id="MLA392279",
        price=22999,
        currency_id="ARS",
        quantity=1,
        commercial={"buying_mode": "buy_it_now"},
        condition="new",
        attributes={"BRAND": "Mate Pampa"},
        listing_type_id=None,
        description="",
    )
    draft = SimpleNamespace(
        title="Kit Mate Boca Juniors Yerbera Xeneize Amarillo Mate Pampa",
        commercial_config={
            "commercial_intent": WITHOUT_INSTALLMENTS,
            "listing_type_id": "gold_special",
        },
    )

    payload = build_item_payload(
        version,
        draft,
        ["https://example.test/image.jpg"],
        seller_sku="SKU-TEST-001",
    )

    assert family_name_for_version(version) == "Kit Boca Juniors con Mate y Yerbera"
    assert publication_title_intent(draft) == draft.title
    assert family_name_for_draft(version, draft) == draft.title
    assert payload["family_name"] == draft.title
    assert payload["listing_type_id"] == "gold_special"
    assert payload["seller_custom_field"] == "SKU-TEST-001"
    assert "title" not in payload


def test_number_unit_attribute_preserves_structured_measurement_contract():
    version = SimpleNamespace(
        title_reference="Botella de vidrio 1 L",
        category_id="MLA412517",
        price=1000,
        currency_id="ARS",
        quantity=3,
        commercial={"buying_mode": "buy_it_now"},
        logistics={},
        condition="new",
        attributes={
            "HEIGHT": {
                "value_name": "28 cm",
                "value_struct": {"number": 28, "unit": "cm"},
            },
            "WEIGHT": {
                "value_name": "200 g",
                "value_struct": {"number": 200, "unit": "g"},
            },
        },
        listing_type_id=None,
        description="Botella de vidrio.",
    )
    draft = SimpleNamespace(
        title="Botella de Vidrio 1 L",
        commercial_config={"listing_type_id": "gold_special"},
    )

    payload = build_item_payload(
        version, draft, ["https://example.test/image.jpg"], seller_sku="BOT-001"
    )
    attributes = {row["id"]: row for row in payload["attributes"]}

    assert attributes["HEIGHT"] == {
        "id": "HEIGHT",
        "value_name": "28 cm",
        "value_struct": {"number": 28, "unit": "cm"},
    }
    assert attributes["WEIGHT"]["value_struct"] == {"number": 200, "unit": "g"}
