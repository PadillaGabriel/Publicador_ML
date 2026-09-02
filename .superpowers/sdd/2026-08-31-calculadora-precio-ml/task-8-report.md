# Task 8 - Pricing calculator API

## Outcome

- Added thin calculator endpoints for new products and existing Mercado Libre listings.
- Kept profile endpoints unchanged.
- Domain errors are emitted as HTTP 422 details with stable `code` and `message` fields.
- The router constructs the calculator service and performs no pricing formula or publication-workflow logic.

## Tests

- `tests/pricing/test_pricing_router.py` verifies the new-product endpoint returns 200 without publication calls.
- It also verifies `PricingDomainError("SIN_CMV", ...)` becomes `422` with `detail.code == "SIN_CMV"`.

## Verification

- `pytest tests/pricing/test_pricing_router.py -v`: 2 passed.
- `ruff check --select E,F,I app/pricing/router.py app/pricing/schemas.py tests/pricing/test_pricing_router.py`: passed.
- `python -m compileall -q app/pricing tests/pricing/test_pricing_router.py`: passed.
