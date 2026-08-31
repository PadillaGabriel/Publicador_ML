"""Controlled Mercado Libre discovery probe for live publication contract.

Run from ``backend``::

    python -m scripts.probe_ml_publication_contract \
        --query "Kit Boca Juniors mate yerbera" \
        --category-id MLA392279

The probe reuses an already-connected Mercado Libre account from PostgreSQL.
It never prints OAuth credentials, access/refresh tokens, client secrets, or
Authorization headers. Endpoints not already confirmed by the application are
explicitly marked as discovery candidates and must not be promoted to
production solely because they return HTTP 200.
"""

from __future__ import annotations

import argparse
import json
import uuid
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urlencode

from sqlalchemy import select

from app.accounts.service import load_access_token
from app.core.db import SessionLocal
from app.integrations.mercadolibre.client import MercadoLibreClient, MercadoLibreError
from app.persistence import MercadoLibreAccount


@dataclass(slots=True)
class ProbeResult:
    name: str
    path: str
    contract_status: str
    http_status: int | None
    outcome: str
    summary: dict[str, Any]


def _safe_error(exc: MercadoLibreError) -> dict[str, Any]:
    payload = exc.payload if isinstance(exc.payload, dict) else {}
    causes = payload.get("cause")
    return {
        "message": str(exc),
        "api_error": payload.get("error"),
        "api_message": payload.get("message"),
        "cause_count": len(causes) if isinstance(causes, list) else 0,
    }


def _shape(value: Any) -> dict[str, Any]:
    if isinstance(value, list):
        return {
            "type": "list",
            "count": len(value),
            "sample_keys": sorted(value[0].keys()) if value and isinstance(value[0], dict) else [],
        }
    if isinstance(value, dict):
        return {"type": "dict", "keys": sorted(value.keys())[:60]}
    return {"type": type(value).__name__}


def _probe_get(
    client: MercadoLibreClient,
    *,
    name: str,
    path: str,
    contract_status: str,
) -> tuple[ProbeResult, Any | None]:
    try:
        payload = client.get(path)
    except MercadoLibreError as exc:
        return (
            ProbeResult(
                name=name,
                path=path,
                contract_status=contract_status,
                http_status=exc.status_code,
                outcome="ERROR",
                summary=_safe_error(exc),
            ),
            None,
        )

    return (
        ProbeResult(
            name=name,
            path=path,
            contract_status=contract_status,
            http_status=200,
            outcome="OK",
            summary=_shape(payload),
        ),
        payload,
    )


def _active_account(db, account_id: uuid.UUID | None) -> MercadoLibreAccount:
    if account_id:
        account = db.get(MercadoLibreAccount, account_id)
        if not account or not account.active:
            raise RuntimeError("La cuenta indicada no existe o está inactiva.")
        return account

    accounts = db.scalars(
        select(MercadoLibreAccount)
        .where(MercadoLibreAccount.active.is_(True))
        .order_by(MercadoLibreAccount.created_at.asc())
    ).all()
    if not accounts:
        raise RuntimeError("No hay cuentas Mercado Libre activas conectadas.")
    if len(accounts) > 1:
        choices = ", ".join(f"{row.nickname}={row.id}" for row in accounts)
        raise RuntimeError(
            "Hay más de una cuenta activa. Usá --account-id. "
            f"Disponibles: {choices}"
        )
    return accounts[0]


def _first_category(discovery: Any) -> tuple[str | None, str | None]:
    if not isinstance(discovery, list):
        return None, None
    for row in discovery:
        if isinstance(row, dict) and row.get("category_id"):
            return str(row["category_id"]), str(row.get("category_name") or "")
    return None, None


def _listing_type_rows(payload: Any) -> list[dict[str, Any]]:
    """Return a safe, compact view of listing-type rows.

    Mercado Libre currently exposes more than one response shape across the
    discovery endpoints used by this probe. ``/sites/{site}/listing_types``
    returns a list, while seller availability can wrap the list in an
    ``available`` key. The probe deliberately tolerates both shapes without
    promoting either one to a production contract.
    """
    candidate = payload
    if isinstance(payload, dict) and "available" in payload:
        candidate = payload.get("available")

    if not isinstance(candidate, list):
        return []

    rows: list[dict[str, Any]] = []
    for row in candidate[:30]:
        if isinstance(row, str):
            rows.append({"id": row})
            continue
        if not isinstance(row, dict):
            continue
        rows.append(
            {
                key: row.get(key)
                for key in (
                    "id",
                    "name",
                    "available",
                    "cause",
                    "code",
                    "listing_type_id",
                )
                if key in row
            }
        )
    return rows


def _available_listing_types_view(payload: Any) -> Any:
    """Expose the seller availability value without credentials or headers."""
    if not isinstance(payload, dict):
        return None
    available = payload.get("available")
    if isinstance(available, list):
        return _listing_type_rows(payload)
    if isinstance(available, (str, bool, int, float)) or available is None:
        return available
    if isinstance(available, dict):
        return {key: available.get(key) for key in sorted(available)[:30]}
    return str(type(available).__name__)


