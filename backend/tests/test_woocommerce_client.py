"""Unit tests for the WooCommerce HTTP client. All tests are network-free."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Callable, List, Optional

import httpx
import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from integrations.woocommerce_client import (  # noqa: E402
    MAX_RESPONSE_BYTES,
    WooCommerceAPIError,
    WooCommerceAuthenticationError,
    WooCommerceClient,
    WooCommerceConfig,
    WooCommerceConfigurationError,
    WooCommerceConnectionError,
    WooCommercePermissionError,
    WooCommerceResponseError,
    WooCommerceSSLError,
    WooCommerceSecurityError,
    WooCommerceTimeoutError,
    _is_public_ip,
    _normalize_store_url,
)

TEST_KEY = "ck_TEST_SECRET_KEY_SHOULD_NEVER_LEAK"
TEST_SECRET = "cs_TEST_SECRET_VALUE_SHOULD_NEVER_LEAK"


def run(coro):
    return asyncio.run(coro)


# --------------------------------------------------------------------------- #
# Anti-network safety net
# --------------------------------------------------------------------------- #

@pytest.fixture(autouse=True)
def _block_network(monkeypatch):
    def _guard(*a, **kw):  # pragma: no cover - safety net
        raise RuntimeError("Real network transport instantiated in tests")
    monkeypatch.setattr(httpx.HTTPTransport, "__init__", _guard)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "__init__", _guard)
    yield


def _clean_env(monkeypatch):
    for k in (
        "WOOCOMMERCE_URL", "WOOCOMMERCE_CONSUMER_KEY", "WOOCOMMERCE_CONSUMER_SECRET",
        "WOOCOMMERCE_MODE", "WOOCOMMERCE_TIMEOUT_SECONDS", "WOOCOMMERCE_VERIFY_SSL",
        "APP_ENV",
    ):
        monkeypatch.delenv(k, raising=False)


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #

def test_default_mode_is_mock(monkeypatch):
    _clean_env(monkeypatch)
    cfg = WooCommerceConfig.from_env()
    assert cfg.mode == "mock"
    assert cfg.is_mock is True


def test_mock_mode_does_not_require_credentials(monkeypatch):
    _clean_env(monkeypatch)
    cfg = WooCommerceConfig.from_env()
    assert cfg.consumer_key == ""
    cfg.require_live_ready()  # no-op in mock


def test_invalid_mode_rejected(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("WOOCOMMERCE_MODE", "banana")
    with pytest.raises(WooCommerceConfigurationError):
        WooCommerceConfig.from_env()


@pytest.mark.parametrize("missing_key", ["WOOCOMMERCE_URL", "WOOCOMMERCE_CONSUMER_KEY", "WOOCOMMERCE_CONSUMER_SECRET"])
def test_live_missing_config_rejected(monkeypatch, missing_key):
    _clean_env(monkeypatch)
    monkeypatch.setenv("WOOCOMMERCE_MODE", "live")
    envs = {
        "WOOCOMMERCE_URL": "https://shop.example.com",
        "WOOCOMMERCE_CONSUMER_KEY": TEST_KEY,
        "WOOCOMMERCE_CONSUMER_SECRET": TEST_SECRET,
    }
    envs.pop(missing_key)
    for k, v in envs.items():
        monkeypatch.setenv(k, v)
    cfg = WooCommerceConfig.from_env()
    with pytest.raises(WooCommerceConfigurationError):
        cfg.require_live_ready()


@pytest.mark.parametrize("value", ["0", "-5"])
def test_bad_timeout_rejected(monkeypatch, value):
    _clean_env(monkeypatch)
    monkeypatch.setenv("WOOCOMMERCE_TIMEOUT_SECONDS", value)
    with pytest.raises(WooCommerceConfigurationError):
        WooCommerceConfig.from_env()


@pytest.mark.parametrize("value,expected", [
    ("true", True), ("True", True), ("1", True), ("yes", True), ("on", True),
    ("false", False), ("0", False), ("no", False), ("off", False),
])
def test_boolean_ssl_parsing(monkeypatch, value, expected):
    _clean_env(monkeypatch)
    monkeypatch.setenv("WOOCOMMERCE_VERIFY_SSL", value)
    cfg = WooCommerceConfig.from_env()
    assert cfg.verify_ssl is expected


def test_config_repr_masks_secrets():
    cfg = WooCommerceConfig(
        store_url="https://shop.example.com",
        consumer_key=TEST_KEY,
        consumer_secret=TEST_SECRET,
        mode="live",
    )
    r = repr(cfg)
    s = str(cfg)
    assert TEST_KEY not in r and TEST_KEY not in s
    assert TEST_SECRET not in r and TEST_SECRET not in s


# --------------------------------------------------------------------------- #
# URL normalization
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("raw,expected", [
    ("https://shop.example.com/", "https://shop.example.com"),
    ("https://shop.example.com/wp-json/wc/v3/", "https://shop.example.com"),
    ("https://shop.example.com/wp-json/wc/v3", "https://shop.example.com"),
    ("https://shop.example.com/wp-json", "https://shop.example.com"),
    ("https://shop.example.com/subshop/", "https://shop.example.com/subshop"),
    ("HTTPS://Shop.Example.COM/", "https://shop.example.com"),
])
def test_url_normalization(raw, expected):
    assert _normalize_store_url(raw) == expected


@pytest.mark.parametrize("bad", [
    "file:///etc/passwd",
    "ftp://shop.example.com",
    "javascript:alert(1)",
    "data:text/plain,hi",
    "https://user:pw@shop.example.com/",
    "https://shop.example.com#frag",
    "https://shop.example.com/?a=1",
])
def test_url_rejects_unsafe(bad):
    with pytest.raises((WooCommerceSecurityError, WooCommerceConfigurationError)):
        _normalize_store_url(bad)


def test_production_http_rejected(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("WOOCOMMERCE_MODE", "live")
    monkeypatch.setenv("WOOCOMMERCE_URL", "http://shop.example.com")
    monkeypatch.setenv("WOOCOMMERCE_CONSUMER_KEY", TEST_KEY)
    monkeypatch.setenv("WOOCOMMERCE_CONSUMER_SECRET", TEST_SECRET)
    cfg = WooCommerceConfig.from_env()
    with pytest.raises(WooCommerceSecurityError):
        cfg.require_live_ready()


# --------------------------------------------------------------------------- #
# SSRF protection
# --------------------------------------------------------------------------- #

def _live_client(
    monkeypatch,
    *,
    transport: Optional[httpx.MockTransport] = None,
    url: str = "https://shop.example.com",
    resolver: Optional[Callable[[str], List[str]]] = None,
    allow_local_host: bool = False,
    app_env: str = "development",
) -> WooCommerceClient:
    _clean_env(monkeypatch)
    monkeypatch.setenv("APP_ENV", app_env)
    monkeypatch.setenv("WOOCOMMERCE_MODE", "live")
    monkeypatch.setenv("WOOCOMMERCE_URL", url)
    monkeypatch.setenv("WOOCOMMERCE_CONSUMER_KEY", TEST_KEY)
    monkeypatch.setenv("WOOCOMMERCE_CONSUMER_SECRET", TEST_SECRET)
    cfg = WooCommerceConfig.from_env()
    return WooCommerceClient(
        cfg,
        transport=transport,
        resolver=(resolver or (lambda h: ["93.184.216.34"])),
        allow_local_host=allow_local_host,
    )


@pytest.mark.parametrize("ip", [
    "127.0.0.1", "10.0.0.1", "192.168.1.1", "172.16.0.5",
    "169.254.169.254", "0.0.0.0", "224.0.0.1", "::1", "fe80::1", "fd00::1",
])
def test_is_public_ip_rejects_unsafe(ip):
    assert _is_public_ip(ip) is False


def test_is_public_ip_accepts_public():
    assert _is_public_ip("93.184.216.34") is True


def test_production_localhost_rejected(monkeypatch):
    client = _live_client(
        monkeypatch,
        url="https://internal.local.example",
        resolver=lambda h: ["127.0.0.1"],
        app_env="production",
    )
    with pytest.raises(WooCommerceSecurityError):
        run(client.test_connection())


def test_ssrf_mixed_addresses_rejected(monkeypatch):
    client = _live_client(
        monkeypatch,
        resolver=lambda h: ["93.184.216.34", "127.0.0.1"],
        app_env="production",
    )
    with pytest.raises(WooCommerceSecurityError):
        run(client.test_connection())


def test_dev_localhost_allowed_when_flagged(monkeypatch):
    def handler(request):
        return httpx.Response(200, json=[])
    _clean_env(monkeypatch)
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("WOOCOMMERCE_MODE", "live")
    monkeypatch.setenv("WOOCOMMERCE_URL", "http://localhost:8080")
    monkeypatch.setenv("WOOCOMMERCE_CONSUMER_KEY", TEST_KEY)
    monkeypatch.setenv("WOOCOMMERCE_CONSUMER_SECRET", TEST_SECRET)
    cfg = WooCommerceConfig.from_env()
    client = WooCommerceClient(cfg, transport=httpx.MockTransport(handler), allow_local_host=True)
    result = run(client.test_connection())
    assert result["connected"] is True


def test_mock_mode_skips_resolver(monkeypatch):
    _clean_env(monkeypatch)
    called = {"n": 0}
    def resolver(h):
        called["n"] += 1
        return ["1.2.3.4"]
    cfg = WooCommerceConfig.from_env()
    client = WooCommerceClient(cfg, resolver=resolver)
    result = run(client.test_connection())
    assert result["mode"] == "mock"
    assert called["n"] == 0


# --------------------------------------------------------------------------- #
# Mock behaviour
# --------------------------------------------------------------------------- #

def test_mock_test_connection_does_not_hit_network(monkeypatch):
    _clean_env(monkeypatch)
    cfg = WooCommerceConfig.from_env()
    client = WooCommerceClient(cfg)
    result = run(client.test_connection())
    assert result["connected"] is True
    assert result["mode"] == "mock"
    assert "mock" in result["message"].lower()


def test_mock_get_categories_deterministic(monkeypatch):
    _clean_env(monkeypatch)
    cfg = WooCommerceConfig.from_env()
    client = WooCommerceClient(cfg)
    a = run(client.get_categories())
    b = run(client.get_categories())
    assert a == b
    assert len(a) >= 2
    for c in a:
        assert set(c.keys()) == {"id", "name", "slug", "parent"}


# --------------------------------------------------------------------------- #
# Live HTTP mocking
# --------------------------------------------------------------------------- #

def _mock_transport(handler):
    return httpx.MockTransport(handler)


def test_live_test_connection_success(monkeypatch):
    captured = {}
    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["method"] = request.method
        captured["auth"] = request.headers.get("authorization")
        captured["accept"] = request.headers.get("accept")
        captured["ua"] = request.headers.get("user-agent")
        return httpx.Response(200, json=[{"id": 1, "name": "Root", "slug": "root", "parent": 0}])

    client = _live_client(monkeypatch, transport=_mock_transport(handler))
    result = run(client.test_connection())
    assert result["connected"] is True
    assert result["mode"] == "live"
    assert "per_page=1" in captured["url"]
    assert "page=1" in captured["url"]
    assert captured["method"] == "GET"
    assert captured["auth"].startswith("Basic ")
    assert TEST_KEY not in captured["url"]
    assert TEST_SECRET not in captured["url"]
    assert captured["accept"] == "application/json"
    assert "AI-Merchant-OS" in (captured["ua"] or "")


@pytest.mark.parametrize("status_code,exc_type", [
    (401, WooCommerceAuthenticationError),
    (403, WooCommercePermissionError),
    (404, WooCommerceAPIError),
    (408, WooCommerceTimeoutError),
    (429, WooCommerceAPIError),
    (500, WooCommerceAPIError),
    (503, WooCommerceAPIError),
    (400, WooCommerceAPIError),
])
def test_status_code_mapping(monkeypatch, status_code, exc_type):
    def handler(request):
        return httpx.Response(status_code, json={"code": "err", "message": "hata"})
    client = _live_client(monkeypatch, transport=_mock_transport(handler))
    with pytest.raises(exc_type) as ei:
        run(client.test_connection())
    msg = str(ei.value)
    assert TEST_KEY not in msg
    assert TEST_SECRET not in msg


@pytest.mark.parametrize("code", [301, 302, 303, 307, 308])
def test_redirect_refused(monkeypatch, code):
    def handler(request):
        return httpx.Response(code, headers={"Location": "https://evil.example.com/"})
    client = _live_client(monkeypatch, transport=_mock_transport(handler))
    with pytest.raises(WooCommerceSecurityError):
        run(client.test_connection())


def test_timeout_mapped(monkeypatch):
    def handler(request):
        raise httpx.TimeoutException("boom")
    client = _live_client(monkeypatch, transport=_mock_transport(handler))
    with pytest.raises(WooCommerceTimeoutError):
        run(client.test_connection())


def test_connect_error_mapped(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("no connect")
    client = _live_client(monkeypatch, transport=_mock_transport(handler))
    with pytest.raises(WooCommerceConnectionError):
        run(client.test_connection())


def test_ssl_error_mapped(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("SSL: CERTIFICATE_VERIFY_FAILED")
    client = _live_client(monkeypatch, transport=_mock_transport(handler))
    with pytest.raises(WooCommerceSSLError):
        run(client.test_connection())


def test_invalid_json_rejected(monkeypatch):
    def handler(request):
        return httpx.Response(200, content=b"<html>oops</html>")
    client = _live_client(monkeypatch, transport=_mock_transport(handler))
    with pytest.raises(WooCommerceResponseError):
        run(client.test_connection())


def test_oversized_response_rejected(monkeypatch):
    big = b"A" * (MAX_RESPONSE_BYTES + 100)
    def handler(request):
        return httpx.Response(200, content=big, headers={"Content-Length": str(len(big))})
    client = _live_client(monkeypatch, transport=_mock_transport(handler))
    with pytest.raises(WooCommerceResponseError):
        run(client.test_connection())


def test_error_message_truncates_html(monkeypatch):
    huge_html = "<html>" + ("secret-marker " * 500) + "</html>"
    def handler(request):
        return httpx.Response(500, content=huge_html.encode(), headers={"Content-Type": "text/html"})
    client = _live_client(monkeypatch, transport=_mock_transport(handler))
    with pytest.raises(WooCommerceAPIError) as ei:
        run(client.test_connection())
    assert len(ei.value.message) <= 500


# --------------------------------------------------------------------------- #
# Category pagination
# --------------------------------------------------------------------------- #

def _make_cats(start, count):
    return [
        {"id": start + i, "name": f"Cat {start + i}", "slug": f"cat-{start + i}", "parent": 0}
        for i in range(count)
    ]


def test_categories_single_page(monkeypatch):
    def handler(request):
        return httpx.Response(200, json=_make_cats(1, 5))
    client = _live_client(monkeypatch, transport=_mock_transport(handler))
    cats = run(client.get_categories())
    assert [c["id"] for c in cats] == [1, 2, 3, 4, 5]


def test_categories_multipage_via_totalpages_header(monkeypatch):
    calls = {"n": 0}
    def handler(request):
        calls["n"] += 1
        page = int(request.url.params.get("page", "1"))
        payload = _make_cats((page - 1) * 100 + 1, 100)
        return httpx.Response(200, json=payload, headers={"X-WP-TotalPages": "3"})
    client = _live_client(monkeypatch, transport=_mock_transport(handler))
    cats = run(client.get_categories())
    assert calls["n"] == 3
    assert len(cats) == 300


def test_categories_pagination_without_header(monkeypatch):
    calls = {"n": 0}
    def handler(request):
        calls["n"] += 1
        page = int(request.url.params.get("page", "1"))
        if page == 1:
            return httpx.Response(200, json=_make_cats(1, 100))
        return httpx.Response(200, json=_make_cats(101, 5))
    client = _live_client(monkeypatch, transport=_mock_transport(handler))
    cats = run(client.get_categories())
    assert calls["n"] == 2
    assert len(cats) == 105


def test_categories_partial_failure_is_not_returned(monkeypatch):
    def handler(request):
        page = int(request.url.params.get("page", "1"))
        if page == 1:
            return httpx.Response(200, json=_make_cats(1, 100),
                                  headers={"X-WP-TotalPages": "2"})
        return httpx.Response(500, json={"code": "server", "message": "boom"})
    client = _live_client(monkeypatch, transport=_mock_transport(handler))
    with pytest.raises(WooCommerceAPIError):
        run(client.get_categories())


def test_categories_deduplicates_and_validates(monkeypatch):
    payload = [
        {"id": 5, "name": "Alpha", "slug": "alpha", "parent": 0},
        {"id": 5, "name": "Alpha Dup", "slug": "alpha-dup", "parent": 0},
        {"id": 6, "name": "", "slug": "empty", "parent": 0},
        {"id": -1, "name": "Bad", "slug": "bad", "parent": 0},
        {"id": 7, "name": "Beta", "slug": "beta", "parent": -1},
        {"id": 8, "name": "Gamma", "slug": "gamma", "parent": 0},
    ]
    def handler(request):
        return httpx.Response(200, json=payload)
    client = _live_client(monkeypatch, transport=_mock_transport(handler))
    cats = run(client.get_categories())
    ids = [c["id"] for c in cats]
    assert ids == [5, 8]


def test_exception_messages_never_contain_credentials(monkeypatch):
    def handler(request):
        return httpx.Response(401, json={
            "code": "auth",
            "message": f"Bad auth for {TEST_KEY}/{TEST_SECRET}",
        })
    client = _live_client(monkeypatch, transport=_mock_transport(handler))
    with pytest.raises(WooCommerceAuthenticationError) as ei:
        run(client.test_connection())
    msg = ei.value.message + " " + str(ei.value)
    assert TEST_KEY not in msg
    assert TEST_SECRET not in msg
