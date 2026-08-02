"""Tests for AI suggestion generation, demo/gemini behavior."""
import asyncio

import pytest

import ai_service


def _seed(client):
    row = {
        "sku": "S-1", "name": "SAMSUNG A55 128GB",
        "description": "6.6 inç ekran.", "category": "Elektronik",
        "price": "100", "stock": "5",
        "image_url": "https://example.com/x.jpg", "product_url": "https://example.com/p",
    }
    client.post("/api/import/commit", json={
        "mapping": {k: k for k in row.keys()}, "rows": [row], "mode": "replace",
    })
    return client.get("/api/products").json()["items"][0]


def test_demo_suggestion_is_conservative(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    payload = asyncio.run(ai_service.generate_suggestion(
        name="SAMSUNG A55 128GB Akıllı Telefon Siyah",
        description="6.6 inç ekran.",
        category="Elektronik",
        price=18999.0,
    ))
    assert payload["provider"] == "demo"
    # No fabricated marketing claim
    assert "günlük kullanıma uygun" not in payload["suggested_description"].lower()
    # Preserves the model number and brand
    assert "A55" in payload["suggested_name"] or "A55" in payload["suggested_description"]
    assert "128GB" in payload["suggested_name"] or "128GB" in payload["suggested_description"]
    # SEO/meta lengths respected
    assert len(payload["suggested_seo_title"]) <= 60
    assert len(payload["suggested_meta_description"]) <= 155
    assert isinstance(payload["suggested_tags"], list)


def test_gemini_failure_prevents_persisted_suggestion(client, monkeypatch):
    """Provider error → HTTP 502 → no ProductSuggestion row is committed."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    def boom(prompt):
        raise ai_service.AIProviderError("network down")

    monkeypatch.setattr(ai_service, "_gemini_call", boom)

    p = _seed(client)
    r = client.post(f"/api/products/{p['id']}/suggest")
    assert r.status_code == 502
    # No suggestion, product remains without an active_suggestion_id
    p2 = client.get(f"/api/products/{p['id']}").json()
    assert p2["active_suggestion_id"] is None
    assert p2["workflow_status"] != "awaiting_review"


def test_ai_never_overwrites_original(client):
    """Even after successful suggestion, product original fields are unchanged."""
    p = _seed(client)
    original_name = p["name"]
    original_desc = p["description"]
    r = client.post(f"/api/products/{p['id']}/suggest")
    assert r.status_code == 200
    s = r.json()
    assert s["suggested_name"] != original_name  # AI suggests a cleaned title
    p2 = client.get(f"/api/products/{p['id']}").json()
    assert p2["name"] == original_name
    assert p2["description"] == original_desc


def test_bulk_suggest_stops_on_provider_failure(client, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    def boom(prompt):
        raise ai_service.AIProviderError("gemini down")

    monkeypatch.setattr(ai_service, "_gemini_call", boom)

    _seed(client)
    row2 = {"sku": "S-2", "name": "İkinci Ürün Deneme"}
    client.post("/api/import/commit", json={
        "mapping": {"sku": "sku", "name": "name"}, "rows": [row2], "mode": "replace",
    })
    ids = [p["id"] for p in client.get("/api/products").json()["items"]]
    r = client.post("/api/bulk/suggest", json={"ids": ids}).json()
    assert r["failed"] >= 1
    assert r["processed"] == 0
