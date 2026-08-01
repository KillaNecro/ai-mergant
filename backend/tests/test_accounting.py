"""Integration tests for Phase 1 cleanup accounting behaviour."""
import io


def _seed_full(client, sku="P-1"):
    """Insert one product with every field populated."""
    rows = [{
        "sku": sku, "name": "Ad", "description": "Açıklama",
        "category": "Kategori", "price": "100", "stock": "5",
        "image_url": "https://example.com/x.jpg", "product_url": "https://example.com/p",
    }]
    r = client.post("/api/import/commit", json={
        "mapping": {
            "sku": "sku", "name": "name", "description": "description",
            "category": "category", "price": "price", "stock": "stock",
            "image_url": "image_url", "product_url": "product_url",
        },
        "rows": rows,
        "mode": "replace",
    })
    assert r.status_code == 200
    assert r.json()["inserted"] == 1


def test_no_change_counts_as_skipped(client):
    _seed_full(client)
    # Re-import the exact same values in replace mode → nothing changes.
    rows = [{"sku": "P-1", "name": "Ad", "price": "100"}]
    r = client.post("/api/import/commit", json={
        "mapping": {"sku": "sku", "name": "name", "price": "price"},
        "rows": rows,
        "mode": "replace",
    })
    body = r.json()
    assert body["inserted"] == 0
    assert body["updated"] == 0
    assert body["skipped"] == 1
    assert body["failed"] == 0


def test_single_field_change_counts_as_updated(client):
    _seed_full(client)
    rows = [{"sku": "P-1", "name": "Yeni Ad"}]
    r = client.post("/api/import/commit", json={
        "mapping": {"sku": "sku", "name": "name"},
        "rows": rows,
        "mode": "replace",
    })
    body = r.json()
    assert body["updated"] == 1
    assert body["skipped"] == 0


def test_failed_row_does_not_undo_prior_success(client):
    """A failing row must not roll back previously successful inserts/updates."""
    rows = [
        {"sku": "OK-A", "name": "İlk Ürün", "price": "10"},
        {"sku": "", "name": "Bozuk"},               # ValueError: empty SKU
        {"sku": "OK-B", "name": "İkinci Ürün"},
        {"sku": "OK-C", "name": "Üçüncü", "price": "-5"},  # ValueError: negative
        {"sku": "OK-D", "name": "Dördüncü"},
    ]
    r = client.post("/api/import/commit", json={
        "mapping": {"sku": "sku", "name": "name", "price": "price"},
        "rows": rows,
        "mode": "replace",
    })
    body = r.json()
    assert body["inserted"] == 3       # OK-A, OK-B, OK-D
    assert body["failed"] == 2
    row_nums = [e["row"] for e in body["errors"]]
    assert row_nums == [2, 4]
    # And the survivors are actually persisted:
    skus = {p["sku"] for p in client.get("/api/products").json()["items"]}
    assert {"OK-A", "OK-B", "OK-D"}.issubset(skus)
    assert "OK-C" not in skus


def test_fill_empty_preserves_non_empty_stock(client):
    _seed_full(client)  # stock=5
    rows = [{"sku": "P-1", "name": "Ad", "stock": "99"}]
    r = client.post("/api/import/commit", json={
        "mapping": {"sku": "sku", "name": "name", "stock": "stock"},
        "rows": rows,
        "mode": "fill_empty",
    })
    body = r.json()
    # stock=5 is already non-empty → fill_empty must NOT overwrite it.
    assert body["skipped"] == 1
    assert body["updated"] == 0
    pid = client.get("/api/products").json()["items"][0]["id"]
    p = client.get(f"/api/products/{pid}").json()
    assert p["stock"] == 5


def test_replace_mode_overwrites_stock(client):
    _seed_full(client)
    rows = [{"sku": "P-1", "name": "Ad", "stock": "99"}]
    r = client.post("/api/import/commit", json={
        "mapping": {"sku": "sku", "name": "name", "stock": "stock"},
        "rows": rows,
        "mode": "replace",
    })
    body = r.json()
    assert body["updated"] == 1
    pid = client.get("/api/products").json()["items"][0]["id"]
    p = client.get(f"/api/products/{pid}").json()
    assert p["stock"] == 99
