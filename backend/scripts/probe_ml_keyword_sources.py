"""Probe Mercado Libre sources that may support Keyword Intelligence.

Run from ``backend`` with::

    python -m scripts.probe_ml_keyword_sources --query "mate imperial calabaza cuero"

The script reuses the encrypted token of an already connected account. It never
prints OAuth credentials or tokens. Candidate/legacy endpoints are probed only
for Discovery evidence and must not be promoted to production integrations
until their current Mercado Libre contract is verified.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
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


def _shape(value: Any) -> dict[str, Any]:
    if isinstance(value, list):
        return {
            "type": "list",
            "count": len(value),
            "sample_keys": sorted(value[0].keys()) if value and isinstance(value[0], dict) else [],
        }
    if isinstance(value, dict):
        return {"type": "dict", "keys": sorted(value.keys())[:40]}
    return {"type": type(value).__name__}


def _safe_error(exc: MercadoLibreError) -> dict[str, Any]:
    payload = exc.payload if isinstance(exc.payload, dict) else {}
    return {
        "message": str(exc),
        "api_error": payload.get("error"),
        "api_message": payload.get("message"),
        "cause_count": len(payload.get("cause", [])) if isinstance(payload.get("cause"), list) else 0,
    }


def _probe_get(
    client: MercadoLibreClient,
    *,
    name: str,
    path: str,
    contract_status: str,
) -> tuple[ProbeResult, Any | None]:
    try:
        value = client.get(path)
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
            summary=_shape(value),
        ),
        value,
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
        choices = ", ".join(f"{item.nickname}={item.id}" for item in accounts)
        raise RuntimeError(
            "Hay más de una cuenta activa. Ejecutá nuevamente con --account-id. "
            f"Disponibles: {choices}"
        )
    return accounts[0]


def _category_from_discovery(value: Any) -> tuple[str | None, str | None]:
    if not isinstance(value, list):
        return None, None
    for row in value:
        if isinstance(row, dict) and row.get("category_id"):
            return str(row["category_id"]), str(row.get("category_name") or "")
    return None, None


def _titles_from_search(value: Any, limit: int = 10) -> list[str]:
    if not isinstance(value, dict) or not isinstance(value.get("results"), list):
        return []
    titles: list[str] = []
    for row in value["results"]:
        if isinstance(row, dict) and row.get("title"):
            titles.append(str(row["title"]))
            if len(titles) >= limit:
                break
    return titles


def _terms_from_trends(value: Any, limit: int = 20) -> list[str]:
    if not isinstance(value, list):
        return []
    terms: list[str] = []
    for row in value:
        if isinstance(row, dict):
            candidate = row.get("keyword") or row.get("q") or row.get("term")
        else:
            candidate = row if isinstance(row, str) else None
        if candidate:
            terms.append(str(candidate))
            if len(terms) >= limit:
                break
    return terms


def _highlight_ids(value: Any, limit: int = 10) -> list[str]:
    rows: Any = value
    if isinstance(value, dict):
        rows = value.get("content") or value.get("results") or value.get("highlights") or []
    if not isinstance(rows, list):
        return []
    ids: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        candidate = row.get("id") or row.get("item_id") or row.get("product_id")
        if candidate:
            ids.append(str(candidate))
            if len(ids) >= limit:
                break
    return ids


def run(query: str, account_id: uuid.UUID | None) -> dict[str, Any]:
    results: list[ProbeResult] = []
    with SessionLocal() as db:
        account = _active_account(db, account_id)
        token = load_access_token(db, account.id)
        client = MercadoLibreClient(token)

        me_result, me = _probe_get(
            client,
            name="authenticated_identity",
            path="/users/me",
            contract_status="CONFIRMED_IN_CURRENT_PROJECT",
        )
        results.append(me_result)

        discovery_path = f"/sites/{account.site_id}/domain_discovery/search?{urlencode({'q': query, 'limit': 8})}"
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

        category_id, category_name = _category_from_discovery(discovery)
        if not category_id:
            return _report(account, query, category_id, category_name, results)

        category_result, _ = _probe_get(
            client,
            name="category_detail",
            path=f"/categories/{category_id}",
            contract_status="CONFIRMED_IN_CURRENT_PROJECT",
        )
        results.append(category_result)

        attributes_result, attributes = _probe_get(
            client,
            name="category_attributes",
            path=f"/categories/{category_id}/attributes",
            contract_status="CONFIRMED_IN_CURRENT_PROJECT",
        )
        if isinstance(attributes, list):
            attributes_result.summary["attribute_count"] = len(attributes)
        results.append(attributes_result)

        search_path = f"/sites/{account.site_id}/search?{urlencode({'q': query, 'category': category_id, 'limit': 20})}"
        search_result, search_payload = _probe_get(
            client,
            name="marketplace_search",
            path=search_path,
            contract_status="DISCOVERY_UNCONFIRMED_CURRENT_CONTRACT",
        )
        search_titles = _titles_from_search(search_payload)
        if search_titles:
            search_result.summary["sample_titles"] = search_titles
        if isinstance(search_payload, dict) and isinstance(search_payload.get("paging"), dict):
            search_result.summary["paging"] = {
                key: search_payload["paging"].get(key)
                for key in ("total", "primary_results", "offset", "limit")
                if key in search_payload["paging"]
            }
        results.append(search_result)

        highlights_path = f"/highlights/{account.site_id}/category/{category_id}"
        highlights_result, highlights_payload = _probe_get(
            client,
            name="category_highlights_best_sellers_candidate",
            path=highlights_path,
            contract_status="DISCOVERY_UNCONFIRMED_CURRENT_CONTRACT",
        )
        highlight_ids = _highlight_ids(highlights_payload)
        if highlight_ids:
            highlights_result.summary["sample_ids"] = highlight_ids
        results.append(highlights_result)

        trends_path = f"/trends/{account.site_id}/{category_id}"
        trends_result, trends_payload = _probe_get(
            client,
            name="category_trends_candidate",
            path=trends_path,
            contract_status="DISCOVERY_UNCONFIRMED_CURRENT_CONTRACT",
        )
        trend_terms = _terms_from_trends(trends_payload)
        if trend_terms:
            trends_result.summary["sample_terms"] = trend_terms
        results.append(trends_result)

        legacy_trends_path = f"/sites/{account.site_id}/trends/search?{urlencode({'category': category_id})}"
        legacy_result, legacy_payload = _probe_get(
            client,
            name="legacy_category_trends_candidate",
            path=legacy_trends_path,
            contract_status="LEGACY_CANDIDATE_DO_NOT_INTEGRATE",
        )
        legacy_terms = _terms_from_trends(legacy_payload)
        if legacy_terms:
            legacy_result.summary["sample_terms"] = legacy_terms
        results.append(legacy_result)

        return _report(account, query, category_id, category_name, results)


def _report(
    account: MercadoLibreAccount,
    query: str,
    category_id: str | None,
    category_name: str | None,
    results: list[ProbeResult],
) -> dict[str, Any]:
    return {
        "account": {
            "nickname": account.nickname,
            "seller_id": account.seller_id,
            "site_id": account.site_id,
        },
        "query": query,
        "resolved_category": {
            "category_id": category_id,
            "category_name": category_name,
        },
        "probes": [asdict(item) for item in results],
        "security": {
            "tokens_printed": False,
            "secrets_printed": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--query",
        required=True,
        help="Descripción real del producto utilizada para categorizar y probar señales.",
    )
    parser.add_argument(
        "--account-id",
        type=uuid.UUID,
        default=None,
        help="UUID interno de la cuenta; obligatorio sólo si hay más de una activa.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Opcional: guardar el reporte JSON además de imprimirlo.",
    )
    args = parser.parse_args()

    try:
        report = run(args.query.strip(), args.account_id)
    except Exception as exc:  # CLI boundary: present a concise operational error.
        print(json.dumps({"status": "FATAL", "message": str(exc)}, ensure_ascii=False, indent=2))
        return 1

    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
