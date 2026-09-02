# Task 7 report: pricing calculator use cases

## Implementation

- Added `PricingCalculatorService` for the `NEW_PRODUCT` and `EXISTING_LISTING`
  scenarios. It composes immutable profile parameters, Mercado Libre simulation,
  the economic domain, and the existing target-margin optimizer.
- Added explicit request schemas for package context, economic overrides, new
  products, and existing listings.
- Responses expose one-unit scenario metadata, the analyzed `EconomicResult`,
  MC0/15/20 targets, an optional custom target, the economic recommended price,
  and audit data for parameter sources, overrides, marketplace context, and the
  analyzed candidate price.
- New-product inputs reject missing CMV, category, listing type, dimensions, or
  logistics context with domain errors. Existing MLA listings resolve category,
  listing type, current price, and package context through the provider. SKU-only
  requests reject the unavailable baseline lookup explicitly.
- The calculator has no draft, validation, publication, job, migration, or
  external transport behavior of its own.

## TDD evidence

- Added application tests before the implementation; the initial focused run
  failed because `app.pricing.application.calculator` did not exist.
- Added focused coverage for overrides without global-profile mutation, required
  input errors, MLA baseline resolution, and the SKU baseline error.

## Verification

- `DATABASE_URL=postgresql+psycopg://pricing:pricing@localhost/pricing`
  `python -m pytest tests/pricing/test_pricing_application.py -v`: 20 passed.
- Ruff: passed for the new calculator and application exports; import-order
  checks passed for the modified schemas and focused tests.
- `git diff --check`: passed.
