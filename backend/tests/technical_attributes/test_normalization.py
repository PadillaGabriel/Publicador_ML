from app.technical_attributes.normalization import normalize_attribute_value


def test_normalizes_provider_list_value():
    assert normalize_attribute_value({"id": "BRAND", "value_id": "123", "value_name": "Marca X"}) == {
        "value_id": "123",
        "value_name": "Marca X",
    }


def test_normalizes_measurement_value():
    assert normalize_attribute_value({
        "id": "HEIGHT",
        "value_struct": {"number": 30, "unit": "cm"},
        "value_name": "30 cm",
    }) == {
        "value_struct": {"number": 30, "unit": "cm"},
        "value_name": "30 cm",
    }


def test_normalizes_existing_product_value_shapes():
    assert normalize_attribute_value("Acero") == {"value_name": "Acero"}
    assert normalize_attribute_value({"value_name": "Azul"}) == {"value_name": "Azul"}
    assert normalize_attribute_value(None) is None
    assert normalize_attribute_value("") is None
    assert normalize_attribute_value({"value_name": "   "}) is None
