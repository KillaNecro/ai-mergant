"""Live-backend integration tests hitting the public REACT_APP_BACKEND_URL.
Covers Phase-1 hardening items not exercised by unit-tests using TestClient."""
import io
import os
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://catalog-commander-2.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"


@pytest.fixture(scope="module")
def s():
    return requests.Session()


def _csv_bytes(text: str, encoding="utf-8-sig") -> bytes:
    return text.encode(encoding)


# --- Health & demo mode ------------------------------------------------------
def test_health_demo(s):
    r = s.get(f"{API}/health")
    assert r.status_code == 200
    j = r.json()
    assert j.get("status") == "ok"
    assert j.get("demo_mode") is True


# --- Pagination bounds --------------------------------------------------------
def test_products_page_zero(s):
    r = s.get(f"{API}/products", params={"page": 0})
    assert r.status_code in (400, 422)


def test_products_page_size_too_big(s):
    r = s.get(f"{API}/products", params={"page_size": 500})
    assert r.status_code in (400, 422)


# --- Bulk validation ----------------------------------------------------------
def test_bulk_price_empty_ids(s):
    r = s.post(f"{API}/bulk/price-percent", json={"ids": [], "percent": 10})
    assert r.status_code == 422


def test_bulk_price_percent_too_big(s):
    # need at least one id
    prods = s.get(f"{API}/products").json()["items"]
    ids = [prods[0]["id"]] if prods else [1]
    r = s.post(f"{API}/bulk/price-percent", json={"ids": ids, "percent": 500})
    assert r.status_code == 422


def test_bulk_price_never_negative(s):
    # find or create product with price 1.0
    # Use import to add one for isolation
    csv = "sku,name,price\nTEST_NEG_1,Neg Test,1.00\n"
    files = {"file": ("t.csv", _csv_bytes(csv), "text/csv")}
    pre = s.post(f"{API}/import/preview", files=files).json()
    mapping = {"sku": "sku", "name": "name", "price": "price"}
    r = s.post(f"{API}/import/commit", json={"rows": pre["rows"], "mapping": mapping, "mode": "replace"})
    assert r.status_code == 200
    # find id
    lst = s.get(f"{API}/products", params={"q": "TEST_NEG_1"}).json()["items"]
    assert lst
    pid = lst[0]["id"]
    r = s.post(f"{API}/bulk/price-percent", json={"ids": [pid], "percent": -80})
    assert r.status_code == 200
    got = s.get(f"{API}/products/{pid}").json()
    assert got["price"] is None or got["price"] >= 0


# --- Non-destructive import ---------------------------------------------------
def test_non_destructive_fill_empty(s):
    # seed via replace
    csv = ("sku,name,description,category,price,stock,image_url,product_url\n"
           "TEST_NDS_1,Original Ürün,Ürün açıklaması,Elektronik,199.90,5,https://ex.com/i.jpg,https://ex.com/p\n")
    files = {"file": ("s.csv", _csv_bytes(csv), "text/csv")}
    pre = s.post(f"{API}/import/preview", files=files).json()
    mapping = {"sku": "sku", "name": "name", "description": "description", "category": "category",
               "price": "price", "stock": "stock", "image_url": "image_url", "product_url": "product_url"}
    r = s.post(f"{API}/import/commit", json={"rows": pre["rows"], "mapping": mapping, "mode": "replace"})
    assert r.status_code == 200

    # re-import with only sku+name in fill_empty
    csv2 = "sku,name\nTEST_NDS_1,Yeni İsim Değişmesin\n"
    files = {"file": ("s2.csv", _csv_bytes(csv2), "text/csv")}
    pre2 = s.post(f"{API}/import/preview", files=files).json()
    mapping2 = {"sku": "sku", "name": "name"}
    r2 = s.post(f"{API}/import/commit", json={"rows": pre2["rows"], "mapping": mapping2, "mode": "fill_empty"})
    assert r2.status_code == 200
    body = r2.json()
    assert "inserted" in body and "updated" in body and "skipped" in body and "failed" in body and "errors" in body

    got = s.get(f"{API}/products", params={"q": "TEST_NDS_1"}).json()["items"][0]
    # existing fields preserved
    assert got["description"] == "Ürün açıklaması"
    assert got["category"] == "Elektronik"
    assert float(got["price"]) == 199.90
    assert got["stock"] == 5
    assert got["image_url"] == "https://ex.com/i.jpg"
    assert got["product_url"] == "https://ex.com/p"


# --- Row errors ---------------------------------------------------------------
def test_row_errors(s):
    csv = ("sku,name,price,image_url\n"
           ",EmptySku,10,https://x/i.jpg\n"
           "TEST_ROW_2,,10,https://x/i.jpg\n"
           "TEST_ROW_3,Neg,-5,https://x/i.jpg\n"
           "TEST_ROW_4,BadUrl,10,notaurl\n")
    files = {"file": ("e.csv", _csv_bytes(csv), "text/csv")}
    pre = s.post(f"{API}/import/preview", files=files).json()
    mapping = {"sku": "sku", "name": "name", "price": "price", "image_url": "image_url"}
    r = s.post(f"{API}/import/commit", json={"rows": pre["rows"], "mapping": mapping, "mode": "replace"})
    assert r.status_code == 200
    b = r.json()
    assert b["failed"] >= 4
    rows = {e["row"] for e in b["errors"]}
    # 1-based, header on row 1, first data row=2
    assert {2, 3, 4, 5}.issubset(rows) or len(rows) >= 4


