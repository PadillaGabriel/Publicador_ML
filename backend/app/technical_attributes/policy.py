from __future__ import annotations

_NON_REUSABLE_IDS = {
    "SELLER_SKU",
    "GTIN",
    "EMPTY_GTIN_REASON",
}


def is_reusable_attribute(
    attribute_id: str,
    *,
    source_category_id: str | None,
    target_category_id: str | None = None,
) -> bool:
    """Return whether an attribute may enter the reusable product library.

    Category compatibility is validated separately against the destination schema.
    This policy only owns global exclusions that must never propagate as reusable
    technical characteristics.
    """
    del source_category_id, target_category_id
    normalized = str(attribute_id or "").strip().upper()
    return bool(normalized) and normalized not in _NON_REUSABLE_IDS
