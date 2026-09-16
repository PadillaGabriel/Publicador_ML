from app.technical_attributes.compatibility import compatible_value


def test_list_value_id_must_exist_when_custom_values_are_disabled():
    field = {
        "id": "BRAND",
        "value_type": "list",
        "hidden": False,
        "allow_custom_value": False,
        "values": [{"id": "1", "name": "A"}, {"id": "2", "name": "B"}],
    }
    assert compatible_value(field, {"value_id": "1", "value_name": "A"}) is True
    assert compatible_value(field, {"value_id": "9", "value_name": "Otra"}) is False


def test_list_can_fall_back_to_name_only_when_custom_allowed():
    field = {
        "id": "MATERIAL",
        "value_type": "string",
        "hidden": False,
        "allow_custom_value": True,
        "values": [],
    }
    assert compatible_value(field, {"value_name": "Acero inoxidable"}) is True


def test_number_unit_requires_allowed_unit():
    field = {
        "id": "HEIGHT",
        "value_type": "number_unit",
        "hidden": False,
        "allow_custom_value": True,
        "allowed_units": [{"id": "cm", "name": "cm"}],
        "values": [],
    }
    assert compatible_value(field, {"value_struct": {"number": 30, "unit": "cm"}, "value_name": "30 cm"}) is True
    assert compatible_value(field, {"value_struct": {"number": 12, "unit": "in"}, "value_name": "12 in"}) is False


def test_hidden_field_is_never_compatible():
    assert compatible_value(
        {"id": "SECRET", "value_type": "string", "hidden": True, "allow_custom_value": True},
        {"value_name": "x"},
    ) is False


def test_list_without_value_id_requires_custom_values():
    field = {
        "id": "COLOR",
        "value_type": "list",
        "hidden": False,
        "allow_custom_value": False,
        "values": [{"id": "1", "name": "Azul"}],
    }
    assert compatible_value(field, {"value_name": "Azul"}) is False


def test_number_must_be_numeric_and_respect_max_length():
    field = {
        "id": "CAPACITY",
        "value_type": "number",
        "hidden": False,
        "allow_custom_value": True,
        "value_max_length": 4,
        "values": [],
    }
    assert compatible_value(field, {"value_name": "123"}) is True
    assert compatible_value(field, {"value_name": "12A"}) is False
    assert compatible_value(field, {"value_name": "12345"}) is False