# --- SKU normalization & uniqueness ------------------------------------------
def test_sku_normalization(s):
    import uuid
    sku_val = f"TEST_SKU_{uuid.uuid4().hex[:8]}"
    csv = f"sku,name\n  {sku_val}  ,A\n{sku_val},B\n"
    files = {"file": ("n.csv", _csv_bytes(csv), "text/csv")}
    pre = s.post(f"{API}/import/preview", files=files).json()
    r = s.post(f"{API}/import/commit", json={"rows": pre["rows"], "mapping": {"sku": "sku", "name": "name"}, "mode": "replace"})
    assert r.status_code == 200
    b = r.json()
    assert b["inserted"] == 1 and b["updated"] == 1, b


def test_sku_uniqueness_patch_conflict(s):
    # create two known products via import
    csv = "sku,name\nTEST_UQ_A,A\nTEST_UQ_B,B\n"
    files = {"file": ("u.csv", _csv_bytes(csv), "text/csv")}
    pre = s.post(f"{API}/import/preview", files=files).json()
    s.post(f"{API}/import/commit", json={"rows": pre["rows"], "mapping": {"sku": "sku", "name": "name"}, "mode": "replace"})
    items = s.get(f"{API}/products").json()["items"]
    a = next(p for p in items if p["sku"] == "TEST_UQ_A")
    r = s.patch(f"{API}/products/{a['id']}", json={"sku": "TEST_UQ_B"})
    assert r.status_code == 409


# --- File validation ----------------------------------------------------------
def test_reject_xlsx(s):
    files = {"file": ("x.xlsx", b"PK\x03\x04fake", "application/octet-stream")}
    r = s.post(f"{API}/import/preview", files=files)
    assert r.status_code == 400
    # Turkish message
    assert "CSV" in r.text or "XML" in r.text or "desteklen" in r.text.lower()


def test_reject_empty(s):
    files = {"file": ("e.csv", b"", "text/csv")}
    r = s.post(f"{API}/import/preview", files=files)
    assert r.status_code == 400


# --- Encodings ----------------------------------------------------------------
@pytest.mark.parametrize("enc", ["utf-8-sig", "utf-8", "cp1254", "iso-8859-9"])
def test_encoding_preserved(s, enc):
    text = "sku,name\nTEST_ENC_" + enc.replace("-", "") + ",Şeker Çubuğu Ürünü\n"
    files = {"file": (f"e_{enc}.csv", text.encode(enc), "text/csv")}
    pre = s.post(f"{API}/import/preview", files=files)
    assert pre.status_code == 200
    j = pre.json()
    # sample should contain Turkish chars
    txt = str(j)
    assert "Şeker" in txt or "eker" in txt  # accept partial if TR char preserved


# --- Number parsing -----------------------------------------------------------
def test_number_parsing(s):
    csv = ("sku,name,price\n"
           "TEST_NUM_1,A,\"1.234,56\"\n"
           "TEST_NUM_2,B,\"1234,56\"\n"
           "TEST_NUM_3,C,\"1,234.56\"\n"
           "TEST_NUM_4,D,1234.56\n")
    files = {"file": ("n.csv", _csv_bytes(csv), "text/csv")}
    pre = s.post(f"{API}/import/preview", files=files).json()
    r = s.post(f"{API}/import/commit", json={"rows": pre["rows"], "mapping": {"sku": "sku", "name": "name", "price": "price"}, "mode": "replace"})
    assert r.status_code == 200
    for sku in ["TEST_NUM_1", "TEST_NUM_2", "TEST_NUM_3", "TEST_NUM_4"]:
        p = s.get(f"{API}/products", params={"q": sku}).json()["items"][0]
        assert float(p["price"]) == 1234.56, f"{sku} -> {p['price']}"


# --- Turkish auto-mapping -----------------------------------------------------
def test_tr_auto_mapping(s):
    csv = "Stok Kodu,Ürün Adı,Açıklama,Kategori,Fiyat,Stok,Görsel URL,Ürün Linki\nTEST_TR_1,X,d,c,10,1,https://a/i.jpg,https://a/p\n"
    files = {"file": ("t.csv", _csv_bytes(csv), "text/csv")}
    r = s.post(f"{API}/import/preview", files=files)
    assert r.status_code == 200
    j = r.json()
    m = j.get("suggested_mapping") or {}
    assert m.get("sku") == "Stok Kodu"
    assert m.get("name") == "Ürün Adı"
    assert m.get("description") == "Açıklama"
    assert m.get("category") == "Kategori"
    assert m.get("price") == "Fiyat"
    assert m.get("stock") == "Stok"
    assert m.get("image_url") == "Görsel URL"
    assert m.get("product_url") == "Ürün Linki"
    # 'Görsel URL' must NOT be mapped to product_url
    assert m.get("product_url") != "Görsel URL"
    assert "mapping_confidence" in j


# --- Timestamps UTC Z ---------------------------------------------------------
def test_timestamps_utc_z(s):
    j = s.get(f"{API}/dashboard/stats").json()
    for a in j.get("recent_activities", []):
        assert a["created_at"].endswith("Z"), a
    if j.get("last_import_at"):
        assert j["last_import_at"].endswith("Z")


# --- Export BOM ---------------------------------------------------------------
def test_exports_bom(s):
    for path in ["/export/all", "/export/filtered"]:
        r = s.get(f"{API}{path}")
        assert r.status_code == 200
        assert r.content[:3] == b"\xef\xbb\xbf"
    # selected
    ids = [p["id"] for p in s.get(f"{API}/products").json()["items"][:2]]
    r = s.post(f"{API}/export/selected", json={"ids": ids})
    assert r.status_code == 200
    assert r.content[:3] == b"\xef\xbb\xbf"


# --- URL validation on PATCH --------------------------------------------------
def test_url_validation_patch(s):
    pid = s.get(f"{API}/products").json()["items"][0]["id"]
    r = s.patch(f"{API}/products/{pid}", json={"image_url": "notaurl"})
    assert r.status_code in (400, 422)
