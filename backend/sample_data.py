"""Seed 12+ realistic Turkish e-commerce sample products."""
from database import SessionLocal
from models import Product, Activity, Meta
from datetime import datetime, timezone


SAMPLES = [
    {
        "sku": "ELK-001",
        "name": "SAMSUNG Galaxy A55 128GB Akıllı Telefon Siyah",
        "description": "6.6 inç Super AMOLED ekran, 50MP kamera, 5000 mAh batarya.",
        "category": "Elektronik",
        "price": 18999.90,
        "stock": 24,
        "image_url": "https://images.unsplash.com/photo-1511707171634-5f897ff02aa9?w=200",
        "product_url": "https://example.com/urun/samsung-a55",
    },
    {
        "sku": "ELK-002",
        "name": "apple airpods pro 2 kablosuz kulaklık!!!",
        "description": None,
        "category": "Elektronik",
        "price": None,
        "stock": 8,
        "image_url": "https://images.unsplash.com/photo-1606220945770-b5b6c2c55bf1?w=200",
        "product_url": "https://example.com/urun/airpods-pro-2",
    },
    {
        "sku": "GIY-101",
        "name": "Erkek Slim Fit Pamuklu Basic Tişört Beyaz M Beden",
        "description": "%100 pamuk, bisiklet yaka, günlük kullanım için ideal.",
        "category": "Giyim",
        "price": 249.00,
        "stock": 120,
        "image_url": "https://images.unsplash.com/photo-1521572163474-6864f9cf17ab?w=200",
        "product_url": "https://example.com/urun/basic-tshirt",
    },
    {
        "sku": "GIY-102",
        "name": "kadın deri ceket siyah 38 beden yeni yeni yeni",
        "description": "",
        "category": "Giyim",
        "price": 2499.00,
        "stock": 3,
        "image_url": "https://images.unsplash.com/photo-1551028719-00167b16eac5?w=200",
        "product_url": "https://example.com/urun/deri-ceket",
    },
    {
        "sku": "KOZ-201",
        "name": "L'Oreal Paris Elseve Onarıcı Şampuan 450ml",
        "description": "Yıpranmış saçlar için onarıcı bakım, keratin içerir.",
        "category": "Kozmetik",
        "price": 129.90,
        "stock": 65,
        "image_url": "https://images.unsplash.com/photo-1585386959984-a4155224a1ad?w=200",
        "product_url": "https://example.com/urun/elseve-sampuan",
    },
    {
        "sku": "KOZ-202",
        "name": "MAC Ruby Woo Ruj Mat Kırmızı",
        "description": None,
        "category": "Kozmetik",
        "price": 749.00,
        "stock": 2,
        "image_url": "https://images.unsplash.com/photo-1586495777744-4413f21062fa?w=200",
        "product_url": "https://example.com/urun/mac-ruby-woo",
    },
    {
        "sku": "EV-301",
        "name": "IKEA MALM Çekmeceli Şifonyer 80x48 cm Beyaz",
        "description": "6 çekmeceli, kolay montaj, dayanıklı yapı.",
        "category": "Ev & Yaşam",
        "price": 4499.00,
        "stock": 12,
        "image_url": "https://images.unsplash.com/photo-1555041469-a586c61ea9bc?w=200",
        "product_url": "https://example.com/urun/malm-sifonyer",
    },
    {
        "sku": "EV-302",
        "name": "Karaca Emaye Tencere Seti 7 Parça",
        "description": "",
        "category": "Ev & Yaşam",
        "price": None,
        "stock": 40,
        "image_url": "https://images.unsplash.com/photo-1584990347449-a1a3a13d0f4e?w=200",
        "product_url": "https://example.com/urun/karaca-tencere",
    },
    {
        "sku": "SPR-401",
        "name": "NIKE Air Zoom Pegasus 40 Erkek Koşu Ayakkabısı 42",
        "description": "Hafif ve nefes alabilir yapı, uzun mesafe koşular için üretildi.",
        "category": "Spor",
        "price": 3899.00,
        "stock": 18,
        "image_url": "https://images.unsplash.com/photo-1542291026-7eec264c27ff?w=200",
        "product_url": "https://example.com/urun/pegasus-40",
    },
    {
        "sku": "SPR-402",
        "name": "yoga matı 6mm mor renk kaydırmaz",
        "description": None,
        "category": "Spor",
        "price": 299.90,
        "stock": 5,
        "image_url": "https://images.unsplash.com/photo-1518611012118-696072aa579a?w=200",
        "product_url": "https://example.com/urun/yoga-mati",
    },
    {
        "sku": "ELK-003",
        "name": "LG 55UR7500 55 inç 4K UHD Smart TV",
        "description": "webOS 23, HDR10 Pro, AI ThinQ desteği.",
        "category": "Elektronik",
        "price": 22499.00,
        "stock": 6,
        "image_url": "https://images.unsplash.com/photo-1593359677879-a4bb92f829d1?w=200",
        "product_url": "https://example.com/urun/lg-55ur7500",
    },
    {
        "sku": "GIY-103",
        "name": "Çocuk Kışlık Mont Su Geçirmez 8 Yaş Lacivert",
        "description": "İç astarlı, kapüşonlu, su ve rüzgar geçirmez dış yüzey.",
        "category": "Giyim",
        "price": 899.00,
        "stock": 32,
        "image_url": "https://images.unsplash.com/photo-1544966503-7cc5ac882d5f?w=200",
        "product_url": "https://example.com/urun/cocuk-mont",
    },
    {
        "sku": "KOZ-203",
        "name": "Nivea Nemlendirici El Kremi 100ml",
        "description": "",
        "category": "Kozmetik",
        "price": 79.90,
        "stock": 150,
        "image_url": "https://images.unsplash.com/photo-1556228720-195a672e8a03?w=200",
        "product_url": "https://example.com/urun/nivea-el-kremi",
    },
]


def seed(db):
    if db.query(Product).count() > 0:
        return 0
    now = datetime.now(timezone.utc)
    for s in SAMPLES:
        db.add(Product(**s))
    db.add(Activity(kind="import", message=f"Örnek veri yüklendi ({len(SAMPLES)} ürün)"))
    db.merge(Meta(key="last_import_at", value=now.isoformat()))
    db.commit()
    return len(SAMPLES)
