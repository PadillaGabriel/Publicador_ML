from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException

from app.integrations.mercadolibre.client import MercadoLibreClient, MercadoLibreError

WITHOUT_INSTALLMENTS = "WITHOUT_INSTALLMENTS"
WITH_INSTALLMENTS = "WITH_INSTALLMENTS"

# Mercado Libre Argentina documents the current frontend semantics this way:
# - no agregar cuotas -> gold_special
# - agregar cuotas -> gold_pro
# The backend remains responsible for resolving the real listing_type_id and never
# exposes Classic/Premium as the operator's business intent.
_MLA_INTENT_TO_LISTING_TYPE = {
    WITHOUT_INSTALLMENTS: "gold_special",
    WITH_INSTALLMENTS: "gold_pro",
}

_INTENT_LABELS = {
    WITHOUT_INSTALLMENTS: "No agregar cuotas",
    WITH_INSTALLMENTS: "Agregar cuotas",
}


@dataclass(frozen=True, slots=True)
class ListingTypeOption:
    id: str
    name: str


@dataclass(frozen=True, slots=True)
class CommercialOption:
    commercial_intent: str
    label: str
    listing_type_id: str
    listing_type_name: str


def normalize_listing_type_options(payload: dict | list) -> list[ListingTypeOption]:
    raw_items = payload.get("available") if isinstance(payload, dict) else payload
    if not isinstance(raw_items, list):
        return []

    result: list[ListingTypeOption] = []
    seen: set[str] = set()
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        listing_type_id = str(item.get("id") or "").strip()
        name = str(item.get("name") or "").strip()
        if not listing_type_id or listing_type_id in seen:
            continue
        seen.add(listing_type_id)
        result.append(ListingTypeOption(id=listing_type_id, name=name or listing_type_id))
    return result


def fetch_available_listing_types(*, access_token: str, seller_id: str, category_id: str) -> list[ListingTypeOption]:
    client = MercadoLibreClient(access_token)
    payload = client.available_listing_types(seller_id=seller_id, category_id=category_id)
    return normalize_listing_type_options(payload)


def commercial_options_from_listing_types(
    options: list[ListingTypeOption],
    *,
    site_id: str,
) -> list[CommercialOption]:
    """Expose operator intent while retaining ML's real listing_type contract.

    The installments naming used here is specific to Argentina (MLA). Other sites
    must be mapped explicitly before this resolver can offer those intents.
    """
    if site_id != "MLA":
        return []

    by_id = {option.id: option for option in options}
    result: list[CommercialOption] = []
    for intent in (WITHOUT_INSTALLMENTS, WITH_INSTALLMENTS):
        listing_type_id = _MLA_INTENT_TO_LISTING_TYPE[intent]
        listing_type = by_id.get(listing_type_id)
        if not listing_type:
            continue
        result.append(
            CommercialOption(
                commercial_intent=intent,
                label=_INTENT_LABELS[intent],
                listing_type_id=listing_type_id,
                listing_type_name=listing_type.name,
            )
        )
    return result


def fetch_commercial_options(
    *,
    access_token: str,
    seller_id: str,
    category_id: str,
    site_id: str,
) -> list[CommercialOption]:
    listing_types = fetch_available_listing_types(
        access_token=access_token,
        seller_id=seller_id,
        category_id=category_id,
    )
    return commercial_options_from_listing_types(listing_types, site_id=site_id)


def listing_type_for_intent(commercial_intent: str, *, site_id: str) -> str | None:
    if site_id != "MLA":
        return None
    return _MLA_INTENT_TO_LISTING_TYPE.get(commercial_intent)


def validate_selected_listing_type(selected: str | None, options: list[ListingTypeOption]) -> str | None:
    """Kept as a low-level contract helper for diagnostics and backward compatibility."""
    selected = (selected or "").strip() or None
    if selected is None:
        return None
    allowed = {option.id for option in options}
    if selected not in allowed:
        raise MercadoLibreError(
            "El tipo de publicación seleccionado no está disponible para esta cuenta/categoría.",
            status_code=422,
            payload={"selected_listing_type_id": selected, "available": sorted(allowed)},
        )
    return selected


def normalize_commercial_distribution(
    *,
    count: int,
    requested: list[dict] | None,
    options: list[CommercialOption],
) -> list[dict]:
    """Resolve a user-facing installments intent into ML's current listing_type_id.

    The UI sends only WITH_INSTALLMENTS / WITHOUT_INSTALLMENTS. The resolver accepts
    an intent only if Mercado Libre reported the corresponding listing type as
    available for this seller/category.
    """
    by_intent = {option.commercial_intent: option for option in options}
    if not by_intent:
        raise HTTPException(
            status_code=422,
            detail="Mercado Libre no informó modalidades compatibles de cuotas para esta cuenta/categoría.",
        )

    rows = requested or []
    if not rows:
        default_intent = WITHOUT_INSTALLMENTS if WITHOUT_INSTALLMENTS in by_intent else next(iter(by_intent))
        option = by_intent[default_intent]
        return [{
            "commercial_intent": option.commercial_intent,
            "label": option.label,
            "listing_type_id": option.listing_type_id,
            "listing_type_name": option.listing_type_name,
            "count": count,
        }]

    normalized: list[dict] = []
    seen: set[str] = set()
    total = 0
    for row in rows:
        intent = str(row.get("commercial_intent") or "").strip()
        amount = int(row.get("count") or 0)
        if amount <= 0:
            continue
        if intent in seen:
            raise HTTPException(status_code=422, detail=f"Modalidad comercial duplicada: {intent}.")
        option = by_intent.get(intent)
        if not option:
            raise HTTPException(
                status_code=422,
                detail=(
                    "La modalidad comercial seleccionada ya no está disponible para la cuenta/categoría: "
                    f"{intent}."
                ),
            )
        seen.add(intent)
        total += amount
        normalized.append({
            "commercial_intent": option.commercial_intent,
            "label": option.label,
            "listing_type_id": option.listing_type_id,
            "listing_type_name": option.listing_type_name,
            "count": amount,
        })

    if total != count:
        raise HTTPException(
            status_code=422,
            detail="La distribución comercial debe sumar exactamente el total de publicaciones.",
        )
    return normalized


def commercial_sequence(distribution: list[dict]) -> list[dict]:
    """Deterministically interleave installment intents across the generated batch."""
    remaining = [dict(row) for row in distribution]
    result: list[dict] = []
    while any(int(row["count"]) > 0 for row in remaining):
        for row in remaining:
            if int(row["count"]) <= 0:
                continue
            result.append({
                "commercial_intent": row["commercial_intent"],
                "label": row["label"],
                "listing_type_id": row["listing_type_id"],
                "listing_type_name": row["listing_type_name"],
            })
            row["count"] = int(row["count"]) - 1
    return result
