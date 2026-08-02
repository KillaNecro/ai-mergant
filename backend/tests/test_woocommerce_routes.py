"""Integration tests for WooCommerce FastAPI routes.

Tests mount the real FastAPI app on a temporary SQLite database, and override
the ``get_woocommerce_client`` dependency with a client built on a
``httpx.MockTransport`` so no real network is touched.
"""
from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


TEST_KEY = "ck_TEST_SECRET_KEY_SHOULD_NEVER_LEAK"
TEST_SECRET = "cs_TEST_SECRET_VALUE_SHOULD_NEVER_LEAK"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _install_client_override(server_mod, factory):
    from integrations.woocommerce_client import WooCommerceClient  # noqa: F401
    import woocommerce_routes as wr

    server_mod.app.dependency_overrides[wr.get_woocommerce_client] = factory


def _client_factory_mock():
    """Returns a factory producing mock-mode WooCommerce clients."""
    from integrations.woocommerce_client import WooCommerceClient, WooCommerceConfig
    def factory():
        return WooCommerceClient(WooCommerceConfig(mode="mock"))
    return factory


def _client_factory_live(handler, *, url="https://shop.example.com", app_env="development"):
    from integrations.woocommerce_client import WooCommerceClient, WooCommerceConfig
    def factory():
        cfg = WooCommerceConfig(
            store_url=url,
            consumer_key=TEST_KEY,
            consumer_secret=TEST_SECRET,
            mode="live",
            timeout_seconds=20.0,
            verify_ssl=True,
            app_env=app_env,
        )
        return WooCommerceClient(
            cfg,
            transport=httpx.MockTransport(handler),
            resolver=lambda h: ["93.184.216.34"],
        )
    return factory


def _client_factory_live_unconfigured():
    from integrations.woocommerce_client import WooCommerceClient, WooCommerceConfig
    def factory():
        cfg = WooCommerceConfig(
            store_url="",
            consumer_key="",
            consumer_secret="",
            mode="live",
        )
        return WooCommerceClient(cfg)
    return factory


@pytest.fixture()
def wc_client(client, tmp_db):
    """Ensure module-level in-memory status resets between tests."""
    import woocommerce_routes as wr
    wr._reset_status_state_for_tests()
    yield client
    wr._reset_status_state_for_tests()
    tmp_db.app.dependency_overrides.clear()


# --------------------------------------------------------------------------- #
# GET /status
# --------------------------------------------------------------------------- #

def test_status_mock(wc_client, tmp_db):
    _install_client_override(tmp_db, _client_factory_mock())
    r = wc_client.get("/api/integrations/woocommerce/status")
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "mock"
    assert body["configured"] is True
    assert body["connected"] is True
    assert "mock" in body["message"].lower()
    assert TEST_KEY not in r.text
    assert TEST_SECRET not in r.text


def test_status_live_missing_config(wc_client, tmp_db):
    _install_client_override(tmp_db, _client_factory_live_unconfigured())
    r = wc_client.get("/api/integrations/woocommerce/status")
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "live"
    assert body["configured"] is False
    assert body["connected"] is False
    assert "eksik" in body["message"].lower()


def test_status_live_not_tested_yet(wc_client, tmp_db):
    def handler(request):
        return httpx.Response(200, json=[])
    _install_client_override(tmp_db, _client_factory_live(handler))
    r = wc_client.get("/api/integrations/woocommerce/status")
    body = r.json()
    assert body["configured"] is True
    assert body["connected"] is False
    assert body["last_checked_at"] is None


def test_status_updates_after_successful_test(wc_client, tmp_db):
    def handler(request):
        return httpx.Response(200, json=[])
    _install_client_override(tmp_db, _client_factory_live(handler))
    t = wc_client.post("/api/integrations/woocommerce/test")
    assert t.status_code == 200
    s = wc_client.get("/api/integrations/woocommerce/status").json()
    assert s["connected"] is True
    assert s["last_checked_at"] is not None


