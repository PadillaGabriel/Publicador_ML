# Iteration 17 — Product identifier contract hardening

## Problem

The universal-code section was not reliable enough. A GTIN could still appear as a normal
category field, older product versions could restore placeholders such as `Otros`, and the
special UI depended on a requirement group instead of a first-class product-identifier
contract. The previous fallback also left the provider ID for "Otra razón" unresolved.

## Decision

The category normalizer now exposes a dedicated `product_identifier_contract`. GTIN and
`EMPTY_GTIN_REASON` are always rendered by one specialized UI component and are excluded
from the generic required/recommended/secondary grids.

Category metadata remains the preferred source for `EMPTY_GTIN_REASON`. When current
category metadata omits the attribute while exposing GTIN, the guarded Mercado Libre
fallback is used with the four current provider reason IDs. Schema version 4 forces cached
raw metadata to be renormalized locally without an unnecessary marketplace request.

## Integrity rules

- A real GTIN and an empty-GTIN reason are mutually exclusive.
- Text placeholders such as `Otros`, SKU values and `0` are never accepted as GTIN.
- Legacy invalid GTIN values are not restored into the editor.
- Product persistence rejects an obviously malformed GTIN before creating a ProductVersion.
- Draft validation remains the final backend gate against the current category contract.

## Architecture

Provider-specific identifier normalization moved from `publication` to
`integrations/mercadolibre/product_identifiers.py`. Publication consumes the provider
contract but no longer owns that vocabulary.

No database migration is required.
