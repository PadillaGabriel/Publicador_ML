from __future__ import annotations

from decimal import ROUND_CEILING, Decimal, InvalidOperation

from app.integrations.mercadolibre.client import MercadoLibreClient

MAX_B2B_TIERS = 5
B2B_CONTEXT = ["channel_marketplace", "user_type_business"]
PERCENTAGE_QUANT = Decimal("0.01")


class QuantityPricingSyncError(ValueError):
    """Safe-to-surface business error while synchronizing Mercado Libre PxQ B2B."""


def _money(value) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("El precio mayorista debe ser numérico.") from exc


def _percentage(value) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise QuantityPricingSyncError(
            "Mercado Libre devolvió un porcentaje B2B inválido."
        ) from exc
    if not result.is_finite():
        raise QuantityPricingSyncError("Mercado Libre devolvió un porcentaje B2B inválido.")
    return result


def normalize_b2b_quantity_prices(commercial: dict | None, *, base_price) -> list[dict]:
    raw = (commercial or {}).get("quantity_prices") or []
    if not raw:
        return []
    if not isinstance(raw, list):
        raise ValueError("commercial.quantity_prices debe ser una lista.")
    if len(raw) > MAX_B2B_TIERS:
        raise ValueError("Mercado Libre admite como máximo 5 precios B2B por cantidad.")

    base = _money(base_price)
    normalized: list[dict] = []
    seen_quantities: set[int] = set()
    for row in raw:
        if not isinstance(row, dict):
            raise ValueError("Cada precio mayorista debe ser un objeto.")
        quantity = int(row.get("min_purchase_unit") or 0)
        amount = _money(row.get("amount"))
        if quantity <= 1:
            raise ValueError("La cantidad mínima mayorista debe ser mayor a 1.")
        if quantity in seen_quantities:
            raise ValueError("Las cantidades mínimas de los precios mayoristas deben ser únicas.")
        if amount <= 0:
            raise ValueError("El precio mayorista debe ser mayor a 0.")
        if amount >= base:
            raise ValueError("Cada precio mayorista debe ser menor que el precio unitario base.")
        seen_quantities.add(quantity)
        normalized.append({"min_purchase_unit": quantity, "amount": amount})

    normalized.sort(key=lambda item: item["min_purchase_unit"])
    previous_amount = base
    for row in normalized:
        if row["amount"] >= previous_amount:
            raise ValueError(
                "El precio unitario debe disminuir a medida que aumenta la cantidad mínima."
            )
        previous_amount = row["amount"]
    return normalized


def _contexts(node: dict) -> set[str]:
    conditions = node.get("conditions") or {}
    values = conditions.get("context_restrictions") or []
    return {str(value) for value in values}


def _standard_price(current_prices: dict, fallback_price, currency_id: str) -> Decimal:
    for price in current_prices.get("prices") or []:
        if not isinstance(price, dict) or price.get("type") != "standard":
            continue
        conditions = price.get("conditions") or {}
        if conditions.get("min_purchase_unit"):
            continue
        if _contexts(price):
            continue
        if str(price.get("currency_id") or currency_id) != currency_id:
            continue
        amount = _money(price.get("amount"))
        if amount > 0:
            return amount
    fallback = _money(fallback_price)
    if fallback <= 0:
        raise QuantityPricingSyncError("No se pudo resolver el precio estándar actual del ítem.")
    return fallback


def _current_percentage_ids(current_prices: dict) -> dict[int, str]:
    result: dict[int, str] = {}
    for node in current_prices.get("price_per_quantity") or []:
        if not isinstance(node, dict) or "user_type_business" not in _contexts(node):
            continue
        conditions = node.get("conditions") or {}
        quantity = int(conditions.get("min_purchase_unit") or 0)
        node_id = str(node.get("id") or "").strip()
        if quantity > 1 and node_id:
            result[quantity] = node_id
    return result


def _has_absolute_b2b(current_prices: dict) -> bool:
    for node in current_prices.get("prices") or []:
        if not isinstance(node, dict):
            continue
        conditions = node.get("conditions") or {}
        if conditions.get("min_purchase_unit") and "user_type_business" in _contexts(node):
            return True
    return False


def _recommendations_by_quantity(payload: dict) -> dict[int, dict]:
    result: dict[int, dict] = {}
    for row in payload.get("recommendations") or []:
        if not isinstance(row, dict):
            continue
        quantity = int(row.get("quantity") or 0)
        if quantity > 0:
            result[quantity] = row
    return result


