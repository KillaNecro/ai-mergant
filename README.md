# AI Merchant OS Lite

Türkçe e-ticaret işletmeleri için AI destekli ürün kataloğu yönetim aracı MVP'si.

## Özellikler

- CSV / XML ürün içe aktarımı (kolon eşleştirme + önizleme)
- Ürün kataloğu (arama, filtre, sayfalama)
- Ürün editörü (orijinal vs. iyileştirilmiş yan yana)
- Toplu işlemler (başlık/açıklama iyileştir, fiyat/kategori güncelle)
- UTF-8 CSV dışa aktarımı (Türkçe karakter korunur)
- Demo Modu (API anahtarı olmadan çalışır) veya Gemini entegrasyonu

## Yerel Kurulum

### Gereksinimler
- Python 3.10+
- Node.js 18+
- Yarn

### Backend

```bash
cd backend
cp .env.example .env  # opsiyonel: GEMINI_API_KEY girin
pip install -r requirements.txt
uvicorn server:app --host 0.0.0.0 --port 8001 --reload
```

### Frontend

```bash
cd frontend
yarn install
yarn start
```

Uygulama http://localhost:3000 adresinde açılır ve `REACT_APP_BACKEND_URL` üzerinden backend'e istek atar.

## Ortam Değişkenleri

`backend/.env.example` içindekiler:

- `GEMINI_API_KEY` - Boş bırakılırsa Demo Modu etkinleşir.
- `SQLITE_PATH` - Varsayılan `./merchant_os.db`.
- `CORS_ORIGINS` - Virgülle ayrılmış, varsayılan `*`.

## Klasör Yapısı

```
backend/
  server.py         FastAPI ana uygulama + REST endpointleri
  database.py       SQLAlchemy + SQLite bağlantısı
  models.py         Product / Activity / Meta modelleri
  ai_service.py     Demo modu + Gemini entegrasyonu
  sample_data.py    Örnek Türkçe ürünler
  requirements.txt
frontend/
  src/pages/        Genel Bakış, Ürünler, İçe Aktar, Toplu, Dışa Aktar, Ayarlar
  src/components/   Layout, Sidebar, ProductEditor
```
