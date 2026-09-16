from __future__ import annotations

from typing import Any


def _norm(value: Any) -> str:
    return str(value or "").strip().casefold()


def _within_length(field: dict, value_name: str) -> bool:
    max_length = field.get("value_max_length")
    if isinstance(max_length, int) and max_length > 0:
        return len(value_name) <= max_length
    return True


def compatible_value(field: dict, value: dict) -> bool:
    """Validate one canonical stored value against a normalized destination field."""
    if not isinstance(field, dict) or not isinstance(value, dict):
        return False
    if field.get("hidden") or field.get("importance") == "system":
        return False

    value_type = str(field.get("value_type") or "string")
    value_name_raw = str(value.get("value_name") or "").strip()
    value_name = value_name_raw.casefold()

    if value_type == "number_unit":
        struct = value.get("value_struct")
        if not isinstance(struct, dict) or struct.get("number") is None:
            return False
        unit = _norm(struct.get("unit"))
        if not unit:
            return False
        allowed_units = field.get("allowed_units") or []
        if not allowed_units:
            return bool(field.get("allow_custom_value"))
        return any(
            unit in {_norm(item.get("id")), _norm(item.get("name"))}
            for item in allowed_units
            if isinstance(item, dict)
        )

    if field.get("is_boolean") or value_type == "boolean":
        if not value_name:
            return False
        values = [item for item in (field.get("values") or []) if isinstance(item, dict)]
        allowed = {_norm(item.get("name")) for item in values if item.get("name") is not None}
        if not allowed:
            allowed = {"si", "sí", "no", "yes", "true", "false"}
        return value_name in allowed

    values = [item for item in (field.get("values") or []) if isinstance(item, dict)]
    value_id = _norm(value.get("value_id"))

    if value_type == "list":
        if value_id:
            return any(value_id == _norm(item.get("id")) for item in values)
        return bool(field.get("allow_custom_value") and value_name_raw and _within_length(field, value_name_raw))

    if value_type == "number":
        if not value_name_raw or not _within_length(field, value_name_raw):
            return False
        try:
            float(value_name_raw.replace(",", "."))
        except ValueError:
            return False
        return bool(field.get("allow_custom_value"))

    if value_id:
        if any(value_id == _norm(item.get("id")) for item in values):
            return True
        return bool(field.get("allow_custom_value") and value_name_raw and _within_length(field, value_name_raw))

    if values and value_name_raw:
        if any(value_name == _norm(item.get("name")) for item in values):
            return True
        return bool(field.get("allow_custom_value") and _within_length(field, value_name_raw))

    return bool(field.get("allow_custom_value") and value_name_raw and _within_length(field, value_name_raw))
