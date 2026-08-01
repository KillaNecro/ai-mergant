"""Product listing / pagination / bulk validation tests."""


def _seed(client, count=3):
    rows = [{"sku": f"P-{i}", "name": f"Ürün {i}", "price": "10"} for i in range(count)]
    client.post("/api/import/commit", json={
        "mapping": {"sku": "sku", "name": "name", "price": "price"},
        "rows": rows, "mode": "replace",
    })


def test_pagination_bounds(client):
    r = client.get("/api/products", params={"page": 0})
    assert r.status_code in (400, 422)
    r = client.get("/api/products", params={"page_size": 500})
    assert r.status_code in (400, 422)


def test_empty_bulk_rejected(client):
    r = client.post("/api/bulk/category", json={"ids": [], "category": "X"})
    assert r.status_code == 422  # pydantic min_length


def test_price_percent_limit(client):
    _seed(client, 1)
    p = client.get("/api/products").json()["items"][0]
    r = client.post("/api/bulk/price-percent", json={"ids": [p["id"]], "percent": 500})
    assert r.status_code == 422


def test_bulk_price_never_negative(client):
    rows = [{"sku": "LOW-1", "name": "Ucuz", "price": "1"}]
    client.post("/api/import/commit", json={
        "mapping": {"sku": "sku", "name": "name", "price": "price"},
        "rows": rows, "mode": "replace",
    })
    pid = client.get("/api/products").json()["items"][0]["id"]
    r = client.post("/api/bulk/price-percent", json={"ids": [pid], "percent": -80})
    assert r.status_code == 200
    price = client.get(f"/api/products/{pid}").json()["price"]
    assert price is not None and price >= 0


def test_products_persist_across_reads(client):
    _seed(client, 2)
    n = client.get("/api/products").json()["total"]
    assert n == 2
    # Second call — same data
    assert client.get("/api/products").json()["total"] == 2


def test_activity_timestamps_utc(client):
    _seed(client, 1)
    acts = client.get("/api/dashboard/stats").json()["recent_activities"]
    assert acts, "should have at least one activity"
    ts = acts[0]["created_at"]
    assert ts.endswith("Z"), f"timestamp must be UTC ISO with Z suffix, got {ts!r}"


def test_negative_price_rejected(client):
    rows = [{"sku": "NEG-1", "name": "Ürün", "price": "-5"}]
    r = client.post("/api/import/commit", json={
        "mapping": {"sku": "sku", "name": "name", "price": "price"},
        "rows": rows, "mode": "replace",
    })
    assert r.json()["failed"] == 1
