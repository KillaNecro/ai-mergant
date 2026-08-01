"""Tests for CSV/XML import behaviour."""
import io


def _upload(client, filename: str, content: bytes, content_type: str):
    return client.post(
        "/api/import/preview",
        files={"file": (filename, io.BytesIO(content), content_type)},
    )


def test_csv_preview_utf8_bom(client):
    csv = "\ufeffsku,name,description,price\nABC-1,Ürün Şeker,Açıklama,19,90\n".encode("utf-8")
    r = _upload(client, "urunler.csv", csv, "text/csv")
    assert r.status_code == 200
    data = r.json()
    assert data["format"] == "csv"
    assert "sku" in data["suggested_mapping"]
    assert data["total_rows"] == 1
    assert data["rows"][0]["name"] == "Ürün Şeker"


def test_csv_windows_1254_encoding(client):
    text = "sku;name;price\r\nSKU-1;Türkçe Ürün;1.299,90\r\n"
    content = text.encode("cp1254")
    r = _upload(client, "tr.csv", content, "text/csv")
    assert r.status_code == 200, r.text
    assert r.json()["rows"][0]["name"] == "Türkçe Ürün"


def test_reject_unsupported_extension(client):
    r = _upload(client, "veri.xlsx", b"binary", "application/octet-stream")
    assert r.status_code == 400
    assert "Desteklenmeyen" in r.json()["detail"]


def test_reject_empty_file(client):
    r = _upload(client, "bos.csv", b"", "text/csv")
    assert r.status_code == 400


def test_reject_no_header(client):
    r = _upload(client, "no_header.csv", b"\n\n", "text/csv")
    assert r.status_code == 400


def test_commit_partial_update_preserves_unmapped_fields(client):
    # Seed one product via commit
    seed_csv = "sku,name,description,category,price,stock\nSKU-1,Adı,Açıklama,Kategori,100,10\n".encode("utf-8")
    r = _upload(client, "seed.csv", seed_csv, "text/csv")
    rows = r.json()["rows"]
    mapping = {
        "sku": "sku", "name": "name", "description": "description",
        "category": "category", "price": "price", "stock": "stock",
    }
    client.post("/api/import/commit", json={"mapping": mapping, "rows": rows, "mode": "replace"})

    # Now re-upload with only sku+name; category/price MUST be preserved
    partial = "sku,name\nSKU-1,Yeni Ad\n".encode("utf-8")
    r2 = _upload(client, "partial.csv", partial, "text/csv")
    rows2 = r2.json()["rows"]
    commit = client.post("/api/import/commit", json={
        "mapping": {"sku": "sku", "name": "name"},
        "rows": rows2,
        "mode": "fill_empty",
    })
    assert commit.status_code == 200
    products = client.get("/api/products").json()["items"]
    p = next(p for p in products if p["sku"] == "SKU-1")
    # description/category/price preserved
    assert p["description"] == "Açıklama"
    assert p["category"] == "Kategori"
    assert p["price"] == 100.0


def test_commit_rejects_missing_sku_mapping(client):
    r = client.post("/api/import/commit", json={
        "mapping": {"name": "name"},
        "rows": [{"name": "X"}],
    })
    assert r.status_code == 400
    assert "SKU" in r.json()["detail"]


def test_commit_reports_row_errors(client):
    rows = [
        {"sku": "OK-1", "name": "Ürün 1", "price": "10,50"},
        {"sku": "", "name": "Ürün 2"},              # invalid: sku empty
        {"sku": "OK-3", "name": "", "price": "5"},  # invalid: name empty
        {"sku": "OK-4", "name": "Ürün 4", "price": "-1"},  # invalid: negative
    ]
    r = client.post("/api/import/commit", json={
        "mapping": {"sku": "sku", "name": "name", "price": "price"},
        "rows": rows, "mode": "replace",
    })
    body = r.json()
    assert body["inserted"] == 1
    assert body["failed"] == 3
    assert len(body["errors"]) == 3
    row_nums = [e["row"] for e in body["errors"]]
    assert row_nums == [2, 3, 4]


def test_sku_normalization_and_uniqueness(client):
    rows = [
        {"sku": "  SKU-9 ", "name": "Ürün A"},
        {"sku": "SKU-9", "name": "Ürün B"},  # same SKU after normalization → updates
    ]
    r = client.post("/api/import/commit", json={
        "mapping": {"sku": "sku", "name": "name"},
        "rows": rows, "mode": "replace",
    })
    body = r.json()
    assert body["inserted"] == 1
    assert body["updated"] == 1
    products = client.get("/api/products", params={"q": "SKU-9"}).json()["items"]
    assert len(products) == 1
    assert products[0]["sku"] == "SKU-9"


def test_number_parsing_formats(client):
    rows = [
        {"sku": "N-1", "name": "A", "price": "1.234,56"},
        {"sku": "N-2", "name": "B", "price": "1,234.56"},
        {"sku": "N-3", "name": "C", "price": "1234,56"},
        {"sku": "N-4", "name": "D", "price": "1234.56"},
    ]
    r = client.post("/api/import/commit", json={
        "mapping": {"sku": "sku", "name": "name", "price": "price"},
        "rows": rows, "mode": "replace",
    })
    assert r.json()["inserted"] == 4
    prices = {p["sku"]: p["price"] for p in client.get("/api/products").json()["items"]}
    assert prices["N-1"] == 1234.56
    assert prices["N-2"] == 1234.56
    assert prices["N-3"] == 1234.56
    assert prices["N-4"] == 1234.56


def test_turkish_column_auto_mapping(client):
    csv = "Stok Kodu,Ürün Adı,Açıklama,Kategori,Fiyat,Stok,Görsel URL,Ürün Linki\n".encode("utf-8")
    csv += "TR-1,Deneme,Metin,Elektronik,1.999,00,5,https://x/y.jpg,https://x/y\n".encode("utf-8")
    r = _upload(client, "tr.csv", csv, "text/csv")
    m = r.json()["suggested_mapping"]
    assert m["sku"] == "Stok Kodu"
    assert m["name"] == "Ürün Adı"
    assert m["description"] == "Açıklama"
    assert m["category"] == "Kategori"
    assert m["price"] == "Fiyat"
    assert m["stock"] == "Stok"
    assert m["image_url"] == "Görsel URL"
    assert m["product_url"] == "Ürün Linki"
    # Görsel URL must NOT be mapped to product_url
    assert m["product_url"] != "Görsel URL"
