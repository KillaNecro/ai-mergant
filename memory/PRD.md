# AI Merchant OS Lite - PRD

## Product objective
Türkçe B2B e-ticaret için AI destekli ürün hazırlama iş akışı:
İçe aktarılan ürün → Kalite analizi → Sorunlar → AI önerisi → İnsan onayı → Yayına hazır.

Orijinal içeri aktarılan veri, AI önerisinden ve onaylanan içerikten her zaman ayrı tutulur.

## Architecture (Phase 2)
- **Backend:** FastAPI + SQLite + SQLAlchemy + Alembic. Modules: `server.py`, `merchant_routes.py`, `merchant_service.py`, `quality_service.py`, `revision_service.py`, `ai_service.py`.
- **Frontend:** React + Tailwind, sidebar layout preserved.
- **AI:** google-genai (Gemini) + deterministic Demo Mode. Provider failures raise `AIProviderError` → HTTP 502.
- **Testing:** 81 pytest tests, all green. Frontend production build clean.

## Data model (Phase 2 additions)
- `Product`: `workflow_status`, `quality_score`, `quality_analyzed_at`, `active_suggestion_id`
- `ProductIssue`: id, product_id, issue_code, field_name, severity, message, recommendation, is_resolved, timestamps
- `ProductSuggestion`: id, product_id, suggested_* fields, provider, model, suggestion_status, timestamps
- `ProductRevision`: id, product_id, action_type, source, before_snapshot, after_snapshot, created_at

## Workflow states (Turkish labels)
- `imported` → İçe Aktarıldı
- `needs_attention` → Dikkat Gerekiyor (critical issues or score<60)
- `ready_for_ai` → AI İçin Hazır (score≥60, no suggestion)
- `awaiting_review` → İnceleme Bekliyor (draft suggestion)
- `approved` → Onaylandı (approved but validation blocking)
- `ready_to_publish` → Yayına Hazır (approved + validation ok)

## Implemented (2026-02 · Phase 2)
**Backend**
- Alembic `0002_merchant_core` (idempotent, preserves Phase 1 data)
- Deterministic `quality_service.py` — 17 issue codes with stable weights; single source of truth for scoring
- `merchant_service.py` — workflow transitions, create/edit/approve/reject suggestions, revert
- `revision_service.py` — JSON snapshots
- `ai_service.generate_suggestion` — demo (deterministic-v1) + Gemini JSON output, never invents specs
- `merchant_routes.py` — 13 new endpoints (analyze, issues, suggest, patch, approve, reject, revisions, revert, bulk×4, ready-to-publish export)
- Auto-analyze on import
- Dashboard stats extended (average_quality_score, workflow buckets, open_critical_issues)
- Product list filters: workflow_status, score_bucket (low/mid/high/critical)

**Frontend**
- Dashboard: 8 new KPIs (Ortalama Kalite, Dikkat Gerekiyor, İnceleme Bekliyor, Onaylandı, Yayına Hazır, Kritik Sorun, etc.)
- Products table: quality/issue-count/status columns; workflow + score filters
- ProductEditor: 4 tabs (Orijinal Veri, AI Önerisi, Kalite Analizi, Revizyon Geçmişi) with side-by-side comparison for name/desc/category/SEO/meta/tags; buttons Kaliteyi Analiz Et, AI Önerisi Oluştur, Öneriyi Kaydet, Onayla, Reddet, Önceki Sürüme Dön
- Export: "Yayına Hazır Ürünleri Dışa Aktar" card
- BulkOps: 4 new merchant actions (analyze/suggest/approve/reject) with confirmation dialogs

## Testing
```
cd backend && python -m pytest -q
81 passed
```
Coverage: import safety (Phase 1 preserved), quality engine, workflow transitions, AI failure surfacing, revisions/revert, bulk approve eligibility, ready-to-publish export.

## Known remaining issues (Phase 3 candidates)
- server.py + merchant_routes.py combined is ~1000 lines — router package split deferred
- Bulk API request schemas need OpenAPI descriptions
- Duplicate-title detection is O(N²); acceptable at N<10k but should switch to indexed subquery later
- Migration doesn't run analysis for legacy products; they remain `imported` until user clicks "Analyze All"

## Restrictions (respected)
No auth, no payments, no Stripe/Woo/İkas/Shopier/Instagram/Meta, no image gen, no XLSX, no Redis/Celery, no multi-tenant, no visual rebrand.

## Backlog (Phase 3+)
- P1: Gemini key entry from Ayarlar UI
- P1: Router split (`routers/` package)
- P1: XLSX import
- P2: Automated analyze-on-schedule for legacy data
- P2: Multi-language suggestion output
- P2: Product-image validation ping check
