from __future__ import annotations

from typing import Any

from app.integrations.mercadolibre.attribute_contracts import (
    EMPTY_GTIN_REASON_ATTRIBUTE_ID,
    EMPTY_GTIN_REASON_FALLBACK_VALUES,
    GTIN_ATTRIBUTE_ID,
)


_BOOLEAN_NAMES = {"si", "sí", "no", "yes", "true", "false"}
_CUSTOM_VALUE_TYPES = {"string", "number", "number_unit"}
NORMALIZED_SCHEMA_VERSION = 5


def _numeric_relevance(value: Any) -> float:
    if isinstance(value, bool) or value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _looks_boolean(value_type: str, values: list[dict]) -> bool:
    if value_type == "boolean":
        return True
    names = {
        str(value.get("name") or "").strip().casefold()
        for value in values
        if value.get("name") is not None
    }
    return bool(names) and names.issubset(_BOOLEAN_NAMES) and len(names) <= 4


def _importance(
    *,
    required: bool,
    hidden: bool,
    relevance: float,
    value_type: str,
    is_boolean: bool,
) -> str:
    if hidden:
        return "system"
    if required:
        return "required"
    # Mercado Libre exposes relevance plus typed attribute metadata.  We use
    # those provider signals instead of hardcoding category-specific fields.
    # Measurements and yes/no characteristics are useful completeness inputs
    # even when they are not mandatory for item creation.
    if relevance > 0 or value_type == "number_unit" or is_boolean:
        return "recommended"
    return "secondary"


def normalize_attributes(raw_attributes: list[dict]) -> dict:
    fields = []
    for position, attr in enumerate(raw_attributes):
        tags = attr.get("tags") or {}
        raw_values = attr.get("values") or []
        values = [
            {
                "id": value.get("id"),
                "name": value.get("name"),
                "struct": value.get("struct"),
            }
            for value in raw_values
            if value.get("name") is not None
        ]
        value_type = str(attr.get("value_type") or "string")
        required_for_item = bool(tags.get("required"))
        catalog_required = bool(tags.get("catalog_required"))
        conditional_required = bool(
            tags.get("conditional_required")
            or tags.get("conditionally_required")
        )
        hidden = bool(tags.get("hidden") or tags.get("read_only"))
        required = (required_for_item or catalog_required) and not hidden
        relevance = _numeric_relevance(attr.get("relevance"))
        is_boolean = _looks_boolean(value_type, values)
        importance = _importance(
            required=required,
            hidden=hidden,
            relevance=relevance,
            value_type=value_type,
            is_boolean=is_boolean,
        )
        allows_custom_value = (
            not hidden
            and not is_boolean
            and value_type in _CUSTOM_VALUE_TYPES
            and not bool(tags.get("read_only"))
        )
        fields.append(
            {
                "id": attr.get("id"),
                "label": attr.get("name") or attr.get("id"),
                "value_type": value_type,
                "required": required,
                "required_for_item": required_for_item,
                "catalog_required": catalog_required,
                "conditional_required": conditional_required,
                "hidden": hidden,
                "importance": importance,
                "relevance": relevance,
                "is_boolean": is_boolean,
                "is_measurement": value_type == "number_unit",
                "allowed_units": [
                    {"id": unit.get("id"), "name": unit.get("name") or unit.get("id")}
                    for unit in (attr.get("allowed_units") or [])
                    if unit.get("id") or unit.get("name")
                ],
                "default_unit": attr.get("default_unit") or attr.get("default_unit_id"),
                "allow_custom_value": allows_custom_value,
                "allow_variations": bool(tags.get("allow_variations")),
                "attribute_group_id": attr.get("attribute_group_id"),
                "attribute_group_name": attr.get("attribute_group_name"),
                "hierarchy": attr.get("hierarchy"),
                "hint": attr.get("hint"),
                "value_max_length": attr.get("value_max_length"),
                "position": position,
                "values": values,
            }
        )

    field_ids = {field["id"] for field in fields if field.get("id")}

    # Some current Mercado Libre category snapshots expose GTIN but omit the
    # alternative EMPTY_GTIN_REASON, while POST /items can still require that
    # alternative when the seller has no GTIN. Keep the UI metadata-driven when
    # possible and synthesize only the provider-level fallback contract when the
    # category metadata is incomplete.
    if GTIN_ATTRIBUTE_ID in field_ids and EMPTY_GTIN_REASON_ATTRIBUTE_ID not in field_ids:
        fields.append(
            {
                "id": EMPTY_GTIN_REASON_ATTRIBUTE_ID,
                "label": "Motivo de GTIN vacío",
                "value_type": "list",
                "required": False,
                "required_for_item": False,
                "catalog_required": False,
                "conditional_required": True,
                "hidden": False,
                "importance": "system",
                "relevance": 0.0,
                "is_boolean": False,
                "is_measurement": False,
                "allow_custom_value": False,
                "allow_variations": False,
                "attribute_group_id": None,
                "attribute_group_name": None,
                "hierarchy": None,
                "hint": "Seleccioná el motivo real por el cual este producto no tiene GTIN.",
                "value_max_length": None,
                "position": len(raw_attributes),
                "values": [dict(value) for value in EMPTY_GTIN_REASON_FALLBACK_VALUES],
                "source": "provider_contract_fallback",
            }
        )
        field_ids.add(EMPTY_GTIN_REASON_ATTRIBUTE_ID)

    priority = {"required": 0, "recommended": 1, "secondary": 2, "system": 3}
    fields.sort(
        key=lambda field: (
            priority[field["importance"]],
            -field["relevance"],
            field["position"],
        )
    )

    requirements = []
    product_identifier_contract = None
    if {GTIN_ATTRIBUTE_ID, EMPTY_GTIN_REASON_ATTRIBUTE_ID}.issubset(field_ids):
        requirements.append(
            {
                "id": "GTIN_OR_EMPTY_REASON",
                "kind": "one_of",
                "attribute_ids": [GTIN_ATTRIBUTE_ID, EMPTY_GTIN_REASON_ATTRIBUTE_ID],
                "required": True,
                "message": (
                    "Informá un GTIN real o seleccioná el motivo oficial por el cual "
                    "el producto no tiene GTIN."
                ),
            }
        )
        reason_field = next(
            field for field in fields if field.get("id") == EMPTY_GTIN_REASON_ATTRIBUTE_ID
        )
        product_identifier_contract = {
            "kind": "gtin_or_empty_reason",
            "required": True,
            "gtin_attribute_id": GTIN_ATTRIBUTE_ID,
            "empty_reason_attribute_id": EMPTY_GTIN_REASON_ATTRIBUTE_ID,
            "empty_reason_values": [dict(value) for value in reason_field.get("values") or []],
            "empty_reason_source": reason_field.get("source") or "category_metadata",
        }

    return {
        "schema_version": NORMALIZED_SCHEMA_VERSION,
        "fields": fields,
        "requirements": requirements,
        "product_identifier_contract": product_identifier_contract,
        "counts": {
            "required": sum(field["importance"] == "required" for field in fields),
            "recommended": sum(field["importance"] == "recommended" for field in fields),
            "secondary": sum(field["importance"] == "secondary" for field in fields),
        },
    }


def category_is_publishable_leaf(raw_category: dict) -> bool:
    settings = raw_category.get("settings") or {}
    children = raw_category.get("children_categories") or []
    listing_allowed = settings.get("listing_allowed")
    if listing_allowed is False:
        return False
    if children:
        return False
    return True
