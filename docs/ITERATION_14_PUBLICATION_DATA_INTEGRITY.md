# Iteration 14 — Publication Data Integrity

## Scope

This iteration hardens the live publication contract without changing the approved modular-monolith architecture.

## Implemented

- Product identifiers: `GTIN`, `EAN`, `UPC` and `ISBN` never serialize sentinel values such as `0` as real identifiers.
- Images: uploads are inspected before persistence. The V1 policy enforces a configurable minimum side of 500 px, recommends 1200 px and accepts JPEG/PNG by default. No undocumented maximum resolution is invented.
- Description: a non-empty description is required by pre-publication validation and is synchronized after the item is created through the dedicated Mercado Libre description operation.
- Pickup: `ProductVersion.logistics.local_pick_up` is translated at the Mercado Libre boundary into the item shipping contract.
- Seller warranty: structured domain data is translated into Mercado Libre sale terms (`WARRANTY_TYPE` and `WARRANTY_TIME`).
- Excel: timezone-aware publication timestamps are converted to the configured business timezone before writing the workbook.

## Failure semantics for description

The item result is persisted immediately after Mercado Libre confirms item creation. Description synchronization happens only after that durable checkpoint. If description synchronization fails, the worker never retries item creation. Retryable description failures retry only the description operation against the already confirmed `item_id`.

## Configuration

```text
APP_TIMEZONE=America/Argentina/Buenos_Aires
MAX_UPLOAD_BYTES=10485760
ML_IMAGE_MIN_SIDE_PX=500
ML_IMAGE_RECOMMENDED_SIDE_PX=1200
ML_IMAGE_ALLOWED_FORMATS_CSV=JPEG,JPG,PNG
```

## Dependencies

`Pillow` is used only to inspect image metadata and validate uploaded image files before persistence.

## Database

No migration is required. Warranty and pickup remain inside the already approved structured JSONB boundaries (`commercial` and `logistics`) of `ProductVersion`.

## Tests

Backend regression suite: 40 tests passing.

The frontend TypeScript project passes `tsc -b`. The Vite bundle could not be executed in the Linux validation sandbox because the uploaded `node_modules` contains Windows-specific Rollup optional binaries; this does not indicate a TypeScript error.

## Technical debt

Technical debt introduced: none identified in this iteration.