def test_status_updates_after_failed_test(wc_client, tmp_db):
    def handler(request):
        return httpx.Response(401, json={"code": "e", "message": "no"})
    _install_client_override(tmp_db, _client_factory_live(handler))
    t = wc_client.post("/api/integrations/woocommerce/test")
    assert t.status_code == 401
    s = wc_client.get("/api/integrations/woocommerce/status").json()
    assert s["connected"] is False
    assert s["last_checked_at"] is not None
    assert s["error"] is not None
    assert TEST_KEY not in s["error"]


# --------------------------------------------------------------------------- #
# POST /test
# --------------------------------------------------------------------------- #

def test_post_test_mock(wc_client, tmp_db):
    _install_client_override(tmp_db, _client_factory_mock())
    r = wc_client.post("/api/integrations/woocommerce/test")
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "mock"
    assert body["connected"] is True


def test_post_test_live_success(wc_client, tmp_db):
    def handler(request):
        return httpx.Response(200, json=[])
    _install_client_override(tmp_db, _client_factory_live(handler))
    r = wc_client.post("/api/integrations/woocommerce/test")
    assert r.status_code == 200
    assert r.json()["mode"] == "live"


@pytest.mark.parametrize("upstream_status,expected_status", [
    (401, 401),
    (403, 403),
])
def test_post_test_error_status_mapping(wc_client, tmp_db, upstream_status, expected_status):
    def handler(request):
        return httpx.Response(upstream_status, json={"code": "e", "message": "no"})
    _install_client_override(tmp_db, _client_factory_live(handler))
    r = wc_client.post("/api/integrations/woocommerce/test")
    assert r.status_code == expected_status
    assert TEST_KEY not in r.text
    assert TEST_SECRET not in r.text


def test_post_test_timeout_maps_to_504(wc_client, tmp_db):
    def handler(request):
        raise httpx.TimeoutException("t")
    _install_client_override(tmp_db, _client_factory_live(handler))
    r = wc_client.post("/api/integrations/woocommerce/test")
    assert r.status_code == 504


def test_post_test_connection_error_maps_to_502(wc_client, tmp_db):
    def handler(request):
        raise httpx.ConnectError("dead")
    _install_client_override(tmp_db, _client_factory_live(handler))
    r = wc_client.post("/api/integrations/woocommerce/test")
    assert r.status_code == 502


def test_post_test_config_missing_returns_400(wc_client, tmp_db):
    _install_client_override(tmp_db, _client_factory_live_unconfigured())
    r = wc_client.post("/api/integrations/woocommerce/test")
    assert r.status_code == 400
    assert "eksik" in r.json()["detail"].lower()


# --------------------------------------------------------------------------- #
# GET /categories
# --------------------------------------------------------------------------- #

def test_categories_mock(wc_client, tmp_db):
    _install_client_override(tmp_db, _client_factory_mock())
    r = wc_client.get("/api/integrations/woocommerce/categories")
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "mock"
    assert body["count"] == len(body["categories"])
    assert body["count"] >= 2
    for c in body["categories"]:
        assert set(c.keys()) == {"id", "name", "slug", "parent"}


def test_categories_live(wc_client, tmp_db):
    def handler(request):
        return httpx.Response(200, json=[
            {"id": 10, "name": "Kitap", "slug": "kitap", "parent": 0},
            {"id": 11, "name": "Kırtasiye", "slug": "kirtasiye", "parent": 0},
        ])
    _install_client_override(tmp_db, _client_factory_live(handler))
    r = wc_client.get("/api/integrations/woocommerce/categories")
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "live"
    assert body["count"] == 2
    assert TEST_KEY not in r.text
    assert TEST_SECRET not in r.text


def test_categories_partial_failure_bubbles_up(wc_client, tmp_db):
    def handler(request):
        page = int(request.url.params.get("page", "1"))
        if page == 1:
            return httpx.Response(200,
                json=[{"id": i, "name": f"C{i}", "slug": f"c{i}", "parent": 0} for i in range(1, 101)],
                headers={"X-WP-TotalPages": "2"})
        return httpx.Response(500, json={"code": "srv", "message": "boom"})
    _install_client_override(tmp_db, _client_factory_live(handler))
    r = wc_client.get("/api/integrations/woocommerce/categories")
    assert r.status_code == 502


