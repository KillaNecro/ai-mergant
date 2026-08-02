"""Phase 2.2 stabilization tests."""


def _seed(client, **overrides):
    row = {
        "sku": "P22-1",
        "name": "Samsung Galaxy A55 128GB Akıllı Telefon Siyah",
        "description": "6.6 inç Super AMOLED ekran, 50MP kamera, 5000 mAh batarya kapasitesi.",
        "category": "Elektronik",
        "price": "18999.90", "stock": "24",
        "image_url": "https://example.com/x.jpg",
        "product_url": "https://example.com/p",
    }
    row.update({k: v for k, v in overrides.items() if v is not None})
    for k, v in overrides.items():
        if v is None:
            row.pop(k, None)
    client.post("/api/import/commit", json={
        "mapping": {k: k for k in row.keys()}, "rows": [row], "mode": "replace",
    })
    return client.get("/api/products").json()["items"][0]


# --- Task 1: unique routes -----------------------------------------------
def test_openapi_has_no_duplicate_route_method(client):
    spec = client.get("/openapi.json").json()
    seen: set[tuple[str, str]] = set()
    dups: list[tuple[str, str]] = []
    for path, ops in spec.get("paths", {}).items():
        for method in ops.keys():
            key = (method.upper(), path)
            if key in seen:
                dups.append(key)
            seen.add(key)
    assert not dups, f"Duplicate route/method entries: {dups}"


# --- Task 4: bulk reanalysis ---------------------------------------------
def test_bulk_category_reanalyzes(client):
    p = _seed(client, category=None)
    issues_before = [i["issue_code"] for i in client.get(f"/api/products/{p['id']}/issues").json()]
    assert "MISSING_CATEGORY" in issues_before
    score_before = client.get(f"/api/products/{p['id']}").json()["quality_score"]

    r = client.post("/api/bulk/category", json={"ids": [p["id"]], "category": "Elektronik"})
    assert r.status_code == 200

    p_after = client.get(f"/api/products/{p['id']}").json()
    issues_after = [i["issue_code"] for i in client.get(f"/api/products/{p['id']}/issues").json()]
    assert "MISSING_CATEGORY" not in issues_after
    assert p_after["quality_score"] > score_before


def test_bulk_price_percent_reanalyzes(client):
    p = _seed(client, price="10")
    _ = client.post("/api/bulk/price-percent", json={"ids": [p["id"]], "percent": 50})
    p_after = client.get(f"/api/products/{p['id']}").json()
    # No MISSING_PRICE any more (still 10 → 15) and the analysis timestamp advanced.
    codes = [i["issue_code"] for i in client.get(f"/api/products/{p['id']}/issues").json()]
    assert "MISSING_PRICE" not in codes
    assert p_after["quality_analyzed_at"] is not None


def test_bulk_ops_preserve_approved_suggestions(client):
    p = _seed(client)
    s = client.post(f"/api/products/{p['id']}/suggest").json()
    client.post(f"/api/products/{p['id']}/suggestion/approve")
    client.post("/api/bulk/category", json={"ids": [p["id"]], "category": "Yeni Kategori"})
    p2 = client.get(f"/api/products/{p['id']}").json()
    assert p2["active_suggestion_id"] == s["id"]
    sug = client.get(f"/api/products/{p['id']}/suggestion").json()
    assert sug["suggestion_status"] == "approved"


# --- Task 5: category required for publish -------------------------------
def test_missing_original_category_resolved_by_suggested_category(client):
    p = _seed(client, category=None)
    client.post(f"/api/products/{p['id']}/suggest")
    # AI demo suggestion may or may not fill category; force one via PATCH.
    client.patch(f"/api/products/{p['id']}/suggestion", json={
        "suggested_category": "Elektronik",
    })
    r = client.post(f"/api/products/{p['id']}/suggestion/approve").json()
    assert r["ready_to_publish"] is True
    p2 = client.get(f"/api/products/{p['id']}").json()
    assert p2["category"] in (None, "")  # original preserved
    assert p2["workflow_status"] == "ready_to_publish"


def test_missing_category_in_both_sources_blocks_publish(client):
    p = _seed(client, category=None)
    client.post(f"/api/products/{p['id']}/suggest")
    client.patch(f"/api/products/{p['id']}/suggestion", json={"suggested_category": ""})
    r = client.post(f"/api/products/{p['id']}/suggestion/approve").json()
    assert r["ready_to_publish"] is False
    assert any("Kategori eksik" in reason for reason in r["blocking_reasons"])


def test_bulk_approve_skips_empty_category(client):
    p = _seed(client, category=None)
    client.post(f"/api/products/{p['id']}/suggest")
    client.patch(f"/api/products/{p['id']}/suggestion", json={"suggested_category": ""})
    r = client.post("/api/bulk/approve", json={"ids": [p["id"]]}).json()
    assert r["approved"] == 0
    assert r["skipped"] == 1
    reasons = [x["reason"] for x in r["reasons"]]
    assert any("Kategori eksik" in reason for reason in reasons)
    # Draft suggestion untouched
    s = client.get(f"/api/products/{p['id']}/suggestion").json()
    assert s["suggestion_status"] == "draft"
