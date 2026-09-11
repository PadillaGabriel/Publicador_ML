from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol


ME2_MODE = "me2"
FLEX_LOGISTIC_TYPE = "self_service"
ME2_LOGISTIC_TYPES = frozenset({
    "drop_off",
    "cross_docking",
    "xd_drop_off",
    "fulfillment",
    FLEX_LOGISTIC_TYPE,
    "turbo",
})


class ShippingPreferencesClient(Protocol):
    def user_shipping_preferences(self, seller_id: str) -> dict: ...

    def category_shipping_preferences(self, category_id: str) -> dict: ...


class ShippingCapabilityError(ValueError):
    """Raised when Mercado Envíos cannot be resolved from provider capabilities."""


@dataclass(frozen=True)
class ShippingCapabilities:
    mode: str
    base_logistic_type: str
    flex_available: bool
    flex_logistic_type: str = FLEX_LOGISTIC_TYPE


def _category_me2_types(preferences: Mapping[str, Any]) -> set[str]:
    logistics = preferences.get("logistics")
    if not isinstance(logistics, list):
        return set()
    for entry in logistics:
        if not isinstance(entry, Mapping) or str(entry.get("mode") or "") != ME2_MODE:
            continue
        raw_types = entry.get("types")
        if not isinstance(raw_types, list):
            return set()
        return {str(item).strip() for item in raw_types if str(item).strip()}
    return set()


def _active_user_me2_types(preferences: Mapping[str, Any]) -> list[tuple[str, bool]]:
    logistics = preferences.get("logistics")
    if not isinstance(logistics, list):
        return []
    for entry in logistics:
        if not isinstance(entry, Mapping) or str(entry.get("mode") or "") != ME2_MODE:
            continue
        raw_types = entry.get("types")
        if not isinstance(raw_types, list):
            return []
        result: list[tuple[str, bool]] = []
        for item in raw_types:
            if not isinstance(item, Mapping):
                continue
            type_id = str(item.get("type") or "").strip()
            status = str(item.get("status") or "active").strip().lower()
            if type_id and status == "active":
                result.append((type_id, bool(item.get("default"))))
        return result
    return []


def resolve_shipping_capabilities(
    user_preferences: Mapping[str, Any],
    category_preferences: Mapping[str, Any],
) -> ShippingCapabilities:
    """Resolve the seller/category Mercado Envíos contract without guessing ME1/ME2.

    Mercado Libre publishes both account capabilities and category capabilities. The
    base logistics type must be an active ME2 default for the seller and valid for the
    category. Flex remains a separate optional decision when ``self_service`` is active.
    """

    modes = user_preferences.get("modes")
    if not isinstance(modes, list) or ME2_MODE not in {str(mode) for mode in modes}:
        raise ShippingCapabilityError("La cuenta no tiene Mercado Envíos habilitado.")

    category_types = _category_me2_types(category_preferences)
    user_types = _active_user_me2_types(user_preferences)
    allowed = [
        (type_id, is_default)
        for type_id, is_default in user_types
        if type_id in category_types and type_id in ME2_LOGISTIC_TYPES
    ]

    base = next(
        (
            type_id
            for type_id, is_default in allowed
            if is_default and type_id != FLEX_LOGISTIC_TYPE
        ),
        None,
    )
    if base is None:
        raise ShippingCapabilityError(
            "Mercado Envíos está activo, pero Mercado Libre no informó una logística base ME2 válida para esta categoría."
        )

    flex_available = any(type_id == FLEX_LOGISTIC_TYPE for type_id, _ in allowed)
    return ShippingCapabilities(
        mode=ME2_MODE,
        base_logistic_type=base,
        flex_available=flex_available,
    )


def publication_shipping_payload(logistics: Mapping[str, Any]) -> dict[str, Any] | None:
    """Translate the persisted logistics contract to Mercado Libre's item payload."""

    local_pick_up_present = "local_pick_up" in logistics
    package = logistics.get("pricing_package")
    package = package if isinstance(package, Mapping) else {}
    mode = str(package.get("shipping_mode") or "").strip()
    logistic_type = str(package.get("logistic_type") or "").strip()
    free_shipping = package.get("free_shipping")

    if not mode and not logistic_type and free_shipping is None and not local_pick_up_present:
        return None
    if mode != ME2_MODE or logistic_type not in ME2_LOGISTIC_TYPES:
        raise ShippingCapabilityError(
            "La publicación requiere una configuración válida de Mercado Envíos antes de validar."
        )

    result: dict[str, Any] = {
        "mode": mode,
        "logistic_type": logistic_type,
    }
    if local_pick_up_present:
        result["local_pick_up"] = bool(logistics.get("local_pick_up"))
    if free_shipping is not None:
        result["free_shipping"] = bool(free_shipping)
    return result


def fetch_shipping_capabilities(
    client: ShippingPreferencesClient,
    *,
    seller_id: str,
    category_id: str,
) -> ShippingCapabilities:
    """Fetch and resolve the current seller/category shipping capabilities."""

    return resolve_shipping_capabilities(
        client.user_shipping_preferences(seller_id),
        client.category_shipping_preferences(category_id),
    )