# --------------------------------------------------------------------------- #
# Category mappings
# --------------------------------------------------------------------------- #

def _stub_categories_handler():
    def h(request):
        return httpx.Response(200, json=[
            {"id": 12, "name": "Seramik", "slug": "seramik", "parent": 0},
            {"id": 13, "name": "Elektronik", "slug": "elektronik", "parent": 0},
        ])
    return h


def test_mappings_initially_empty(wc_client, tmp_db):
    _install_client_override(tmp_db, _client_factory_mock())
    r = wc_client.get("/api/integrations/woocommerce/category-mappings")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 0
    assert body["mappings"] == []


def test_mapping_create_and_upsert(wc_client, tmp_db):
    _install_client_override(tmp_db, _client_factory_mock())
    # In mock mode, category ids 1 and 2 are valid.
    r1 = wc_client.post("/api/integrations/woocommerce/category-mappings", json={
        "local_category": "  Seramik Ürünleri  ",
        "external_category_id": 1,
        "external_category_name": "Genel",
    })
    assert r1.status_code == 201
    body = r1.json()
    assert body["created"] is True
    assert body["mapping"]["local_category"] == "Seramik Ürünleri"

    # Upsert -- same local_category, different external target
    r2 = wc_client.post("/api/integrations/woocommerce/category-mappings", json={
        "local_category": "Seramik Ürünleri",
        "external_category_id": 2,
        "external_category_name": "Test Kategorisi",
    })
    assert r2.status_code == 200
    body = r2.json()
    assert body["updated"] is True

    # Only one row should exist.
    lst = wc_client.get("/api/integrations/woocommerce/category-mappings").json()
    assert lst["count"] == 1
    assert lst["mappings"][0]["external_category_id"] == 2


def test_mapping_invalid_payload(wc_client, tmp_db):
    _install_client_override(tmp_db, _client_factory_mock())
    for payload in [
        {"local_category": "", "external_category_id": 1, "external_category_name": "Genel"},
        {"local_category": "X", "external_category_id": 0, "external_category_name": "Genel"},
        {"local_category": "X", "external_category_id": -1, "external_category_name": "Genel"},
        {"local_category": "X", "external_category_id": 1, "external_category_name": ""},
    ]:
        r = wc_client.post("/api/integrations/woocommerce/category-mappings", json=payload)
        assert r.status_code == 422, f"Expected 422 for {payload}, got {r.status_code}"


def test_mapping_extra_channel_field_rejected(wc_client, tmp_db):
    _install_client_override(tmp_db, _client_factory_mock())
    r = wc_client.post("/api/integrations/woocommerce/category-mappings", json={
        "channel": "shopify",
        "local_category": "X",
        "external_category_id": 1,
        "external_category_name": "Genel",
    })
    assert r.status_code == 422


def test_mapping_nonexistent_remote_category_rejected(wc_client, tmp_db):
    _install_client_override(tmp_db, _client_factory_mock())
    r = wc_client.post("/api/integrations/woocommerce/category-mappings", json={
        "local_category": "X",
        "external_category_id": 9999,  # not in mock list
        "external_category_name": "Ghost",
    })
    assert r.status_code == 422
    assert "bulunamadı" in r.json()["detail"].lower()


def test_mapping_filter_and_ordering(wc_client, tmp_db):
    _install_client_override(tmp_db, _client_factory_mock())
    for name in ("Bardak", "Ayakkabı", "Cezve"):
        wc_client.post("/api/integrations/woocommerce/category-mappings", json={
            "local_category": name,
            "external_category_id": 1,
            "external_category_name": "Genel",
        })
    lst = wc_client.get("/api/integrations/woocommerce/category-mappings").json()
    names = [m["local_category"] for m in lst["mappings"]]
    assert names == sorted(names)
    # Filter
    filtered = wc_client.get(
        "/api/integrations/woocommerce/category-mappings",
        params={"local_category": "Bardak"},
    ).json()
    assert filtered["count"] == 1
    assert filtered["mappings"][0]["local_category"] == "Bardak"


