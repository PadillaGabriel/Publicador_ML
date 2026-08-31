from app.catalog.normalization import category_is_publishable_leaf, normalize_attributes


def _field(attribute: dict) -> dict:
    return normalize_attributes([attribute])["fields"][0]


def test_normalize_attributes_marks_required_attribute_as_mandatory():
    field = _field({"id": "BRAND", "name": "Marca", "value_type": "string", "tags": {"required": True}, "values": []})
    assert field["required"] is True
    assert field["importance"] == "required"
    assert field["required_for_item"] is True
    assert field["catalog_required"] is False


def test_normalize_attributes_marks_catalog_required_as_mandatory():
    field = _field({"id": "MODEL", "name": "Modelo", "value_type": "string", "tags": {"catalog_required": True}, "values": []})
    assert field["required"] is True
    assert field["importance"] == "required"
    assert field["required_for_item"] is False
    assert field["catalog_required"] is True


def test_relevant_optional_attribute_is_recommended():
    field = _field({"id": "COLOR", "name": "Color", "value_type": "string", "relevance": 2, "tags": {}, "values": []})
    assert field["required"] is False
    assert field["importance"] == "recommended"


def test_measurement_is_recommended_even_without_relevance():
    field = _field({"id": "HEIGHT", "name": "Altura", "value_type": "number_unit", "tags": {}, "values": []})
    assert field["importance"] == "recommended"
    assert field["is_measurement"] is True
    assert field["allow_custom_value"] is True


def test_boolean_is_recommended_even_when_provider_encodes_it_as_values():
    field = _field({
        "id": "IS_FOLDABLE",
        "name": "Es plegable",
        "value_type": "list",
        "tags": {},
        "values": [{"id": "1", "name": "Sí"}, {"id": "0", "name": "No"}],
    })
    assert field["importance"] == "recommended"
    assert field["is_boolean"] is True
    assert field["allow_custom_value"] is False


def test_low_signal_optional_attribute_remains_secondary():
    field = _field({"id": "OTHER", "name": "Otro", "value_type": "string", "tags": {}, "values": []})
    assert field["importance"] == "secondary"


def test_string_with_suggested_values_allows_manual_value():
    field = _field({
        "id": "MODEL",
        "name": "Modelo",
        "value_type": "string",
        "tags": {"required": True},
        "values": [{"id": "A", "name": "Modelo A"}],
    })
    assert field["allow_custom_value"] is True


def test_hidden_attribute_is_not_forced_manually():
    field = _field({"id": "INTERNAL", "name": "Interno", "tags": {"required": True, "hidden": True}, "values": []})
    assert field["hidden"] is True
    assert field["required"] is False
    assert field["importance"] == "system"


def test_schema_exposes_importance_counts():
    schema = normalize_attributes([
        {"id": "A", "tags": {"required": True}},
        {"id": "B", "value_type": "number_unit", "tags": {}},
        {"id": "C", "value_type": "string", "tags": {}},
        {"id": "D", "tags": {"hidden": True}},
    ])
    assert schema["counts"] == {"required": 1, "recommended": 1, "secondary": 1}


def test_category_leaf_rejects_parent_with_children():
    assert category_is_publishable_leaf({"settings": {"listing_allowed": True}, "children_categories": [{"id": "X"}]}) is False


def test_category_leaf_rejects_listing_not_allowed():
    assert category_is_publishable_leaf({"settings": {"listing_allowed": False}, "children_categories": []}) is False


def test_category_leaf_accepts_leaf_without_explicit_listing_flag():
    assert category_is_publishable_leaf({"settings": {}, "children_categories": []}) is True


