# AI Merchant OS Lite - PRD

## Original Problem Statement
Türkçe B2B e-ticaret için AI destekli ürün kataloğu yönetim MVP'si. Kullanıcılar CSV/XML yükler, ürünleri profesyonel dashboard'da görür, içerikleri iyileştirir ve CSV olarak dışa aktarır.

**User choices:** SQLite veritabanı · Demo Modu ile başla + kendi Gemini API anahtarını sağla · Karışık Türkçe ürün kategorileri.

## Architecture
- **Backend:** FastAPI + SQLAlchemy (SQLite). Tüm route'lar `/api` prefix altında.
- **Frontend:** React + Tailwind, Shadcn UI'den tablo/input yardımcıları, lucide-react ikonlar, sonner toast.
- **AI:** `ai_service.py` soyutlaması. `GEMINI_API_KEY` yoksa deterministik Türkçe Demo Modu; varsa `emergentintegrations` üzerinden Gemini.

## Personas
- **E-ticaret operasyon uzmanı**: yüzlerce ürünü tek panelden yönetir, eksik/kirli içerikleri toplu düzeltir.
- **Küçük işletme sahibi**: CSV feed'lerini yükleyip AI ile hızlıca profesyonel açıklama üretir.

## Core Requirements (static)
- Türkçe UI (Genel Bakış / Ürünler / İçe Aktar / Toplu İşlemler / Dışa Aktar / Ayarlar)
- UTF-8 BOM CSV desteği, Türkçe karakter koruması
- CSV + basit XML içe aktarım, kolon eşleştirme + önizleme
- Ürün editörü: orijinal vs iyileştirilmiş yan yana
- Bulk: başlık/açıklama iyileştir, kategori ata, fiyat %± , seçili dışa aktar
- Demo Modu badge (API anahtarı yoksa)
- Kimlik doğrulama, ödeme, çoklu tenant vb. YOK

## Implemented (2026-02-01)
- SQLite şeması: `products`, `activities`, `meta`
- 13 örnek Türkçe ürün seed (Elektronik, Giyim, Kozmetik, Ev & Yaşam, Spor - bazıları eksik açıklama/fiyat, kötü biçimli başlık)
- REST API: health, dashboard/stats, products CRUD + improve/revert, import preview/commit/sample, bulk improve/category/price-percent, export all/selected/filtered
- Frontend: sidebar layout, dashboard KPI + aktiviteler, ürün tablosu (arama+4 filtre+pagination), Product Editor modal (side-by-side + 5 aksiyon), Import (upload + auto-mapping + preview), BulkOps (5 aksiyon + tablo), Export (all/filtered/sample)
- Demo mode deterministik başlık temizleme (stopword, tekrar, karakter kodları koruma) + yapılandırılmış Türkçe açıklama üretici
- `.env.example`, `README.md`, requirements güncellendi
- Testing agent: %100 backend + %100 frontend

## Backlog (P0/P1/P2)
- P1: Gemini API anahtarını Ayarlar ekranından girme + backend'e yazma
- P1: XML importer için besleme formatları (Google Shopping XML) preset'i
- P1: Ürün düzenleme geçmişi (revizyon listesi)
- P2: Fiyat/stok toplu güncelleme için Excel (XLSX) desteği
- P2: Basit CSV önizleme sonrası satır bazlı hatalar (validation) raporu
- P2: Görsel URL'lerinin erişilebilirlik testi