def test_mapping_delete(wc_client, tmp_db):
    _install_client_override(tmp_db, _client_factory_mock())
    r = wc_client.post("/api/integrations/woocommerce/category-mappings", json={
        "local_category": "Silinecek",
        "external_category_id": 1,
        "external_category_name": "Genel",
    })
    mapping_id = r.json()["mapping"]["id"]
    d = wc_client.delete(f"/api/integrations/woocommerce/category-mappings/{mapping_id}")
    assert d.status_code == 200
    assert d.json()["deleted"] is True
    # Deleting again returns 404
    d2 = wc_client.delete(f"/api/integrations/woocommerce/category-mappings/{mapping_id}")
    assert d2.status_code == 404


def test_mapping_delete_unknown(wc_client, tmp_db):
    _install_client_override(tmp_db, _client_factory_mock())
    r = wc_client.delete("/api/integrations/woocommerce/category-mappings/does-not-exist")
    assert r.status_code == 404


def test_mapping_delete_other_channel_invisible(wc_client, tmp_db):
    """Directly insert a foreign-channel row and confirm it's not visible/deletable."""
    _install_client_override(tmp_db, _client_factory_mock())
    from database import SessionLocal
    from models import CategoryMapping
    db = SessionLocal()
    try:
        row = CategoryMapping(
            channel="shopify",
            local_category="Foreign",
            external_category_id=99,
            external_category_name="X",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        foreign_id = row.id
    finally:
        db.close()

    lst = wc_client.get("/api/integrations/woocommerce/category-mappings").json()
    assert all(m["channel"] == "woocommerce" for m in lst["mappings"])
    d = wc_client.delete(f"/api/integrations/woocommerce/category-mappings/{foreign_id}")
    assert d.status_code == 404


def test_mapping_activities_recorded(wc_client, tmp_db):
    _install_client_override(tmp_db, _client_factory_mock())
    wc_client.post("/api/integrations/woocommerce/category-mappings", json={
        "local_category": "Aktivite Testi",
        "external_category_id": 1,
        "external_category_name": "Genel",
    })
    # Update
    r = wc_client.post("/api/integrations/woocommerce/category-mappings", json={
        "local_category": "Aktivite Testi",
        "external_category_id": 2,
        "external_category_name": "Test Kategorisi",
    })
    mapping_id = r.json()["mapping"]["id"]
    wc_client.delete(f"/api/integrations/woocommerce/category-mappings/{mapping_id}")

    from database import SessionLocal
    from models import Activity
    db = SessionLocal()
    try:
        rows = db.query(Activity).filter(Activity.kind == "integration").all()
        messages = [r.message for r in rows]
    finally:
        db.close()
    assert any("oluşturuldu" in m for m in messages)
    assert any("güncellendi" in m for m in messages)
    assert any("silindi" in m for m in messages)
    for m in messages:
        assert TEST_KEY not in m
        assert TEST_SECRET not in m


# --------------------------------------------------------------------------- #
# Router integrity
# --------------------------------------------------------------------------- #

def test_woocommerce_router_registered_once(wc_client, tmp_db):
    seen = set()
    for route in tmp_db.app.routes:
        for method in getattr(route, "methods", []) or []:
            key = (method, route.path)
            if "woocommerce" in route.path:
                assert key not in seen, f"Duplicate route: {key}"
                seen.add(key)
    # Sanity: our six documented paths+methods are present.
    expected = {
        ("GET", "/api/integrations/woocommerce/status"),
        ("POST", "/api/integrations/woocommerce/test"),
        ("GET", "/api/integrations/woocommerce/categories"),
        ("GET", "/api/integrations/woocommerce/category-mappings"),
        ("POST", "/api/integrations/woocommerce/category-mappings"),
        ("DELETE", "/api/integrations/woocommerce/category-mappings/{mapping_id}"),
    }
    assert expected.issubset(seen)


def test_existing_merchant_routes_still_work(wc_client, tmp_db):
    _install_client_override(tmp_db, _client_factory_mock())
    r = wc_client.get("/api/dashboard/stats")
    assert r.status_code == 200
