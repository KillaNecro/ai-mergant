"""Export CSV tests."""


def test_export_all_has_utf8_bom_and_turkish(client):
    rows = [{"sku": "EX-1", "name": "Ürün Şeker Çayı", "price": "12,50"}]
    client.post("/api/import/commit", json={
        "mapping": {"sku": "sku", "name": "name", "price": "price"},
        "rows": rows, "mode": "replace",
    })
    r = client.get("/api/export/all")
    assert r.status_code == 200
    # Response headers
    assert "charset=utf-8" in r.headers["content-type"]
    body = r.content
    assert body.startswith(b"\xef\xbb\xbf"), "must start with UTF-8 BOM"
    assert "Ürün Şeker Çayı".encode("utf-8") in body


def test_export_selected(client):
    rows = [{"sku": "EX-2", "name": "İkinci Ürün"}]
    client.post("/api/import/commit", json={
        "mapping": {"sku": "sku", "name": "name"},
        "rows": rows, "mode": "replace",
    })
    pid = client.get("/api/products").json()["items"][0]["id"]
    r = client.post("/api/export/selected", json={"ids": [pid]})
    assert r.status_code == 200
    assert b"EX-2" in r.content


def test_export_selected_empty_rejected(client):
    r = client.post("/api/export/selected", json={"ids": []})
    assert r.status_code == 422