def _interesting_category_settings(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    settings = payload.get("settings")
    if not isinstance(settings, dict):
        return {}
    interesting = (
        "listing_allowed",
        "buying_allowed",
        "price",
        "stock",
        "shipping_modes",
        "shipping_options",
        "max_pictures_per_item",
        "maximum_price",
        "minimum_price",
        "vip_subdomain",
        "catalog_domain",
        "user_product_listing_with_context",
    )
    return {key: settings.get(key) for key in interesting if key in settings}


def _attribute_candidates(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        return []
    needles = ("family", "familia", "listing", "publicacion", "publicación")
    matches: list[dict[str, Any]] = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        haystack = " ".join(
            str(row.get(key) or "")
            for key in ("id", "name", "hint", "attribute_group_name")
        ).casefold()
        if any(needle in haystack for needle in needles):
            matches.append(
                {
                    "id": row.get("id"),
                    "name": row.get("name"),
                    "value_type": row.get("value_type"),
                    "tags": row.get("tags"),
                    "hierarchy": row.get("hierarchy"),
                }
            )
    return matches[:20]


def _seller_item_ids(payload: Any, limit: int = 5) -> list[str]:
    if not isinstance(payload, dict):
        return []
    results = payload.get("results")
    if not isinstance(results, list):
        return []
    return [str(value) for value in results[:limit] if value]


def _selected_item_attributes(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    attributes = payload.get("attributes")
    if not isinstance(attributes, list):
        return {}

    wanted = {"SELLER_SKU", "BRAND", "MODEL"}
    selected: dict[str, Any] = {}
    for row in attributes:
        if not isinstance(row, dict):
            continue
        attribute_id = str(row.get("id") or "")
        if attribute_id not in wanted:
            continue
        value = row.get("value_name")
        if value is None and row.get("value_id") is not None:
            value = row.get("value_id")
        selected[attribute_id] = value
    return selected


def _item_contract_view(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    view = {
        key: payload.get(key)
        for key in (
            "id",
            "title",
            "category_id",
            "listing_type_id",
            "family_name",
            "user_product_id",
            "seller_custom_field",
            "status",
        )
        if key in payload
    }
    selected_attributes = _selected_item_attributes(payload)
    if selected_attributes:
        view["selected_attributes"] = selected_attributes
    return view


def run(
    *,
    query: str | None,
    category_id: str | None,
    account_id: uuid.UUID | None,
) -> dict[str, Any]:
    results: list[ProbeResult] = []

    with SessionLocal() as db:
        account = _active_account(db, account_id)
        token = load_access_token(db, account.id)
        client = MercadoLibreClient(token)

        me_result, _ = _probe_get(
            client,
            name="authenticated_identity",
            path="/users/me",
            contract_status="CONFIRMED_IN_CURRENT_PROJECT",
        )
        results.append(me_result)

        resolved_category_name: str | None = None
        if not category_id and query:
            discovery_path = (
                f"/sites/{account.site_id}/domain_discovery/search?"
                f"{urlencode({'q': query, 'limit': 8})}"
            )
            discovery_result, discovery = _probe_get(
                client,
                name="domain_discovery",
                path=discovery_path,
                contract_status="CONFIRMED_IN_CURRENT_PROJECT",
            )
            if isinstance(discovery, list):
                discovery_result.summary["suggestions"] = [
                    {
                        "category_id": row.get("category_id"),
                        "category_name": row.get("category_name"),
                        "domain_id": row.get("domain_id"),
                    }
                    for row in discovery[:5]
                    if isinstance(row, dict)
                ]
            results.append(discovery_result)
            category_id, resolved_category_name = _first_category(discovery)

        if not category_id:
            raise RuntimeError("Indicá --category-id o --query para resolver una categoría.")

        category_result, category = _probe_get(
            client,
            name="category_detail",
            path=f"/categories/{category_id}",
            contract_status="CONFIRMED_IN_CURRENT_PROJECT",
        )
        if isinstance(category, dict):
            resolved_category_name = str(category.get("name") or resolved_category_name or "")
            category_result.summary["settings"] = _interesting_category_settings(category)
            category_result.summary["children_count"] = len(category.get("children_categories") or [])
        results.append(category_result)

        attrs_result, attrs = _probe_get(
            client,
            name="category_attributes",
            path=f"/categories/{category_id}/attributes",
            contract_status="CONFIRMED_IN_CURRENT_PROJECT",
        )
        candidates = _attribute_candidates(attrs)
        if candidates:
            attrs_result.summary["family_or_listing_candidates"] = candidates
        results.append(attrs_result)

        site_listing_result, site_listing = _probe_get(
            client,
            name="site_listing_types_candidate",
            path=f"/sites/{account.site_id}/listing_types",
            contract_status="DISCOVERY_UNCONFIRMED_CURRENT_CONTRACT",
        )
        rows = _listing_type_rows(site_listing)
        if rows:
            site_listing_result.summary["listing_types"] = rows
        results.append(site_listing_result)

        user_listing_path = (
            f"/users/{account.seller_id}/available_listing_types?"
            f"{urlencode({'category_id': category_id})}"
        )
        user_listing_result, user_listing = _probe_get(
            client,
            name="seller_available_listing_types_candidate",
            path=user_listing_path,
            contract_status="DISCOVERY_UNCONFIRMED_CURRENT_CONTRACT",
        )
        available_view = _available_listing_types_view(user_listing)
        if available_view is not None:
            user_listing_result.summary["available"] = available_view
        rows = _listing_type_rows(user_listing)
        if rows:
            user_listing_result.summary["listing_types"] = rows
        results.append(user_listing_result)

        seller_items_path = (
            f"/users/{account.seller_id}/items/search?"
            f"{urlencode({'status': 'active', 'limit': 5})}"
        )
        seller_items_result, seller_items = _probe_get(
            client,
            name="seller_active_items_candidate",
            path=seller_items_path,
            contract_status="DISCOVERY_UNCONFIRMED_CURRENT_CONTRACT",
        )
        item_ids = _seller_item_ids(seller_items)
        if item_ids:
            seller_items_result.summary["sample_item_ids"] = item_ids
        results.append(seller_items_result)

        existing_items: list[dict[str, Any]] = []
        for item_id in item_ids:
            item_path = (
                f"/items/{item_id}?"
                "attributes=id,title,category_id,listing_type_id,family_name,"
                "user_product_id,seller_custom_field,status,attributes"
            )
            item_result, item_payload = _probe_get(
                client,
                name=f"existing_item_contract_{item_id}",
                path=item_path,
                contract_status="DISCOVERY_EXISTING_ACCOUNT_EVIDENCE",
            )
            view = _item_contract_view(item_payload)
            if view:
                item_result.summary["contract_fields"] = view
                existing_items.append(view)
            results.append(item_result)

        category_items_path = (
            f"/users/{account.seller_id}/items/search?"
            f"{urlencode({'status': 'active', 'category': category_id, 'limit': 20})}"
        )
        category_items_result, category_items = _probe_get(
            client,
            name="seller_active_items_in_category_candidate",
            path=category_items_path,
            contract_status="DISCOVERY_UNCONFIRMED_CURRENT_CONTRACT",
        )
        category_item_ids = _seller_item_ids(category_items, limit=5)
        if category_item_ids:
            category_items_result.summary["sample_item_ids"] = category_item_ids
        results.append(category_items_result)

        category_existing_items: list[dict[str, Any]] = []
        for item_id in category_item_ids:
            item_path = (
                f"/items/{item_id}?"
                "attributes=id,title,category_id,listing_type_id,family_name,"
                "user_product_id,seller_custom_field,status,attributes"
            )
            item_result, item_payload = _probe_get(
                client,
                name=f"existing_category_item_contract_{item_id}",
                path=item_path,
                contract_status="DISCOVERY_EXISTING_ACCOUNT_CATEGORY_EVIDENCE",
            )
            view = _item_contract_view(item_payload)
            if view:
                item_result.summary["contract_fields"] = view
                category_existing_items.append(view)
            results.append(item_result)

    return {
        "account": {
            "nickname": account.nickname,
            "seller_id": account.seller_id,
            "site_id": account.site_id,
        },
        "query": query,
        "resolved_category": {
            "category_id": category_id,
            "category_name": resolved_category_name,
        },
        "probes": [asdict(row) for row in results],
        "existing_item_contract_samples": existing_items,
        "existing_category_item_contract_samples": category_existing_items,
        "interpretation_rules": {
            "http_200_is_not_documentation": True,
            "do_not_publish_from_probe": True,
            "listing_type_goal": (
                "Inspect the seller/category availability payload and compare it with accepted "
                "items before choosing a production listing_type_id."
            ),
            "family_name_goal": (
                "Compare family_name, user_product_id and selected product attributes on existing "
                "items, especially items from the exact target category. Do not infer a creation "
                "rule solely from these samples."
            ),
        },
        "security": {
            "tokens_printed": False,
            "secrets_printed": False,
            "authorization_headers_printed": False,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", help="Texto del producto para resolver categoría si no se pasa --category-id.")
    parser.add_argument("--category-id", help="Categoría hoja a investigar, por ejemplo MLA392279.")
    parser.add_argument("--account-id", type=uuid.UUID, help="UUID interno de la cuenta si hay más de una activa.")
    args = parser.parse_args()

    report = run(
        query=(args.query or "").strip() or None,
        category_id=(args.category_id or "").strip() or None,
        account_id=args.account_id,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
