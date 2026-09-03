# Title Intelligence Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deterministic, trend-assisted title recommendations that never invent product facts and remain usable when Mercado Libre trends fail.

**Architecture:** Reuse the existing Mercado Libre client and `KeywordTrendSnapshot` cache through a public cached-trends reader. A pure title-intelligence domain generates candidates and ranks them; a thin API service and an explicit frontend action consume it. No AI, scraper, Redis, highlights provider, new dependency, draft, job, or publication flow is added.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy, PostgreSQL cache already in use, React 19, TypeScript, Vite.

**Spec:** `docs/superpowers/specs/2026-09-02-title-intelligence-phase1-design.md`

## Global Constraints

- Reuse `MercadoLibreClient` and `KeywordTrendSnapshot`; do not duplicate HTTP fetching or cache code.
- Product facts take precedence over trends; incompatible trend tokens are never inserted.
- Provider failure or empty trends must produce a factual fallback, not HTTP 500.
- Title maximum length is an explicit request constraint, not a generator constant.
- “Usar título” only updates the frontend form; it must not call drafts, jobs, publication, or `POST /items`.
- Run focused tests, a review, and code-quality checks after each task. No push, merge, deployment, or automatic deletion.

---

### Task 1: Make cached category trends reusable

**Files:**
- Modify: `backend/app/keywords/service.py`
- Modify: `backend/tests/test_keywords.py`

**Interfaces:**
- Produces `CategoryTrendLookup(terms: tuple[str, ...], cache_status: Literal["FRESH_HIT", "MISS_FETCHED", "STALE_FALLBACK", "UNAVAILABLE"])`.
- Produces `get_category_trends(db, *, site_id, category_id, access_token) -> CategoryTrendLookup`.
- Existing `build_ml_keyword_snapshot` consumes the reader without changing its existing snapshot persistence format.

- [ ] **Step 1: Write failing cache and fallback tests**

```python
def test_returns_stale_terms_when_provider_fails(db, stale_snapshot, monkeypatch):
    monkeypatch.setattr(MercadoLibreClient, "category_trends", raise_timeout)
    lookup = get_category_trends(db, site_id="MLA", category_id="MLA1", access_token="token")
    assert lookup.terms == ("cesto ropa",)
    assert lookup.cache_status == "STALE_FALLBACK"

def test_returns_unavailable_without_snapshot(db, monkeypatch):
    monkeypatch.setattr(MercadoLibreClient, "category_trends", raise_timeout)
    lookup = get_category_trends(db, site_id="MLA", category_id="MLA1", access_token="token")
    assert lookup.terms == ()
    assert lookup.cache_status == "UNAVAILABLE"
```

- [ ] **Step 2: Run the tests red**

Run: `pytest backend/tests/test_keywords.py -v`

Expected: import error for `get_category_trends`.

- [ ] **Step 3: Implement one public reader**

```python
@dataclass(frozen=True, slots=True)
class CategoryTrendLookup:
    terms: tuple[str, ...]
    cache_status: Literal["FRESH_HIT", "MISS_FETCHED", "STALE_FALLBACK", "UNAVAILABLE"]
```

Extract the current fresh-cache, fetch, and stale-cache branches from `_category_trends`. Return `UNAVAILABLE` with empty terms when there is no usable cache. Update `build_ml_keyword_snapshot` to use this reader; do not create a second client call.

- [ ] **Step 4: Run green checks**

Run: `pytest backend/tests/test_keywords.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/keywords/service.py backend/tests/test_keywords.py
git commit -m "refactor: expose cached category trends reader"
```

### Task 2: Add the pure deterministic title domain

**Files:**
- Create: `backend/app/title_intelligence/__init__.py`
- Create: `backend/app/title_intelligence/domain.py`
- Create: `backend/tests/title_intelligence/test_domain.py`

**Interfaces:**
- Produces `ProductTitleContext`, `TitleConstraints`, `TitleRecommendation`.
- Produces `recommend_title(context, trends, constraints) -> TitleRecommendation`.
- Reuses pure `normalize_text` and `content_tokens` from `app.keywords.relevance`; it does not import FastAPI, SQLAlchemy, OpenAI, or an HTTP client.

- [ ] **Step 1: Write the failing safety tests**

```python
def test_compatible_trend_can_improve_a_factual_title():
    context = ProductTitleContext(
        category_id="MLA1",
        product_name="Cesto plástico plegable",
        attributes={"capacity": "40 L", "use": "ropa"},
    )
    result = recommend_title(context, ("cesto ropa sucia",), TitleConstraints(max_length=60))
    assert result.recommended_title == "CESTO PLEGABLE PARA ROPA 40L"

def test_incompatible_material_is_never_added():
    result = recommend_title(context, ("cesto rattan",), TitleConstraints(max_length=60))
    assert "RATTAN" not in result.recommended_title

def test_empty_trends_produces_a_valid_factual_fallback():
    result = recommend_title(context, (), TitleConstraints(max_length=60))
    assert result.fallback_used is True
    assert result.recommended_title
```

- [ ] **Step 2: Run red**

Run: `pytest backend/tests/title_intelligence/test_domain.py -v`

Expected: import error for `app.title_intelligence.domain`.

- [ ] **Step 3: Implement deterministic generation**

Build factual ordered terms from product name and confirmed attributes. Accept a trend phrase only when every inserted token is already supported by factual tokens. Generate 3–10 deduplicated candidates, reject candidates over `max_length`, and sort deterministically by factual coverage, compatible trend relevance, readability, and duplication penalty.

- [ ] **Step 4: Add boundary tests and run green**

