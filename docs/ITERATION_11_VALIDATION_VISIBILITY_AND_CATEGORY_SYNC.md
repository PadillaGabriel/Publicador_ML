# Iteration 11 — Validation visibility and category-contract synchronization

## Objective
Make pre-publication validation observable and prevent the product version from being saved while Mercado Libre category/listing-type metadata is still loading.

## Changes
- Batch detail now includes the persisted latest validation result for every draft.
- The frontend renders validation errors/warnings directly below each draft title.
- Category metadata and seller/category listing types are treated as one loading contract.
- Save ficha is disabled until that contract finishes and a real listing type is selected.
- Stale category responses are ignored when the operator changes category/account before the previous request completes.
- `createProduct` also enforces the same preconditions as a defensive UI guard.

## Database
No migration. Existing `validation_results` rows are reused.
