"""Tests for single-product WooCommerce draft publishing (Phase 3A Part B1).

No real HTTP. No real DNS. Only ``httpx.MockTransport`` and dependency
overrides. Existing 200 baseline tests must remain green.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Callable, Optional

import httpx
import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

TEST_KEY = "ck_TEST_SECRET_KEY_SHOULD_NEVER_LEAK"
TEST_SECRET = "cs_TEST_SECRET_VALUE_SHOULD_NEVER_LEAK"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _factory_mock():
    from integrations.woocommerce_client import WooCommerceClient, WooCommerceConfig
    def factory():
        return WooCommerceClient(WooCommerceConfig(mode="mock"))
    return factory


def _factory_live(handler):
    from integrations.woocommerce_client import WooCommerceClient, WooCommerceConfig
    def factory():
        cfg = WooCommerceConfig(
            store_url="https://shop.example.com",
            consumer_key=TEST_KEY, consumer_secret=TEST_SECRET,
            mode="live", timeout_seconds=20.0, verify_ssl=True,
            app_env="development",
        )
        return WooCommerceClient(
            cfg,
            transport=httpx.MockTransport(handler),
            resolver=lambda h: ["93.184.216.34"],
        )
    return factory


def _install(server_mod, factory):
    import woocommerce_routes as wr
    server_mod.app.dependency_overrides[wr.get_woocommerce_client] = factory


@pytest.fixture()
def wc_client(client, tmp_db):
    """Fresh WC dependency + status state per test."""
    import woocommerce_routes as wr
    wr._reset_status_state_for_tests()
    yield client
    wr._reset_status_state_for_tests()
    tmp_db.app.dependency_overrides.clear()


def _seed_ready_product(client, sku="PUB-1", category="Elektronik"):
    """Seed a product that is ready_to_publish + has an approved suggestion."""
    row = {
        "sku": sku,
        "name": "Samsung Galaxy A55 128GB Akıllı Telefon Siyah",
        "description": "6.6 inç Super AMOLED ekran, 50MP kamera, 5000 mAh batarya kapasitesi.",
        "category": category,
        "price": "18999.90",
        "stock": "24",
        "image_url": "https://example.com/x.jpg",
        "product_url": "https://example.com/p",
    }
    client.post("/api/import/commit", json={
        "mapping": {k: k for k in row.keys()}, "rows": [row], "mode": "replace",
    })
    p = client.get("/api/products").json()["items"][0]

    # Create + approve a suggestion (Demo AI provider).
    s = client.post(f"/api/products/{p['id']}/suggest").json()
    # Tags via patch
    client.patch(f"/api/products/{p['id']}/suggestion", json={
        "suggested_seo_title": "Galaxy A55 128GB - SEO",
        "suggested_meta_description": "SEO meta description",
        "suggested_tags": ["telefon", "samsung"],
    })
    client.post(f"/api/products/{p['id']}/suggestion/approve")

    fresh = client.get(f"/api/products/{p['id']}").json()
    assert fresh["workflow_status"] == "ready_to_publish", fresh
    return fresh


def _add_mapping(client, local_category="Elektronik", external_id=1, external_name="Genel"):
    r = client.post("/api/integrations/woocommerce/category-mappings", json={
        "local_category": local_category,
        "external_category_id": external_id,
        "external_category_name": external_name,
    })
    assert r.status_code in (200, 201), r.text
    return r.json()


# --------------------------------------------------------------------------- #
# Preconditions
# --------------------------------------------------------------------------- #

def test_nonexistent_product_blocked(wc_client, tmp_db):
    _install(tmp_db, _factory_mock())
    r = wc_client.post("/api/products/does-not-exist/publish/woocommerce")
    assert r.status_code == 404


def test_non_ready_product_blocked(wc_client, tmp_db):
    _install(tmp_db, _factory_mock())
    row = {"sku": "N-1", "name": "Bir ürün", "price": "10", "stock": "1"}
    wc_client.post("/api/import/commit", json={
        "mapping": {k: k for k in row.keys()}, "rows": [row], "mode": "replace",
    })
    p = wc_client.get("/api/products").json()["items"][0]
    r = wc_client.post(f"/api/products/{p['id']}/publish/woocommerce")
    assert r.status_code == 400
    assert "yayına hazır değil" in r.json()["detail"].lower()


def test_missing_approved_suggestion_blocked(wc_client, tmp_db):
    _install(tmp_db, _factory_mock())
    # Seed a good product but only up to draft (no approve).
    row = {
        "sku": "N-2", "name": "İyi bir ürün adı",
        "description": "Yeterince uzun bir Türkçe açıklama metnidir.",
        "category": "Elektronik", "price": "500", "stock": "5",
        "image_url": "https://example.com/i.jpg",
        "product_url": "https://example.com/p",
    }
    wc_client.post("/api/import/commit", json={
        "mapping": {k: k for k in row.keys()}, "rows": [row], "mode": "replace",
    })
    p = wc_client.get("/api/products").json()["items"][0]
    wc_client.post(f"/api/products/{p['id']}/suggest")  # draft only
    r = wc_client.post(f"/api/products/{p['id']}/publish/woocommerce")
    assert r.status_code == 400


def test_missing_category_mapping_blocked(wc_client, tmp_db):
    _install(tmp_db, _factory_mock())
    p = _seed_ready_product(wc_client, sku="MAP-1", category="Elektronik")
    # No mapping created.
    r = wc_client.post(f"/api/products/{p['id']}/publish/woocommerce")
    assert r.status_code == 400
    assert "WooCommerce kategori eşleştirmesi eksik" in r.json()["detail"]


# --------------------------------------------------------------------------- #
# Payload correctness
# --------------------------------------------------------------------------- #

def test_payload_uses_approved_content_and_originals(wc_client, tmp_db):
    """Capture the exact payload sent to WooCommerce and inspect."""
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/products/categories"):
            return httpx.Response(200, json=[
                {"id": 7, "name": "Elektronik", "slug": "elektronik", "parent": 0},
            ])
        captured["method"] = request.method
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json={
            "id": 42, "status": "draft",
            "permalink": "https://shop.example.com/?p=42",
            "name": captured["body"]["name"],
        })

    _install(tmp_db, _factory_live(handler))
    _add_mapping(wc_client, local_category="Elektronik", external_id=7, external_name="Elektronik")
    p = _seed_ready_product(wc_client, sku="PAY-1", category="Elektronik")

    r = wc_client.post(f"/api/products/{p['id']}/publish/woocommerce")
    assert r.status_code == 200, r.text

    body = captured["body"]
    # Approved fields
    assert body["name"]  # approved name (non-empty)
    assert body["description"]
    # Original preserved
    assert body["sku"] == "PAY-1"
    assert body["regular_price"] == "18999.90"
    assert body["stock_quantity"] == 24
    assert body["manage_stock"] is True
    # Status forced draft
    assert body["status"] == "draft"
    # Category from mapping (not from raw local category)
    assert body["categories"] == [{"id": 7}]
    # Image comes from original product
    assert body["images"] == [{"src": "https://example.com/x.jpg"}]
    # SEO / meta / tags namespaced neutral meta_data
    meta_keys = {m["key"] for m in body.get("meta_data", [])}
    assert meta_keys == {
        "ai_merchant_os_seo_title",
        "ai_merchant_os_meta_description",
        "ai_merchant_os_tags",
    }
    # product_url is never used as permalink
    assert "permalink" not in body
    # No credentials leaked into path
    assert TEST_KEY not in captured["path"]
    assert TEST_SECRET not in captured["path"]
    assert captured["method"] == "POST"
    assert captured["path"] == "/wp-json/wc/v3/products"


def test_publish_forces_status_draft_even_if_upstream_returns_publish(wc_client, tmp_db):
    def handler(request):
        if request.url.path.endswith("/products/categories"):
            return httpx.Response(200, json=[
                {"id": 1, "name": "Genel", "slug": "genel", "parent": 0},
            ])
        return httpx.Response(200, json={
            "id": 55, "status": "publish", "permalink": "https://shop.example.com/x",
            "name": "x",
        })
    _install(tmp_db, _factory_live(handler))
    _add_mapping(wc_client, local_category="Elektronik", external_id=1, external_name="Genel")
    p = _seed_ready_product(wc_client, sku="DRAFT-1", category="Elektronik")

    r = wc_client.post(f"/api/products/{p['id']}/publish/woocommerce")
    assert r.status_code == 200
    # Response returned to client says "draft".
    fresh = wc_client.get(f"/api/products/{p['id']}/publications/woocommerce").json()
    assert fresh["publication_status"] in ("draft_created", "draft_updated")


# --------------------------------------------------------------------------- #
# First send (create) + idempotency (update)
# --------------------------------------------------------------------------- #

def test_mock_first_send_creates_draft(wc_client, tmp_db):
    _install(tmp_db, _factory_mock())
    _add_mapping(wc_client, local_category="Elektronik", external_id=1, external_name="Genel")
    p = _seed_ready_product(wc_client, sku="MOCK-1", category="Elektronik")

    r = wc_client.post(f"/api/products/{p['id']}/publish/woocommerce")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["mode"] == "mock"
    assert body["action"] == "draft_created"
    assert body["publication_status"] == "draft_created"
    assert body["workflow_status"] == "sent_as_draft"
    assert body["attempt_count"] == 1
    assert body["external_product_id"]
    assert body["external_url"]

    # Publication row exists exactly once.
    from database import SessionLocal
    from models import ProductPublication
    db = SessionLocal()
    try:
        rows = db.query(ProductPublication).filter(
            ProductPublication.product_id == p["id"]
        ).all()
    finally:
        db.close()
    assert len(rows) == 1


def test_second_send_updates_same_row(wc_client, tmp_db):
    counter = {"create": 0, "update": 0}
    def handler(request):
        if request.url.path.endswith("/products/categories"):
            return httpx.Response(200, json=[
                {"id": 1, "name": "Genel", "slug": "genel", "parent": 0},
            ])
        if request.method == "POST":
            counter["create"] += 1
            return httpx.Response(200, json={
                "id": 999, "status": "draft",
                "permalink": "https://shop.example.com/?p=999", "name": "n",
            })
        counter["update"] += 1
        return httpx.Response(200, json={
            "id": 999, "status": "draft",
            "permalink": "https://shop.example.com/?p=999", "name": "n2",
        })
    _install(tmp_db, _factory_live(handler))
    _add_mapping(wc_client, local_category="Elektronik", external_id=1, external_name="Genel")
    p = _seed_ready_product(wc_client, sku="UPD-1", category="Elektronik")

    r1 = wc_client.post(f"/api/products/{p['id']}/publish/woocommerce").json()
    assert r1["action"] == "draft_created"
    assert r1["external_product_id"] == "999"

    r2 = wc_client.post(f"/api/products/{p['id']}/publish/woocommerce").json()
    assert r2["action"] == "draft_updated"
    assert r2["external_product_id"] == "999"
    assert r2["attempt_count"] == 2

    assert counter["create"] == 1
    assert counter["update"] == 1

    from database import SessionLocal
    from models import ProductPublication
    db = SessionLocal()
    try:
        rows = db.query(ProductPublication).filter(
            ProductPublication.product_id == p["id"]
        ).all()
    finally:
        db.close()
    assert len(rows) == 1


def test_mock_reuses_same_external_id_for_same_sku(wc_client, tmp_db):
    _install(tmp_db, _factory_mock())
    _add_mapping(wc_client, local_category="Elektronik", external_id=1, external_name="Genel")
    p = _seed_ready_product(wc_client, sku="MOCK-STABLE-1", category="Elektronik")

    r1 = wc_client.post(f"/api/products/{p['id']}/publish/woocommerce").json()
    r2 = wc_client.post(f"/api/products/{p['id']}/publish/woocommerce").json()
    assert r1["external_product_id"] == r2["external_product_id"]
    assert r2["action"] == "draft_updated"


# --------------------------------------------------------------------------- #
# Failure handling
# --------------------------------------------------------------------------- #

def test_failure_preserves_previous_success(wc_client, tmp_db):
    """After a successful create, a failing re-send must not lose external_product_id."""
    state = {"phase": "create"}

    def handler(request):
        if request.url.path.endswith("/products/categories"):
            return httpx.Response(200, json=[
                {"id": 1, "name": "Genel", "slug": "genel", "parent": 0},
            ])
        if state["phase"] == "create":
            return httpx.Response(200, json={
                "id": 321, "status": "draft",
                "permalink": "https://shop.example.com/?p=321", "name": "x",
            })
        # Update phase -> 500
        return httpx.Response(500, json={"code": "srv", "message": "boom"})

    _install(tmp_db, _factory_live(handler))
    _add_mapping(wc_client, local_category="Elektronik", external_id=1, external_name="Genel")
    p = _seed_ready_product(wc_client, sku="FAIL-1", category="Elektronik")

    ok = wc_client.post(f"/api/products/{p['id']}/publish/woocommerce")
    assert ok.status_code == 200
    state["phase"] = "update"
    fail = wc_client.post(f"/api/products/{p['id']}/publish/woocommerce")
    assert fail.status_code == 502
    detail = fail.json()["detail"]
    assert TEST_KEY not in detail
    assert TEST_SECRET not in detail

    stat = wc_client.get(f"/api/products/{p['id']}/publications/woocommerce").json()
    assert stat["publication_status"] == "failed"
    assert stat["external_product_id"] == "321"  # preserved
    assert stat["external_url"] is not None
    assert stat["last_success_at"] is not None
    assert stat["attempt_count"] == 2
    assert stat["last_error"] is not None


def test_failure_does_not_modify_original_or_suggestion(wc_client, tmp_db):
    def handler(request):
        if request.url.path.endswith("/products/categories"):
            return httpx.Response(200, json=[
                {"id": 1, "name": "Genel", "slug": "genel", "parent": 0},
            ])
        return httpx.Response(500, json={"code": "srv", "message": "boom"})
    _install(tmp_db, _factory_live(handler))
    _add_mapping(wc_client, local_category="Elektronik", external_id=1, external_name="Genel")
    p_before = _seed_ready_product(wc_client, sku="FAIL-2", category="Elektronik")
    sug_before = wc_client.get(f"/api/products/{p_before['id']}/suggestion").json()

    r = wc_client.post(f"/api/products/{p_before['id']}/publish/woocommerce")
    assert r.status_code == 502

    p_after = wc_client.get(f"/api/products/{p_before['id']}").json()
    sug_after = wc_client.get(f"/api/products/{p_before['id']}/suggestion").json()
    for k in ("sku", "name", "description", "category", "price", "stock",
              "image_url", "product_url"):
        assert p_after[k] == p_before[k], f"{k} changed on failure"
    for k in ("suggested_name", "suggested_description", "suggested_category",
              "suggestion_status"):
        assert sug_after[k] == sug_before[k], f"suggestion.{k} changed on failure"

    # workflow_status must NOT become sent_as_draft on failure.
    assert p_after["workflow_status"] != "sent_as_draft"


def test_failure_creates_one_activity(wc_client, tmp_db):
    def handler(request):
        if request.url.path.endswith("/products/categories"):
            return httpx.Response(200, json=[
                {"id": 1, "name": "Genel", "slug": "genel", "parent": 0},
            ])
        return httpx.Response(401, json={"code": "auth", "message": "no"})
    _install(tmp_db, _factory_live(handler))
    _add_mapping(wc_client, local_category="Elektronik", external_id=1, external_name="Genel")
    p = _seed_ready_product(wc_client, sku="ACT-FAIL", category="Elektronik")

    wc_client.post(f"/api/products/{p['id']}/publish/woocommerce")
    from database import SessionLocal
    from models import Activity
    db = SessionLocal()
    try:
        rows = db.query(Activity).filter(
            Activity.kind == "integration",
            Activity.message.like("%başarısız%"),
        ).all()
    finally:
        db.close()
    assert len(rows) == 1
    for a in rows:
        assert TEST_KEY not in a.message
        assert TEST_SECRET not in a.message


def test_success_creates_one_activity(wc_client, tmp_db):
    _install(tmp_db, _factory_mock())
    _add_mapping(wc_client, local_category="Elektronik", external_id=1, external_name="Genel")
    p = _seed_ready_product(wc_client, sku="ACT-OK", category="Elektronik")
    wc_client.post(f"/api/products/{p['id']}/publish/woocommerce")

    from database import SessionLocal
    from models import Activity
    db = SessionLocal()
    try:
        rows = db.query(Activity).filter(
            Activity.kind == "integration",
            Activity.message.like("%taslak olarak gönderildi%"),
        ).all()
    finally:
        db.close()
    assert len(rows) == 1


# --------------------------------------------------------------------------- #
# Publication status endpoint
# --------------------------------------------------------------------------- #

def test_publication_endpoint_safe_no_snapshots(wc_client, tmp_db):
    _install(tmp_db, _factory_mock())
    _add_mapping(wc_client, local_category="Elektronik", external_id=1, external_name="Genel")
    p = _seed_ready_product(wc_client, sku="GET-1", category="Elektronik")
    wc_client.post(f"/api/products/{p['id']}/publish/woocommerce")

    r = wc_client.get(f"/api/products/{p['id']}/publications/woocommerce")
    assert r.status_code == 200
    body = r.json()
    # Positive assertions
    assert body["product_id"] == p["id"]
    assert body["channel"] == "woocommerce"
    assert body["publication_status"] == "draft_created"
    assert body["attempt_count"] == 1
    # No snapshots or credentials
    assert "payload_snapshot" not in body
    assert "response_snapshot" not in body
    assert TEST_KEY not in r.text
    assert TEST_SECRET not in r.text


def test_publication_endpoint_404_when_none(wc_client, tmp_db):
    _install(tmp_db, _factory_mock())
    row = {"sku": "NO-PUB", "name": "x", "price": "1", "stock": "1"}
    wc_client.post("/api/import/commit", json={
        "mapping": {k: k for k in row.keys()}, "rows": [row], "mode": "replace",
    })
    p = wc_client.get("/api/products").json()["items"][0]
    r = wc_client.get(f"/api/products/{p['id']}/publications/woocommerce")
    assert r.status_code == 404


# --------------------------------------------------------------------------- #
# Smoke: existing suites still route
# --------------------------------------------------------------------------- #

def test_export_ready_still_works(wc_client, tmp_db):
    """Part A + Merchant export should be untouched by publish additions."""
    r = wc_client.get("/api/export/ready-to-publish")
    assert r.status_code == 200
