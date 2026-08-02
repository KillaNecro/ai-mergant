# AI Merchant OS Lite - PRD

## Product objective
Türkçe B2B e-ticaret için AI destekli ürün hazırlama iş akışı:
İçe aktarılan ürün → Kalite analizi → Sorunlar → AI önerisi → İnsan onayı → Yayına hazır.

Orijinal içeri aktarılan veri, AI önerisinden ve onaylanan içerikten her zaman ayrı tutulur.

## Architecture
- **Backend:** FastAPI + SQLite + SQLAlchemy + Alembic. Modules: `server.py`, `merchant_routes.py`, `merchant_service.py`, `quality_service.py`, `revision_service.py`, `ai_service.py`.
- **Frontend:** React + Tailwind. Sidebar layout preserved.
- **AI:** google-genai (Gemini) + deterministic Demo Mode. Provider failures → HTTP 502.
- **Testing:** 89 pytest tests, stable across 5 consecutive runs.

## Workflow states
- imported / needs_attention / ready_for_ai / awaiting_review / approved / ready_to_publish

## Implemented — Phase 3A Part A (2026-02, WooCommerce backend foundation)
- `.env.example` extended with `WOOCOMMERCE_URL`, `WOOCOMMERCE_CONSUMER_KEY`, `WOOCOMMERCE_CONSUMER_SECRET`, `WOOCOMMERCE_MODE=mock`, `WOOCOMMERCE_TIMEOUT_SECONDS=20`, `WOOCOMMERCE_VERIFY_SSL=true`, `APP_ENV`.
- Two new SQLAlchemy models with unique constraints + indexes:
  - `ProductPublication` (product_id, channel, external_product_id, external_url, publication_status, payload_snapshot, response_snapshot, last_error, attempt_count, timestamps).
  - `CategoryMapping` (channel, local_category, external_category_id, external_category_name, timestamps).
- Alembic migration `0003_woocommerce_integration` — additive only, preserves all existing rows, verified via downgrade/upgrade round-trip.
- `backend/integrations/woocommerce_client.py` — async `httpx` client with `WooCommerceConfig`, structured exception hierarchy, URL normalization, SSRF guard, redirect refusal, response-size cap, credential-masking `repr`, mock/live modes, `test_connection()` and `get_categories()` (deduped, paginated via `X-WP-TotalPages`, no partial success).
- `backend/woocommerce_routes.py` + `woocommerce_schemas.py` — router at `/api/integrations/woocommerce/*`:
  - `GET /status`, `POST /test`, `GET /categories`, `GET/POST/DELETE /category-mappings`.
  - Upsert on `POST`, 201/200 differentiated by outcome, mock-list validation of `external_category_id`, per-mutation Activity log, IntegrityError rollback + race-safe fallback.
  - Central `map_woocommerce_error_to_http_exception` mapper (400/401/403/429/502/504).
- 104 new tests (`test_woocommerce_client.py`, `test_woocommerce_routes.py`, `test_woocommerce_migration.py`) using `httpx.MockTransport`; autouse fixture blocks real network. Migration test runs `alembic upgrade/downgrade/upgrade` on a temp SQLite.
- **Total pytest**: **200 passed** (2 consecutive runs). All 96 legacy tests intact.

## Restrictions respected in Phase 3A Part A
No real WooCommerce/Gemini calls, no product publishing endpoints, no frontend changes, no new dependencies, no credential storage.

## Implemented — Phase 2.1 (2026-02, correctness fixes)
- **BUG 1** — Approval validates the **effective publish candidate** (approved suggestion + original SKU/price/stock/image/product URL). AI-supplied description resolves original MISSING_DESCRIPTION. Original imported fields never overwritten. `merchant_service.effective_candidate()`, `passes_publish_validation()` rewritten, new `would_publish_if_approved()`.
- **BUG 2** — Direct product PATCH now calls `merchant_service.analyze_and_transition`, refreshing issues, quality_score, workflow_status, and re-validating publish readiness. One activity entry.
- **BUG 3** — `/api/bulk/suggest` commits after each successful product and rolls back only the failing product's pending work. First-succeed-then-fail scenarios keep the first product's suggestion. Also fixed non-deterministic iteration order — bulk endpoints now iterate in `payload.ids` order (5/5 stable pytest runs).
- **BUG 4** — `/api/bulk/approve` pre-checks `would_publish_if_approved` before mutating. Draft suggestion untouched when candidate cannot become `ready_to_publish`; Turkish `Yayına hazır değil: …` reasons returned. Single-product approve still supports the `approved` intermediate state.

## Implemented — Phase 2 (Merchant Core)
- Alembic `0002_merchant_core` migration (idempotent)
- Deterministic quality engine, 17 issue codes
- AI suggestions (Demo + Gemini), never invents specs
- Human review workflow (approve/reject/edit/revert)
- Ready-to-publish CSV export
- Frontend: 4-tab ProductEditor, workflow filters, dashboard KPIs, BulkOps merchant actions

## Implemented — Phase 1 & Cleanup
- CSV/XML import with defusedxml, TR column mapping, encoding support
- Alembic-only migrations, UTC timestamps, SAVEPOINT accounting
- Trimmed requirements.txt, .gitignore covers *.db and .env

## Test result
```
cd backend && python -m pytest -q
200 passed
```
Stable across two consecutive runs. Includes 104 new tests for the WooCommerce foundation.

## Files changed (Phase 2.1)
- **Backend modified:** `merchant_service.py`, `merchant_routes.py`, `server.py`
- **Backend new:** `tests/test_phase2_1.py`
- **No frontend changes** (all four bugs backend-side)

## Known remaining issues (deferred)
- `server.py` + `merchant_routes.py` combined ~1000 lines — router package split still deferred
- `create_suggestion`'s auto-rejection of prior draft doesn't emit a separate revision entry (minor audit gap)
- Duplicate-title detection is O(N²) — fine at N<10k
- Legacy Phase 1 products stay `imported` until user triggers Analyze All

## Restrictions respected
No auth, no payments, no marketplace integrations, no image gen, no XLSX, no Redis/Celery, no multi-tenant, no visual rebrand, no overwriting of original imported data.
