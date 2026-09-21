"""Normalization for Mercado Libre item identifiers used by pricing flows."""

from __future__ import annotations

import re

_MLA_ITEM_PATTERN = re.compile(r"(?<![A-Z0-9])MLA[-_ ]?(\d{1,20})(?!\d)", re.IGNORECASE)
_NUMERIC_ITEM_PATTERN = re.compile(r"^\d{1,20}$")


def normalize_mla_item_id(value: object) -> str | None:
    """Return canonical ``MLA<digits>`` or fail before calling Mercado Libre."""

    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("El código de publicación debe ser texto.")

    raw = value.strip()
    if not raw:
        return None
    if _NUMERIC_ITEM_PATTERN.fullmatch(raw):
        return f"MLA{raw}"

    match = _MLA_ITEM_PATTERN.search(raw)
    if match:
        return f"MLA{match.group(1)}"

    raise ValueError(
        "Ingresá un MLA válido, por ejemplo MLA123456789, el número del MLA o su URL de Mercado Libre."
    )