```python
def test_duplicate_tokens_are_removed():
    result = recommend_title(context, ("cesto cesto ropa",), TitleConstraints(max_length=60))
    assert result.recommended_title.split().count("CESTO") == 1

def test_same_input_has_same_output():
    first = recommend_title(context, ("cesto ropa",), TitleConstraints(max_length=60))
    second = recommend_title(context, ("cesto ropa",), TitleConstraints(max_length=60))
    assert first == second

def test_invalid_max_length_is_rejected():
    with pytest.raises(ValueError, match="max_length"):
        TitleConstraints(max_length=0)
```

Run: `pytest backend/tests/title_intelligence/test_domain.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/title_intelligence backend/tests/title_intelligence/test_domain.py
git commit -m "feat: add deterministic title intelligence domain"
```

### Task 3: Expose the recommendation API

**Files:**
- Create: `backend/app/title_intelligence/schemas.py`
- Create: `backend/app/title_intelligence/service.py`
- Create: `backend/app/title_intelligence/router.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/title_intelligence/test_router.py`

**Interfaces:**
- `POST /api/title-intelligence/generate` accepts `account_id`, `category_id`, `product_name`, factual attributes, and the category-derived `max_length`.
- Response: `recommended_title`, `alternatives`, `confidence`, `matched_trends`, `fallback_used`.
- `generate_title_recommendation(db, payload)` loads the account token, calls Task 1 and Task 2, and has no draft/job/publication dependency.

- [ ] **Step 1: Write failing endpoint tests**

```python
def test_generate_returns_factual_fallback_when_trends_are_unavailable(client, monkeypatch):
    monkeypatch.setattr(title_service, "get_category_trends", unavailable_lookup)
    response = client.post("/api/title-intelligence/generate", json=valid_payload)
    assert response.status_code == 200
    assert response.json()["fallback_used"] is True

def test_generate_has_no_publication_side_effect(client, publication_spy):
    client.post("/api/title-intelligence/generate", json=valid_payload)
    assert publication_spy.calls == 0
```

- [ ] **Step 2: Run red**

Run: `pytest backend/tests/title_intelligence/test_router.py -v`

Expected: 404 before the router is registered.

- [ ] **Step 3: Implement schemas, service, router, and registration**

Map only factual request fields to `ProductTitleContext`. Return stable 422 details for missing account, category, product identity, or invalid max length. The caller supplies the selected category contract's `settings.max_title_length`; do not default to a literal. Catch the Task 1 unavailable result and return Task 2 factual fallback; do not return raw provider errors.

- [ ] **Step 4: Run green**

Run: `pytest backend/tests/title_intelligence/test_router.py backend/tests/test_keywords.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/title_intelligence backend/app/main.py backend/tests/title_intelligence
git commit -m "feat: expose deterministic title recommendations"
```

### Task 4: Add the explicit publisher title assistant

**Files:**
- Create: `frontend/src/title-intelligence/TitleAssistant.tsx`
- Create: `frontend/src/title-intelligence/types.ts`
- Modify: `frontend/src/main.tsx`
- Modify: `frontend/src/styles.css`

**Interfaces:**
- `TitleAssistant` receives `accountId`, `categoryId`, factual form text, category-derived `maxLength`, and `onUseTitle(title)`.
- It calls only `POST /api/title-intelligence/generate`.
- `onUseTitle` updates `form.title` only after an explicit user click.

- [ ] **Step 1: Check current frontend test support**

Run: `npm run`

Expected: record whether a test script exists. Do not add a test dependency if it does not.

- [ ] **Step 2: Implement the isolated component**

```tsx
<TitleAssistant
  accountId={accountId}
  categoryId={categoryId}
  productName={form.title || form.name}
  attributes={currentProductAttributes()}
  maxLength={titleMaxLength}
  onUseTitle={(title) => setForm(current => ({ ...current, title }))}
/>
```

Persist the selected category contract's positive `settings.max_title_length` in a dedicated `titleMaxLength` state in `main.tsx`, and clear it when category changes. Disable generation until account, category, product identity, and that value exist. Show recommendation, alternatives, factual/trend signal copy, fallback copy, and a no-publication notice. The component must not import drafts, jobs, or publication APIs.

- [ ] **Step 3: Verify build and static side-effect boundary**

Run: `npm run build`

Expected: PASS.

Run: `rg -n "drafts|jobs|publication" frontend/src/title-intelligence`

Expected: no matches.

- [ ] **Step 4: Commit**

```powershell
git add frontend/src/title-intelligence frontend/src/main.tsx frontend/src/styles.css
git commit -m "feat: add title recommendation assistant"
```

### Task 5: Verify the full integration

**Files:**
- Modify: `README.md` only if the operator needs a real usage note.
- No new runtime code.

- [ ] **Step 1: Run full backend verification**

Run: `pytest backend/tests -v`

Expected: PASS.

- [ ] **Step 2: Run compile, migration, and frontend checks**

Run: `python -m compileall backend/app`

Expected: no errors.

Run: `cd backend; alembic current; alembic heads`

Expected: existing single head because this phase adds no persistence schema.

Run: `cd frontend; npm run build`

Expected: PASS.

- [ ] **Step 3: Scan for prohibited duplication and side effects**

Run: `rg -n "OpenAI|BeautifulSoup|redis|create_item|publication/jobs|drafts/generate" backend/app/title_intelligence frontend/src/title-intelligence`

Expected: no matches.

- [ ] **Step 4: Manual no-publication smoke test**

1. Select an account and category, then enter a factual product identity.
2. Generate a title and verify no absent material, brand, or feature appears.
3. Click “Usar título” and confirm only the form title changes.
4. Confirm draft and job counts do not change and no `POST /items` is emitted.
5. Repeat with unavailable trends and confirm a factual fallback is shown.

- [ ] **Step 5: Commit documentation only if it changed**

```powershell
git add README.md
git commit -m "docs: document title recommendation assistant"
```
