# AI Merchant OS Lite

Türkçe e-ticaret işletmeleri için AI destekli ürün kataloğu yönetim aracı MVP'si.

## Özellikler
- CSV / XML ürün içe aktarımı (kolon eşleştirme, güven skoru, önizleme, satır bazlı hata raporu)
- Ürün kataloğu (arama, filtre, sayfalama, sayfa bazlı toplu seçim)
- Ürün editörü (orijinal vs iyileştirilmiş yan yana, geri alma)
- Toplu işlemler (başlık/açıklama iyileştir, kategori ata, fiyat %± , dışa aktar)
- UTF-8 BOM CSV dışa aktarımı (Türkçe karakter korunur)
- Demo Modu (deterministik) veya Gemini entegrasyonu (google-genai SDK)
- Alembic ile veritabanı migrasyonu, SQLite tekil SKU kısıtı
- pytest ile otomatik test paketi

## Yerel Kurulum

### Gereksinimler
- Python 3.10+
- Node.js 18+
- Yarn

### Backend

```bash
cd backend
cp .env.example .env                 # opsiyonel: GEMINI_API_KEY girin
pip install -r requirements.txt
alembic upgrade head                 # veritabanı migrasyonu
uvicorn server:app --host 0.0.0.0 --port 8001 --reload
```

### Frontend

```bash
cd frontend
cp .env.example .env
yarn install
yarn start
```

Uygulama `http://localhost:3000` adresinde açılır ve `REACT_APP_BACKEND_URL` üzerinden backend'e istek atar (varsayılan: `http://localhost:8001`).

### Testleri Çalıştırma

```bash
cd backend
pytest -q
```

Testler geçici bir SQLite dosyası kullanır ve geliştirme veritabanını değiştirmez.

### Frontend Production Build

```bash
cd frontend
yarn build
```

## Ortam Değişkenleri

`backend/.env.example`:
- `GEMINI_API_KEY` - Boş bırakılırsa Demo Modu etkinleşir.
- `GEMINI_MODEL` - Varsayılan `gemini-2.0-flash`.
- `SQLITE_PATH` - Varsayılan `./merchant_os.db`.
- `CORS_ORIGINS` - Virgülle ayrılmış, varsayılan `*`.
- `IMPORT_MAX_FILE_MB` - İçe aktarma dosya boyutu limiti (varsayılan 10 MB).
- `IMPORT_MAX_ROWS` - Maksimum satır sayısı (varsayılan 10000).
- `BULK_PRICE_PERCENT_LIMIT` - Toplu fiyat yüzdesi sınırı (varsayılan 90).

`frontend/.env.example`:
- `REACT_APP_BACKEND_URL` - Backend URL. Yerel geliştirme fallback'i `http://localhost:8001`.

## Klasör Yapısı

```
backend/
  server.py           FastAPI + REST endpointleri
  database.py         SQLAlchemy + SQLite bağlantısı
  models.py           Product / Activity / Meta modelleri (SKU unique)
  ai_service.py       Demo modu + Gemini entegrasyonu (google-genai)
  sample_data.py      Örnek Türkçe ürünler (idempotent seed)
  alembic.ini
  alembic/
    env.py
    versions/0001_initial.py
  tests/
    test_import.py, test_products.py, test_export.py, test_ai.py, test_xml.py
  requirements.txt
frontend/
  src/pages/          Genel Bakış, Ürünler, İçe Aktar, Toplu, Dışa Aktar, Ayarlar
  src/components/     Layout, Sidebar, ProductEditor
```
