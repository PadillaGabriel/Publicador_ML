from __future__ import annotations

from decimal import Decimal, InvalidOperation

from app.integrations.mercadolibre.client import MercadoLibreClient, MercadoLibreError

MAX_B2B_TIERS = 5
B2B_CONTEXT = ["channel_marketplace", "user_type_business"]


def _money(value) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("El precio mayorista debe ser numérico.") from exc


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


def b2b_quantity_price_payload(current_prices: dict, tiers: list[dict], currency_id: str) -> dict:
    # Mercado Libre documents omission as deletion for PxQ. Preserve every existing
    # non-B2B price by id and replace only the B2B quantity table.
    preserved: list[dict] = []
    for price in current_prices.get("prices") or []:
        if not isinstance(price, dict) or not price.get("id"):
            continue
        contexts = set(((price.get("conditions") or {}).get("context_restrictions") or []))
        is_b2b_quantity = "user_type_business" in contexts and (price.get("conditions") or {}).get("min_purchase_unit")
        if not is_b2b_quantity:
            preserved.append({"id": str(price["id"])})

    desired = [
        {
            "amount": float(row["amount"]),
            "currency_id": currency_id,
            "conditions": {
                "context_restrictions": B2B_CONTEXT,
                "min_purchase_unit": row["min_purchase_unit"],
            },
        }
        for row in tiers
    ]
    return {"prices": [*preserved, *desired]}


def sync_b2b_quantity_prices(
    client: MercadoLibreClient,
    *,
    item_id: str,
    tiers: list[dict],
    currency_id: str,
) -> dict:
    current = client.item_prices(item_id, show_all=True)
    payload = b2b_quantity_price_payload(current, tiers, currency_id)
    response = client.set_b2b_quantity_prices(item_id, payload)
    return {"request": payload, "response": response.payload, "http_status": response.status_code}
