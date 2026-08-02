"""Tests for workflow (suggestions, approval, rejection, revert)."""


def _seed_good(client, sku="W-1"):
    row = {
        "sku": sku,
        "name": "Samsung Galaxy A55 128GB Akıllı Telefon Siyah",
        "description": "6.6 inç Super AMOLED ekran, 50MP kamera, 5000 mAh batarya kapasitesi.",
        "category": "Elektronik", "price": "18999.90", "stock": "24",
        "image_url": "https://example.com/x.jpg",
        "product_url": "https://example.com/p",
    }
    client.post("/api/import/commit", json={
        "mapping": {k: k for k in row.keys()}, "rows": [row], "mode": "replace",
    })
    return client.get("/api/products").json()["items"][0]


def test_suggest_creates_draft_and_does_not_touch_original(client):
    p = _seed_good(client)
    original_name = p["name"]
    original_desc = p["description"]

    r = client.post(f"/api/products/{p['id']}/suggest")
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["suggestion_status"] == "draft"
    assert s["suggested_name"]
    # Original product unchanged
    p2 = client.get(f"/api/products/{p['id']}").json()
    assert p2["name"] == original_name
    assert p2["description"] == original_desc
    assert p2["workflow_status"] == "awaiting_review"
    assert p2["active_suggestion_id"] == s["id"]


def test_edit_suggestion_persists(client):
    p = _seed_good(client)
    client.post(f"/api/products/{p['id']}/suggest")
    r = client.patch(f"/api/products/{p['id']}/suggestion", json={
        "suggested_name": "Kullanıcının Değiştirdiği Başlık",
        "suggested_tags": ["telefon", "samsung"],
    })
    assert r.status_code == 200
    body = r.json()
    assert body["suggested_name"] == "Kullanıcının Değiştirdiği Başlık"
    assert body["suggested_tags"] == ["telefon", "samsung"]


def test_approve_transitions_to_ready_to_publish(client):
    p = _seed_good(client)
    client.post(f"/api/products/{p['id']}/suggest")
    r = client.post(f"/api/products/{p['id']}/suggestion/approve")
    body = r.json()
    assert body["ready_to_publish"] is True
    assert body["workflow_status"] == "ready_to_publish"
    p2 = client.get(f"/api/products/{p['id']}").json()
    # Original product data still not modified
    assert p2["name"] == p["name"]


def test_approve_with_blocking_issues_stays_approved(client):
    # Product missing price → critical issue → validation should fail publish
    row = {
        "sku": "AP-1", "name": "Samsung Galaxy A55 128GB Siyah",
        "description": "Uzun bir açıklama metni ile 40 karakterden fazla içerik.",
        "category": "Elektronik",
        "image_url": "https://example.com/x.jpg",
    }
    client.post("/api/import/commit", json={
        "mapping": {k: k for k in row.keys()}, "rows": [row], "mode": "replace",
    })
    pid = client.get("/api/products").json()["items"][0]["id"]
    client.post(f"/api/products/{pid}/suggest")
    r = client.post(f"/api/products/{pid}/suggestion/approve").json()
    assert r["ready_to_publish"] is False
    assert r["workflow_status"] == "approved"
    assert any("Fiyat" in reason or "kritik" in reason for reason in r["blocking_reasons"])


def test_reject_returns_status_to_quality_based(client):
    p = _seed_good(client)
    client.post(f"/api/products/{p['id']}/suggest")
    r = client.post(f"/api/products/{p['id']}/suggestion/reject").json()
    assert r["workflow_status"] in ("ready_for_ai", "needs_attention")
    # Suggestion is preserved in revisions
    revs = client.get(f"/api/products/{p['id']}/revisions").json()
    assert any(rv["action_type"] == "reject" for rv in revs)


def test_revision_history_records_and_revert_restores(client):
    p = _seed_good(client)
    s1 = client.post(f"/api/products/{p['id']}/suggest").json()
    # Reject then create a new suggestion
    client.post(f"/api/products/{p['id']}/suggestion/reject")
    s2 = client.post(f"/api/products/{p['id']}/suggest").json()
    assert s2["id"] != s1["id"]

    revs = client.get(f"/api/products/{p['id']}/revisions").json()
    # Find first suggest revision (belongs to s1)
    suggest_revs = [r for r in revs if r["action_type"] == "suggest"]
    assert len(suggest_revs) >= 2
    older = suggest_revs[-1]  # oldest is s1's suggest
    r = client.post(f"/api/products/{p['id']}/revisions/{older['id']}/revert").json()
    assert r["active_suggestion"]["suggested_name"] == s1["suggested_name"]
    # Original product still untouched
    p2 = client.get(f"/api/products/{p['id']}").json()
    assert p2["name"] == p["name"]


def test_bulk_approve_eligibility(client):
    # Two products; only one has an active draft
    _seed_good(client, sku="B-1")
    _seed_good(client, sku="B-2")
    items = client.get("/api/products").json()["items"]
    p1, p2 = items[0], items[1]
    client.post(f"/api/products/{p1['id']}/suggest")
    r = client.post("/api/bulk/approve", json={"ids": [p1["id"], p2["id"]]}).json()
    assert r["approved"] == 1
    assert r["skipped"] == 1
    reasons = [x["reason"] for x in r["reasons"]]
    assert any("Aktif öneri yok" in reason for reason in reasons)


def test_bulk_analyze(client):
    _seed_good(client, sku="BA-1")
    _seed_good(client, sku="BA-2")
    ids = [p["id"] for p in client.get("/api/products").json()["items"]]
    r = client.post("/api/bulk/analyze", json={"ids": ids}).json()
    assert r["processed"] == 2


def test_ready_to_publish_export(client):
    p = _seed_good(client)
    client.post(f"/api/products/{p['id']}/suggest")
    client.post(f"/api/products/{p['id']}/suggestion/approve")
    r = client.get("/api/export/ready-to-publish")
    assert r.status_code == 200
    assert r.content.startswith(b"\xef\xbb\xbf")
    assert b"approved_name" in r.content
    # Original SKU preserved
    assert p["sku"].encode("utf-8") in r.content


def test_dashboard_merchant_stats(client):
    _seed_good(client)
    stats = client.get("/api/dashboard/stats").json()
    assert "average_quality_score" in stats
    assert "needs_attention" in stats
    assert "awaiting_review" in stats
    assert "ready_to_publish" in stats
    assert "open_critical_issues" in stats


def test_workflow_status_filter(client):
    _seed_good(client, sku="F-1")
    row = {"sku": "F-2", "name": "A"}
    client.post("/api/import/commit", json={
        "mapping": {"sku": "sku", "name": "name"}, "rows": [row], "mode": "replace",
    })
    n_att = client.get("/api/products", params={"workflow_status": "needs_attention"}).json()["total"]
    assert n_att >= 1


def test_score_bucket_filter(client):
    _seed_good(client)
    high = client.get("/api/products", params={"score_bucket": "high"}).json()["items"]
    assert all(p["quality_score"] >= 85 for p in high)
