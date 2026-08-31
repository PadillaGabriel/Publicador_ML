# Iteration 16 — GTIN fallback contract and image upload confirmation

## Problem

Two production-facing gaps were reproduced from operator evidence:

1. Some Mercado Libre category metadata exposes `GTIN` but omits `EMPTY_GTIN_REASON`, while item validation still requires the alternative when the product has no GTIN.
2. The browser file input showed selected files even when the backend had not confirmed/persisted images, allowing draft generation with an empty image order.

## Decisions

- Preserve category metadata as the preferred source. When GTIN exists and `EMPTY_GTIN_REASON` is missing, synthesize only the provider-level alternative contract with the generic Mercado Libre reasons.
- Version the normalized category schema. Cached raw Mercado Libre metadata is re-normalized locally when normalization rules change, avoiding an external request solely to refresh UI semantics.
- Treat backend persistence as the source of truth for image upload state. The UI displays confirmed image count, and draft generation re-queries the product version before continuing.
- Reject draft generation before keyword/OpenAI work if no image is persisted, preventing useless external calls and drafts with empty image orders.

## Technical impact

No database migration is required. Existing category snapshots are re-normalized from `raw_attributes` in place when their local schema version is stale.
