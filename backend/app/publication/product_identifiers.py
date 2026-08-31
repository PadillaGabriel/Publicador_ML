from __future__ import annotations

from typing import Any

from app.integrations.mercadolibre.attribute_contracts import PRODUCT_IDENTIFIER_ATTRIBUTE_IDS


_EMPTY_IDENTIFIER_VALUES = {"", "0", "0.0", "none", "null"}


def normalized_identifier_value(value: Any) -> Any | None:
    """Normalize sentinel-like product identifier values to absence.

    Numeric/string zero is not a valid product identifier. It must never be sent to
    Mercado Libre as a literal GTIN/EAN/UPC/ISBN value.
    """
    if value is None:
        return None

    if isinstance(value, dict):
        normalized = dict(value)
        value_id = str(normalized.get("value_id") or "").strip()
        value_name = str(normalized.get("value_name") or normalized.get("name") or "").strip()
        if not value_id and value_name.casefold() in _EMPTY_IDENTIFIER_VALUES:
            return None
        return normalized

    text = str(value).strip()
    if text.casefold() in _EMPTY_IDENTIFIER_VALUES:
        return None
    return value


def attribute_has_value(value: Any) -> bool:
    """Return whether an attribute representation contains a meaningful value."""
    if value is None:
        return False
    if isinstance(value, dict):
        return bool(
            str(value.get("value_id") or "").strip()
            or str(value.get("value_name") or value.get("name") or "").strip()
        )
    if isinstance(value, (list, tuple, set)):
        return bool(value)
    return bool(str(value).strip())


def is_product_identifier(attribute_id: str) -> bool:
    return attribute_id.strip().upper() in PRODUCT_IDENTIFIER_ATTRIBUTE_IDS


def is_valid_identifier_format(value: Any) -> bool:
    """Reject only identifiers that are certainly malformed before provider validation.

    Mercado Libre remains authoritative for category/product-specific identifier rules.
    Locally we reject empty sentinels and non-numeric candidates; accepted length/check
    digit semantics are deliberately left to the provider contract.
    """
    normalized = normalized_identifier_value(value)
    if normalized is None:
        return True
    if isinstance(normalized, dict):
        candidate = normalized.get("value_name") or normalized.get("name") or normalized.get("value_id")
    else:
        candidate = normalized
    text = str(candidate or "").strip().replace("-", "")
    return bool(text) and text.isdigit()


def value_matches_allowed_option(value: Any, allowed_values: list[dict]) -> bool:
    """Validate a selected provider enum by id first and name as a safe fallback."""
    if not attribute_has_value(value):
        return False
    if not allowed_values:
        return True

    if isinstance(value, dict):
        candidate_id = str(value.get("value_id") or "").strip()
        candidate_name = str(value.get("value_name") or value.get("name") or "").strip().casefold()
    else:
        candidate_id = ""
        candidate_name = str(value).strip().casefold()

    for option in allowed_values:
        option_id = str(option.get("id") or "").strip()
        option_name = str(option.get("name") or "").strip().casefold()
        if candidate_id and option_id and candidate_id == option_id:
            return True
        if candidate_name and option_name and candidate_name == option_name:
            return True
    return False
