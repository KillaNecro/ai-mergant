"""Tests for the deterministic quality engine."""
import pytest


def _post_import(client, rows, mapping=None, mode="replace"):
    mapping = mapping or {k: k for k in rows[0].keys()}
    return client.post("/api/import/commit", json={
        "mapping": mapping, "rows": rows, "mode": mode,
    })


def test_analyze_returns_score_and_issues(client):
    _post_import(client, [{"sku": "Q-1", "name": "A"}], mapping={"sku": "sku", "name": "name"})
    pid = client.get("/api/products").json()["items"][0]["id"]
    r = client.post(f"/api/products/{pid}/analyze")
    assert r.status_code == 200
    body = r.json()
    assert 0 <= body["score"] <= 100
    codes = [i["issue_code"] for i in body["issues"]]
    assert "MISSING_DESCRIPTION" in codes
    assert "MISSING_PRICE" in codes
    assert "MISSING_CATEGORY" in codes
    assert "MISSING_IMAGE" in codes
    assert "TITLE_TOO_SHORT" in codes  # "A" is 1 char


def test_score_clamped_between_0_and_100(client):
    # A product with every issue possible → 0 floor
    _post_import(client, [{"sku": "  bad  ", "name": "urun", "price": "-1"}],
                 mapping={"sku": "sku", "name": "name", "price": "price"})
    # import rejects negative price → the row fails; use a valid path instead
    _post_import(client, [{"sku": "BAD-1", "name": "urun"}],
                 mapping={"sku": "sku", "name": "name"}, mode="replace")
    pid = client.get("/api/products").json()["items"][0]["id"]
    r = client.post(f"/api/products/{pid}/analyze")
    assert r.status_code == 200
    assert 0 <= r.json()["score"] <= 100


def test_perfect_product_scores_100(client):
    row = {
        "sku": "GOOD-1",
        "name": "Samsung Galaxy A55 128GB Akıllı Telefon Siyah",
        "description": "6.6 inç Super AMOLED ekran, 50MP kamera, 5000 mAh batarya kapasitesi.",
        "category": "Elektronik", "price": "18999.90", "stock": "24",
        "image_url": "https://example.com/x.jpg",
        "product_url": "https://example.com/p",
    }
    _post_import(client, [row])
    pid = client.get("/api/products").json()["items"][0]["id"]
    r = client.post(f"/api/products/{pid}/analyze")
    assert r.status_code == 200
    assert r.json()["score"] == 100
    assert r.json()["workflow_status"] == "ready_for_ai"


def test_analysis_is_idempotent(client):
    _post_import(client, [{"sku": "IDEM-1", "name": "abc"}], mapping={"sku": "sku", "name": "name"})
    pid = client.get("/api/products").json()["items"][0]["id"]
    a = client.post(f"/api/products/{pid}/analyze").json()
    b = client.post(f"/api/products/{pid}/analyze").json()
    # Same issue codes, same count — no duplicates
    codes_a = sorted(i["issue_code"] for i in a["issues"])
    codes_b = sorted(i["issue_code"] for i in b["issues"])
    assert codes_a == codes_b
    assert len(a["issues"]) == len(b["issues"])


def test_status_transition_needs_attention_when_critical(client):
    _post_import(client, [{"sku": "NA-1", "name": "urun"}], mapping={"sku": "sku", "name": "name"})
    pid = client.get("/api/products").json()["items"][0]["id"]
    r = client.post(f"/api/products/{pid}/analyze").json()
    assert r["workflow_status"] == "needs_attention"


def test_duplicate_title_detected(client):
    _post_import(client, [
        {"sku": "D-1", "name": "Aynı Başlık Ürün Deneme Modeli"},
        {"sku": "D-2", "name": "Aynı Başlık Ürün Deneme Modeli"},
    ], mapping={"sku": "sku", "name": "name"})
    products = client.get("/api/products").json()["items"]
    for p in products:
        codes = [i["issue_code"] for i in client.get(f"/api/products/{p['id']}/issues").json()]
        assert "DUPLICATE_TITLE" in codes


def test_analyze_all_processes_every_product(client):
    _post_import(client, [
        {"sku": f"AA-{i}", "name": f"Ürün {i}"} for i in range(3)
    ], mapping={"sku": "sku", "name": "name"})
    r = client.post("/api/products/analyze-all")
    assert r.status_code == 200
    assert r.json()["processed"] == 3


def test_import_auto_analyzes(client):
    """After /import/commit, products already have quality_score set."""
    _post_import(client, [{"sku": "AUTO-1", "name": "urun"}], mapping={"sku": "sku", "name": "name"})
    p = client.get("/api/products").json()["items"][0]
    assert p["quality_score"] is not None
    assert p["workflow_status"] in ("needs_attention", "ready_for_ai")
