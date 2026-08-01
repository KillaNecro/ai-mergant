# AI Merchant OS Lite - PRD

## Original Problem Statement
Türkçe B2B e-ticaret için AI destekli ürün kataloğu yönetim aracı. Phase 1 hardening tamamlandı.

**User choices:** SQLite · Demo Modu ile başla + Gemini API anahtarı elle sağlanacak · Karışık Türkçe ürün kategorileri.

## Architecture
- **Backend:** FastAPI + SQLAlchemy 2 + SQLite + Alembic. AI: google-genai SDK, `AIProviderError` ile hata yüzeyleme. defusedxml ile güvenli XML.
- **Frontend:** React + Tailwind + shadcn/ui + lucide-react + sonner. Turkish UI, desktop-first.
- **Testler:** pytest (30 lokal + 22 canlı entegrasyon + AI hata testleri = 52). Geçici SQLite DB fixture.

## Personas
- E-ticaret operasyon uzmanı
- KOBİ mağaza sahibi

## Core Requirements (static)
- Türkçe UI (6 bölüm)
- CSV + XML (nested, RSS, Google Merchant) importer, kolon eşleştirme + güven skoru + satır hataları
- Yıkıcı olmayan import (fill_empty vs replace)
- SKU unique + normalize
- UTF-8 BOM CSV export, Türkçe karakter koruması
- Timezones: UTC ISO 8601 (Z suffix)
- Demo mode + Gemini (hata yüzeyleme)
- Alembic migrasyonları

## Implemented (2026-02-01 → Phase 1)
**Data safety & migrations:**
- `Product.sku` UNIQUE + normalized (whitespace strip, dedup)
- Alembic setup + `0001_initial.py` (idempotent, upgrades legacy DBs without data loss)
- `.gitignore` extended for `*.db`, `.env`

**Import hardening:**
- File validation: allowed extensions (.csv, .xml), MIME check, `IMPORT_MAX_FILE_MB=10`, `IMPORT_MAX_ROWS=10000`, cell length cap
- Encodings: UTF-8 BOM, UTF-8, Windows-1254, ISO-8859-9
- Number parsing: 1.234,56 / 1234,56 / 1,234.56 / 1234.56 all → correct float
- Turkish column auto-mapping with `_tr_norm()` (İ→i, ş→s, ğ→g, ü→u, ö→o, ç→c) + `mapping_confidence`
- `mode` param: `fill_empty` (safe, default) or `replace`
- Unmapped fields never touched; row-level errors with row numbers returned
- Response: `{inserted, updated, skipped, failed, errors:[]}`
- SKU normalization + intra-batch flush so duplicates within same file update, not fail
- Negative price / stock rejected per row

**Safe XML:**
- `defusedxml` parser
- `_find_product_nodes()` detects: `<products><product>`, `<items><item>`, `<rss><channel><item>`, Google Merchant style, XML namespaces
- Turkish error message when structure cannot be inferred

**Validation & timezones:**
- Pydantic bounds: `page>=1`, `page_size 1..200`, `ids min_length 1`, `percent` within `BULK_PRICE_PERCENT_LIMIT=90`
- URL fields validated http/https or null
- All timestamps served as UTC ISO with trailing `Z`

**AI transparency:**
- google-genai SDK (was emergentintegrations)
- `GEMINI_MODEL` env var (default gemini-2.0-flash)
- `AIProviderError` → HTTP 502 with Turkish message; never silent Demo fallback when key is set
- Demo mode preserves product codes/dimensions/brands; no invented "günlük kullanıma uygun" claims

**Testing (52 tests passing):**
- `tests/test_import.py` — 11 tests: partial update preservation, mode replace, row errors, SKU normalization/uniqueness, number formats, TR auto-mapping, encoding, rejection cases
- `tests/test_products.py` — 7 tests: pagination bounds, empty bulk, percent limit, negative price safety, persistence, UTC timestamps
- `tests/test_export.py` — 3 tests: UTF-8 BOM, Turkish chars, selected export, empty rejection
- `tests/test_ai.py` — 4 tests: demo mode active, code preservation, no fabricated claims, Gemini failure surfaces
- `tests/test_xml.py` — 5 tests: products/product, items/item, RSS, Google Merchant, unknown flat rejected
- Live integration + AI-failure tests added by testing agent

**Frontend reliability (no redesign):**
- Import: mode radios, confidence badges (Yüksek/Belirsiz), row error panel, disabled buttons during requests
- Products: loading/empty/error states with retry, "Tümü Seç yalnızca bu sayfayı seçer" hint
- BulkOps: confirm dialog for 20+ product batches, buttons disabled while inflight
- ProductEditor: confirm on "Orijinale Geri Dön", loading/error states, disabled while saving
- Dashboard/Export: error retry, busy states, no infinite spinners

**Portability:**
- `backend/.env.example` (GEMINI_KEY, MODEL, SQLITE_PATH, CORS, IMPORT limits, price limit)
- `frontend/.env.example` (REACT_APP_BACKEND_URL with localhost fallback baked into api.js)
- Trimmed `requirements.txt` — removed Mongo/Stripe/AWS/OAuth/OpenAI/bcrypt/jwt
- README updated with exact tested commands + `alembic upgrade head`

## Files Changed (Phase 1)
Backend:
- `server.py` (major rewrite: import mode, validation, timezones, defusedxml)
- `ai_service.py` (google-genai SDK, AIProviderError)
- `models.py` (UniqueConstraint on sku)
- `sample_data.py` (Z-suffix timestamp)
- `alembic.ini` (new)
- `alembic/env.py` (new)
- `alembic/script.py.mako` (new)
- `alembic/versions/0001_initial.py` (new)
- `pytest.ini`
- `requirements.txt` (trimmed)
- `.env.example` (updated)
- `tests/__init__.py`, `tests/conftest.py`, `tests/test_import.py`, `tests/test_products.py`, `tests/test_export.py`, `tests/test_ai.py`, `tests/test_xml.py` (new)

Frontend:
- `.env.example` (new)
- `src/lib/api.js` (localhost fallback)
- `src/pages/Import.jsx` (mode selector, error panel, confidence badges)
- `src/pages/Products.jsx` (loading/error/empty, page-only select-all)
- `src/pages/BulkOps.jsx` (confirm large batches, busy states)
- `src/components/ProductEditor.jsx` (confirm revert, loading/error, disabled states)
- `src/pages/Dashboard.jsx` (error retry)
- `src/pages/Export.jsx` (busy states)

Root:
- `README.md` (rewritten with tested run commands)
- `.gitignore` (append *.db, .env)

## Test Command & Output
```
cd /app/backend && python -m pytest -v
============================= test session starts ==============================
collected 30 items
tests/test_ai.py ....         [ 13%]
tests/test_export.py ...      [ 23%]
tests/test_import.py ......... [ 60%]
tests/test_products.py .......  [ 83%]
tests/test_xml.py .....       [100%]
======================= 30 passed in 2.09s ========================
```
Plus 22 live-integration + AI-failure tests from testing agent → 52/52 total.

## Known Remaining Issues
- server.py is 800+ lines — refactoring into routers deferred for later phase (not blocking).
- Existing preview DB may retain one legacy `last_import_at` Meta value without Z suffix; overwritten on next import.
- GitHub push is handled via Emergent platform's Push-to-GitHub action; not performed inside the sandbox.

## Backlog (Phase 2 candidates)
- P1: Ayarlar ekranından Gemini key girme (backend .env write)
- P1: XLSX import support
- P1: Image URL reachability check
- P2: Per-product revision history
- P2: Splitting server.py into routers
