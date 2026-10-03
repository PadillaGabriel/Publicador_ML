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
    """Read all ME2 category entries, not only the first one.

    These are category-advertised logistics; their absence is not proof that an
    active seller default (e.g. cross_docking) is forbidden for an item.
    """
    result: set[str] = set()
    logistics = preferences.get("logistics")
    if not isinstance(logistics, list):
        return result
    for entry in logistics:
        if not isinstance(entry, Mapping) or str(entry.get("mode") or "") != ME2_MODE:
            continue
        raw_types = entry.get("types")
        if isinstance(raw_types, list):
            result.update(str(item).strip() for item in raw_types if isinstance(item, str) and item.strip())
    return result


def _active_user_me2_types(preferences: Mapping[str, Any]) -> list[tuple[str, bool]]:
    """Collect active seller logistics across all ME2 entries, preserving order."""
    logistics = preferences.get("logistics")
    if not isinstance(logistics, list):
        return []
    result: list[tuple[str, bool]] = []
    for entry in logistics:
        if not isinstance(entry, Mapping) or str(entry.get("mode") or "") != ME2_MODE:
            continue
        raw_types = entry.get("types")
        if not isinstance(raw_types, list):
            continue
        for item in raw_types:
            if not isinstance(item, Mapping):
                continue
            type_id = str(item.get("type") or "").strip()
            status = str(item.get("status") or "").strip().lower()
            if type_id in ME2_LOGISTIC_TYPES and status == "active":
                result.append((type_id, item.get("default") is True))
    return result


def resolve_shipping_capabilities(
    user_preferences: Mapping[str, Any],
    category_preferences: Mapping[str, Any],
) -> ShippingCapabilities:
    """Identify seller ME2 default and independently determine Flex availability.

    Category logistics describe category-level advertised modes. They are not an
    exhaustive denylist for seller-managed ME2 logistics: in particular a seller
    may have cross_docking as its default while a category advertises only
    self_service. Mercado Libre remains authoritative during item preflight.
    """
    modes = user_preferences.get("modes")
    if not isinstance(modes, list) or ME2_MODE not in modes:
        raise ShippingCapabilityError("La cuenta no tiene Mercado Envíos habilitado.")

    user_types = _active_user_me2_types(user_preferences)
    base = next(
        (type_id for type_id, is_default in user_types
         if is_default and type_id != FLEX_LOGISTIC_TYPE),
        None,
    )
    if base is None:
        # No invented preference: we cannot infer which non-Flex type is base.
        raise ShippingCapabilityError(
            "Mercado Envíos: la cuenta no informó una modalidad base ME2 activa y predeterminada."
        )

    category_types = _category_me2_types(category_preferences)
    flex_available = (
        FLEX_LOGISTIC_TYPE in category_types
        and any(type_id == FLEX_LOGISTIC_TYPE for type_id, _ in user_types)
    )
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
