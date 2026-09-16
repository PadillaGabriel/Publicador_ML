from __future__ import annotations

from decimal import Decimal
from typing import Any


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def normalize_attribute_value(raw: object) -> dict | None:
    """Normalize provider/ProductVersion attribute values into one canonical shape."""
    if raw is None:
        return None

    if isinstance(raw, (str, int, float, Decimal)) and not isinstance(raw, bool):
        text = _clean_text(raw)
        return {"value_name": text} if text is not None else None

    if not isinstance(raw, dict):
        return None

    value_name = _clean_text(raw.get("value_name"))
    value_id = _clean_text(raw.get("value_id"))
    raw_struct = raw.get("value_struct")
    value_struct = None
    if isinstance(raw_struct, dict):
        number = raw_struct.get("number")
        unit = _clean_text(raw_struct.get("unit"))
        if number is not None and unit:
            value_struct = {"number": number, "unit": unit}

    if value_struct is not None:
        result = {"value_struct": value_struct}
        if value_name:
            result["value_name"] = value_name
        else:
            result["value_name"] = f"{value_struct['number']} {value_struct['unit']}"
        return result

    if value_id:
        result = {"value_id": value_id}
        if value_name:
            result["value_name"] = value_name
        return result

    if value_name:
        return {"value_name": value_name}

    return None
