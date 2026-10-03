"""Operator-only recovery of B2B prices for an already-published MLA.

Run from backend/: python scripts/retry_quantity_prices.py MLA123456789 [--apply]
Without --apply it reports the stored state and sends no Mercado Libre requests.
No listing creation occurs. Never expose this command as an unauthenticated route.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.accounts.service import load_access_token
from app.core.db import SessionLocal
from app.integrations.mercadolibre.client import MercadoLibreClient
from app.persistence import DraftBatch, ProductVersion, Publication, PublicationDraft
from app.worker import _sync_quantity_prices


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("item_id", help="Identificador exacto de una publicación existente (MLA...)")
    parser.add_argument("--apply", action="store_true", help="Enviar escalones pendientes a Mercado Libre")
    args = parser.parse_args()
    with SessionLocal() as db:
        publication = db.scalar(select(Publication).where(Publication.item_id == args.item_id))
        if publication is None:
            print("No existe una publicación local con ese item_id.")
            return 2
        draft = db.get(PublicationDraft, publication.draft_id)
        batch = db.get(DraftBatch, draft.batch_id)
        version = db.get(ProductVersion, batch.product_version_id)
        commercial = version.commercial or {}
        status = (publication.external_response or {}).get("_quantity_price_sync") or {}
        print(json.dumps({
            "item_id": publication.item_id,
            "status": status,
            "quantity_prices": commercial.get("quantity_prices") or [],
            "quantity_prices_draft": commercial.get("quantity_prices_draft") or [],
        }, default=str, ensure_ascii=False, indent=2))
        if not args.apply:
            print("Solo lectura. Para sincronizar, repetí el comando con --apply.")
            return 0
        if not (commercial.get("quantity_prices") or []):
            print("No hay escalones publicables guardados. Completá y guardá primero la ficha.")
            return 3
        if status.get("status") == "SYNCED":
            print("Ya figura como SYNCED. No se reenvía automáticamente.")
            return 0
        client = MercadoLibreClient(load_access_token(db, publication.account_id))
        warning = _sync_quantity_prices(db, client=client, publication=publication,
                                        version=version, draft=draft)
        current = (publication.external_response or {}).get("_quantity_price_sync") or {}
        print(json.dumps({"status": current, "warning": warning}, default=str,
                         ensure_ascii=False, indent=2))
        return 1 if warning else 0


if __name__ == "__main__":
    raise SystemExit(main())
