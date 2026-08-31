"""Stable Mercado Libre attribute contract identifiers and guarded fallbacks.

Only provider vocabulary belongs here. Category-specific business rules are not
allowed in this module.
"""

GTIN_ATTRIBUTE_ID = "GTIN"
EMPTY_GTIN_REASON_ATTRIBUTE_ID = "EMPTY_GTIN_REASON"
PRODUCT_IDENTIFIER_ATTRIBUTE_IDS = frozenset({"GTIN", "EAN", "UPC", "ISBN"})
GTIN_ALTERNATIVE_ATTRIBUTE_IDS = frozenset(
    {GTIN_ATTRIBUTE_ID, EMPTY_GTIN_REASON_ATTRIBUTE_ID}
)

# Mercado Libre documents four valid reasons when a product legitimately has no
# GTIN: handmade, kit/pack, unregistered and another reason. Some category metadata
# snapshots omit EMPTY_GTIN_REASON even though POST /items enforces the alternative.
# The stable IDs below are used only as a guarded provider-contract fallback; values
# returned by category metadata always take precedence.
EMPTY_GTIN_REASON_FALLBACK_VALUES = (
    {"id": "17055158", "name": "El producto es una pieza artesanal", "struct": None},
    {"id": "17055159", "name": "El producto es un kit o un pack", "struct": None},
    {"id": "17055160", "name": "El producto no tiene código registrado", "struct": None},
    {"id": "17055161", "name": "Otra razón", "struct": None},
)