def test_gtin_and_empty_reason_are_exposed_as_one_of_requirement():
    schema = normalize_attributes([
        {
            "id": "GTIN",
            "name": "Código universal",
            "value_type": "string",
            "tags": {"required": True},
            "values": [],
        },
        {
            "id": "EMPTY_GTIN_REASON",
            "name": "Motivo de GTIN vacío",
            "value_type": "list",
            "tags": {},
            "values": [{"id": "17055159", "name": "El producto es un kit o un pack"}],
        },
    ])

    assert schema["requirements"] == [
        {
            "id": "GTIN_OR_EMPTY_REASON",
            "kind": "one_of",
            "attribute_ids": ["GTIN", "EMPTY_GTIN_REASON"],
            "required": True,
            "message": (
                "Informá un GTIN real o seleccioná el motivo oficial por el cual "
                "el producto no tiene GTIN."
            ),
        }
    ]


def test_gtin_without_empty_reason_gets_provider_contract_fallback():
    schema = normalize_attributes([
        {
            "id": "GTIN",
            "name": "Código universal de producto",
            "value_type": "string",
            "tags": {},
            "values": [],
        }
    ])

    fields = {field["id"]: field for field in schema["fields"]}
    reason = fields["EMPTY_GTIN_REASON"]
    assert schema["schema_version"] >= 4
    assert reason["source"] == "provider_contract_fallback"
    assert {value["name"] for value in reason["values"]} == {
        "El producto es una pieza artesanal",
        "El producto es un kit o un pack",
        "El producto no tiene código registrado",
        "Otra razón",
    }
    assert schema["requirements"][0]["id"] == "GTIN_OR_EMPTY_REASON"


def test_metadata_empty_reason_wins_over_fallback():
    schema = normalize_attributes([
        {"id": "GTIN", "name": "GTIN", "value_type": "string", "tags": {}, "values": []},
        {
            "id": "EMPTY_GTIN_REASON",
            "name": "Motivo de GTIN vacío",
            "value_type": "list",
            "tags": {},
            "values": [{"id": "provider-id", "name": "Motivo específico"}],
        },
    ])
    fields = {field["id"]: field for field in schema["fields"]}
    assert fields["EMPTY_GTIN_REASON"]["values"] == [
        {"id": "provider-id", "name": "Motivo específico", "struct": None}
    ]
    assert "source" not in fields["EMPTY_GTIN_REASON"]


def test_gtin_schema_exposes_dedicated_product_identifier_contract():
    schema = normalize_attributes([
        {
            "id": "GTIN",
            "name": "Código universal",
            "value_type": "string",
            "tags": {"required": True},
            "values": [],
        }
    ])

    contract = schema["product_identifier_contract"]
    assert contract["kind"] == "gtin_or_empty_reason"
    assert contract["gtin_attribute_id"] == "GTIN"
    assert contract["empty_reason_attribute_id"] == "EMPTY_GTIN_REASON"
    assert contract["empty_reason_source"] == "provider_contract_fallback"
    assert {value["id"] for value in contract["empty_reason_values"]} == {
        "17055158", "17055159", "17055160", "17055161"
    }


def test_metadata_empty_reason_contract_uses_category_values():
    schema = normalize_attributes([
        {"id": "GTIN", "name": "GTIN", "value_type": "string", "tags": {}, "values": []},
        {
            "id": "EMPTY_GTIN_REASON",
            "name": "Motivo de GTIN vacío",
            "value_type": "list",
            "tags": {},
            "values": [{"id": "provider-id", "name": "Motivo específico"}],
        },
    ])

    contract = schema["product_identifier_contract"]
    assert contract["empty_reason_source"] == "category_metadata"
    assert contract["empty_reason_values"] == [
        {"id": "provider-id", "name": "Motivo específico", "struct": None}
    ]


def test_number_unit_schema_preserves_allowed_and_default_units():
    schema = normalize_attributes([
        {
            "id": "HEIGHT",
            "name": "Altura",
            "value_type": "number_unit",
            "tags": {},
            "allowed_units": [
                {"id": "mm", "name": "mm"},
                {"id": "cm", "name": "cm"},
            ],
            "default_unit": "cm",
            "values": [],
        }
    ])

    field = schema["fields"][0]
    assert schema["schema_version"] == 5
    assert field["is_measurement"] is True
    assert field["allowed_units"] == [
        {"id": "mm", "name": "mm"},
        {"id": "cm", "name": "cm"},
    ]
    assert field["default_unit"] == "cm"
