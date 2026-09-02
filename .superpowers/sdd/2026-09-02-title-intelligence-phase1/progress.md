# SDD ledger — plan: C:\Users\padil\OneDrive\Silmar\ml_enterprise_v1\docs\superpowers\plans\2026-09-02-title-intelligence-phase1.md

## Pre-flight review

| Scope | Producer / consumer | Finding | Ruling |
| --- | --- | --- | --- |
| Task 1 -> Task 3 | `get_category_trends` -> title service | The plan interface omits the persisted snapshot required by the existing keyword pipeline. | Preserve the internal `snapshot` member in `CategoryTrendLookup`; Task 3 consumes only terms and status. This avoids duplicate fetches and preserves current snapshot persistence. |
| Task 2 -> Task 3 | `recommend_title` -> API response | Task 2 requires deterministic, factual output; Task 3 maps it without adding facts. | Complete missing Task 2 safety and boundary coverage before API work. |
| Task 3 -> Task 4 | API `max_length` -> selected category settings | The API must not use a literal fallback. | Require a positive caller-provided category limit and keep the UI disabled until it is known. |
| Task 4 -> Task 5 | explicit form update -> smoke test | No publication boundary may be crossed. | Keep component isolated from drafts, jobs, and publication APIs; verify with static scan. |

Ruling: The already committed Task 1 and Task 2 work is not marked complete until its planned safety and boundary tests are present and reviewed — this protects the factual-title guarantee; the cost if wrong is a small corrective commit, not an API change built over an incomplete contract.

## Task 1 corrective completion

- Added provider-failure coverage for expired snapshots (`STALE_FALLBACK`) and no snapshot (`UNAVAILABLE`).
- Verified `get_category_trends` behavior without production changes; the existing implementation already satisfies both contracts and preserves `CategoryTrendLookup.snapshot`.
- Focused verification: `8 passed`; Ruff passed for the touched test and service files.
- Full report: `task-1-report.md`.