def _discount_percentage(*, standard_amount: Decimal, tier_amount: Decimal) -> Decimal:
    raw = (Decimal(1) - (tier_amount / standard_amount)) * Decimal(100)
    return raw.quantize(PERCENTAGE_QUANT, rounding=ROUND_CEILING)


def b2b_percentage_payload(
    current_prices: dict,
    tiers: list[dict],
    recommendations: dict,
    *,
    standard_amount,
) -> dict:
    """Build the 2026 Mercado Libre percentage-based B2B PxQ payload safely.

    The configured economic price remains authoritative. Mercado Libre's recommendation
    is a maximum unit amount: if ML requires a deeper discount than our calculated price,
    synchronization is rejected instead of silently destroying the configured margin.
    """

    base = _money(standard_amount)
    if base <= 0:
        raise QuantityPricingSyncError("El precio estándar debe ser mayor a cero.")

    recommended = _recommendations_by_quantity(recommendations)
    existing_ids = _current_percentage_ids(current_prices)
    desired: list[dict] = []
    previous_percentage = Decimal(0)

    for tier in tiers:
        quantity = int(tier["min_purchase_unit"])
        amount = _money(tier["amount"])
        recommendation = recommended.get(quantity)
        if recommendation is None:
            raise QuantityPricingSyncError(
                f"Mercado Libre no devolvió recomendación B2B para {quantity} unidades."
            )
        if bool(recommendation.get("is_incoherent_quantity")):
            raise QuantityPricingSyncError(
                f"Mercado Libre marcó como incoherente el rango desde {quantity} unidades."
            )

        recommended_amount = _money(recommendation.get("amount"))
        if recommended_amount <= 0:
            raise QuantityPricingSyncError(
                f"Mercado Libre devolvió una recomendación inválida para {quantity} unidades."
            )
        if amount > recommended_amount:
            raise QuantityPricingSyncError(
                "El precio mayorista configurado para "
                f"{quantity} unidades ({amount}) es superior al máximo recomendado por "
                f"Mercado Libre ({recommended_amount}). No se aplica un descuento más profundo "
                "automáticamente para proteger el margen configurado."
            )

        percentage = _discount_percentage(standard_amount=base, tier_amount=amount)
        recommendation_discount = recommendation.get("discount") or {}
        recommended_percentage = _percentage(recommendation_discount.get("percentage", 0))
        if percentage < recommended_percentage:
            percentage = recommended_percentage.quantize(PERCENTAGE_QUANT, rounding=ROUND_CEILING)
        if percentage <= previous_percentage:
            raise QuantityPricingSyncError(
                "Los descuentos porcentuales B2B deben aumentar junto con la cantidad mínima."
            )
        if percentage <= 0 or percentage >= 100:
            raise QuantityPricingSyncError("El descuento B2B debe ser mayor a 0% y menor a 100%.")

        node = {
            "type": "discount_percentage",
            "percentage": float(percentage),
            "conditions": {
                "context_restrictions": B2B_CONTEXT,
                "min_purchase_unit": quantity,
                "eligible": True,
            },
        }
        if quantity in existing_ids:
            node["id"] = existing_ids[quantity]
        desired.append(node)
        previous_percentage = percentage

    return {"price_per_quantity": desired}


def sync_b2b_quantity_prices(
    client: MercadoLibreClient,
    *,
    item_id: str,
    tiers: list[dict],
    currency_id: str,
    base_price,
) -> dict:
    """Synchronize B2B PxQ using Mercado Libre's percentage model required from Oct-2026."""

    current = client.item_prices(item_id, show_all=True, display_version=True)
    version = current.get("version")
    if isinstance(version, bool) or not isinstance(version, (int, str)) or not str(version).strip():
        raise QuantityPricingSyncError("Mercado Libre no devolvió la versión actual de precios.")

    standard_amount = _standard_price(current, base_price, currency_id)
    quantities = [int(row["min_purchase_unit"]) for row in tiers]
    recommendations = client.b2b_quantity_price_recommendations(
        item_id=item_id,
        quantities=quantities,
        standard_amount=standard_amount,
        currency_id=currency_id,
    )
    payload = b2b_percentage_payload(
        current,
        tiers,
        recommendations,
        standard_amount=standard_amount,
    )
    response = client.set_b2b_quantity_discounts(
        item_id,
        payload,
        version=str(version),
        remove_absolute_pxq=_has_absolute_b2b(current),
    )
    return {
        "request": payload,
        "response": response.payload,
        "http_status": response.status_code,
        "version": str(version),
        "standard_amount": standard_amount,
        "recommendations": recommendations.get("recommendations") or [],
    }
