"""Phase 2.1 correctness fixes."""


def _seed(client, **overrides):
    row = {
        "sku": "F-1",
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


# ----------- Bug 1: effective candidate validation -----------
def test_ai_description_resolves_original_missing_description(client):
    # Original product has empty description → MISSING_DESCRIPTION issue.
    p = _seed(client, description=None)
    issues = client.get(f"/api/products/{p['id']}/issues").json()
    assert any(i["issue_code"] == "MISSING_DESCRIPTION" for i in issues)

    # Create + approve suggestion that provides a description.
    client.post(f"/api/products/{p['id']}/suggest")
    r = client.post(f"/api/products/{p['id']}/suggestion/approve").json()
    # Effective candidate now has a description → ready_to_publish.
    assert r["ready_to_publish"] is True, r
    assert r["workflow_status"] == "ready_to_publish"
    # Original product row is NEVER touched.
    p2 = client.get(f"/api/products/{p['id']}").json()
    assert p2["description"] in (None, "")
    assert p2["workflow_status"] == "ready_to_publish"


def test_missing_price_still_blocks_approval(client):
    p = _seed(client, price=None)
    client.post(f"/api/products/{p['id']}/suggest")
    r = client.post(f"/api/products/{p['id']}/suggestion/approve").json()
    assert r["ready_to_publish"] is False
    assert r["workflow_status"] == "approved"
    assert any("Fiyat" in reason for reason in r["blocking_reasons"])


def test_ready_to_publish_export_uses_effective_content(client):
    p = _seed(client, description=None)  # missing original description
    client.post(f"/api/products/{p['id']}/suggest")
    client.post(f"/api/products/{p['id']}/suggestion/approve")
    csv_bytes = client.get("/api/export/ready-to-publish").content
    assert csv_bytes.startswith(b"\xef\xbb\xbf")
    # The exported approved_description must come from the AI suggestion,
    # not from the original (which is empty).
    text = csv_bytes.decode("utf-8-sig")
    lines = text.splitlines()
    assert len(lines) >= 2
    header = lines[0].split(",")
    approved_desc_idx = header.index("approved_description")
    # naive CSV split is fine here because our content has no commas in that field
    row = lines[1].split(",")
    assert row[approved_desc_idx].strip('"')  # non-empty


# ----------- Bug 2: PATCH re-runs analysis -----------
def test_patch_reanalyzes_and_updates_workflow(client):
    p = _seed(client, price=None)  # → MISSING_PRICE
    issues_before = client.get(f"/api/products/{p['id']}/issues").json()
    score_before = client.get(f"/api/products/{p['id']}").json()["quality_score"]
    assert any(i["issue_code"] == "MISSING_PRICE" for i in issues_before)

    # Fix the price via direct PATCH.
    r = client.patch(f"/api/products/{p['id']}", json={"price": 1299.90})
    assert r.status_code == 200
    updated = r.json()

    issues_after = client.get(f"/api/products/{p['id']}/issues").json()
    codes = [i["issue_code"] for i in issues_after]
    assert "MISSING_PRICE" not in codes
    assert updated["quality_score"] > score_before
    assert updated["workflow_status"] in ("ready_for_ai", "awaiting_review", "ready_to_publish", "approved")


def test_patch_preserves_active_suggestion_and_history(client):
    p = _seed(client)
    s = client.post(f"/api/products/{p['id']}/suggest").json()
    revs_before = len(client.get(f"/api/products/{p['id']}/revisions").json())

    client.patch(f"/api/products/{p['id']}", json={"stock": 42})
    p2 = client.get(f"/api/products/{p['id']}").json()
    # Suggestion still active
    assert p2["active_suggestion_id"] == s["id"]
    # Revision history preserved
    revs_after = client.get(f"/api/products/{p['id']}/revisions").json()
    assert len(revs_after) >= revs_before


# ----------- Bug 3: Bulk AI transaction safety -----------
def test_bulk_suggest_partial_success_persists(client, monkeypatch):
    # Seed two products.
    _seed(client, sku="B3-1")
    _seed(client, sku="B3-2")
    items = client.get("/api/products").json()["items"]
    p1 = next(x for x in items if x["sku"] == "B3-1")
    p2 = next(x for x in items if x["sku"] == "B3-2")

    # Force Gemini path and make the *second* call fail; first must succeed.
    import ai_service
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    calls = {"n": 0}
    original_generate = ai_service.generate_suggestion

    async def fake_generate(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            # Return a valid demo-style payload for the first product.
            return {
                "provider": "gemini", "model": "test",
                "suggested_name": "İyileştirilmiş Başlık",
                "suggested_description": "Yeterince uzun bir açıklama metni burada var.",
                "suggested_category": kwargs.get("category"),
                "suggested_seo_title": "SEO Başlık",
                "suggested_meta_description": "Meta açıklama",
                "suggested_tags": ["etiket"],
            }
        raise ai_service.AIProviderError("gemini down for product 2")

    monkeypatch.setattr(ai_service, "generate_suggestion", fake_generate)

    r = client.post("/api/bulk/suggest", json={"ids": [p1["id"], p2["id"]]}).json()
    assert r["processed"] == 1
    assert r["failed"] == 1
    # The successful suggestion for p1 must remain committed.
    p1_after = client.get(f"/api/products/{p1['id']}").json()
    assert p1_after["active_suggestion_id"] is not None
    s1 = client.get(f"/api/products/{p1['id']}/suggestion").json()
    assert s1 is not None and s1["suggestion_status"] == "draft"
    # p2 has no suggestion.
    p2_after = client.get(f"/api/products/{p2['id']}").json()
    assert p2_after["active_suggestion_id"] is None


# ----------- Bug 4: Bulk approval eligibility -----------
def test_bulk_approve_skips_when_original_price_invalid(client):
    # Product with missing original price — even a great AI suggestion cannot
    # make it ready_to_publish, so bulk approval MUST skip it (draft preserved).
    p = _seed(client, price=None)
    client.post(f"/api/products/{p['id']}/suggest")

    r = client.post("/api/bulk/approve", json={"ids": [p["id"]]}).json()
    assert r["approved"] == 0
    assert r["skipped"] == 1
    reasons = [x["reason"] for x in r["reasons"]]
    assert any("Yayına hazır değil" in reason and "Fiyat" in reason for reason in reasons)

    # The suggestion is UNCHANGED — still draft.
    s = client.get(f"/api/products/{p['id']}/suggestion").json()
    assert s is not None and s["suggestion_status"] == "draft"
    # Product did NOT become ready_to_publish or approved.
    p2 = client.get(f"/api/products/{p['id']}").json()
    assert p2["workflow_status"] not in ("approved", "ready_to_publish")


def test_bulk_approve_still_counts_only_publishable_as_approved(client):
    # Good product → will be approved and ready.
    good = _seed(client, sku="OK-1")
    client.post(f"/api/products/{good['id']}/suggest")
    # Bad product (no price) → skipped.
    bad = _seed(client, sku="OK-2", price=None)
    client.post(f"/api/products/{bad['id']}/suggest")

    r = client.post("/api/bulk/approve", json={"ids": [good["id"], bad["id"]]}).json()
    assert r["approved"] == 1
    assert r["skipped"] == 1
    p_good = client.get(f"/api/products/{good['id']}").json()
    assert p_good["workflow_status"] == "ready_to_publish"
    p_bad = client.get(f"/api/products/{bad['id']}").json()
    assert p_bad["workflow_status"] not in ("approved", "ready_to_publish")
