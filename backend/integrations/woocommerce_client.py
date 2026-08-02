"""WooCommerce REST API client (Phase 3A Part A).

A fully mockable async HTTP client for WooCommerce, designed so unit tests
never touch the real network. Two public methods are implemented in this
phase:

    * test_connection() -- lightweight read-only ping
    * get_categories()  -- paginated list of product categories

Product-publishing methods (create/update/delete) intentionally do NOT
exist yet; they land in Phase 3A Part B.

Design goals:
    * Configuration comes from environment variables only, never hard-coded.
    * Mock mode makes zero network calls and requires no credentials.
    * Live mode enforces URL scheme, HTTPS-in-production, SSRF blocks,
      redirect refusal, size caps and JSON validation.
    * All error paths raise structured typed exceptions carrying a stable
      internal ``code`` and a Turkish user-facing ``message`` that is safe
      to surface. Credentials are never included in exceptions, logs or
      repr output.
"""
from __future__ import annotations

import ipaddress
import json
import logging
import os
import socket
import urllib.parse as _urlparse
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Iterable, List, Optional

import httpx

logger = logging.getLogger("merchant-os.woocommerce")

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

USER_AGENT = "AI-Merchant-OS/1.0"

# Response size safety net (bytes). WooCommerce category lists are tiny;
# anything larger is either misconfigured or malicious.
MAX_RESPONSE_BYTES = 2 * 1024 * 1024  # 2 MB

# Pagination guard against runaway loops.
MAX_CATEGORY_PAGES = 50

VALID_MODES = ("mock", "live")

_ALLOWED_SCHEMES = ("http", "https")


# --------------------------------------------------------------------------- #
# Exceptions
# --------------------------------------------------------------------------- #

class WooCommerceClientError(Exception):
    """Base class for all WooCommerce client errors.

    Attributes
    ----------
    code:
        Stable internal identifier (e.g. ``authentication_failed``). Safe to
        expose via APIs/logs.
    message:
        Turkish user-facing message. Never contains credentials.
    """

    default_code = "woocommerce_error"
    default_message = "WooCommerce hatası"

    def __init__(self, message: Optional[str] = None, *, code: Optional[str] = None) -> None:
        self.code = code or self.default_code
        self.message = message or self.default_message
        super().__init__(self.message)

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"{type(self).__name__}(code={self.code!r}, message={self.message!r})"


class WooCommerceConfigurationError(WooCommerceClientError):
    default_code = "configuration_missing"
    default_message = "WooCommerce yapılandırması eksik veya geçersiz"


class WooCommerceSecurityError(WooCommerceClientError):
    default_code = "unsafe_url"
    default_message = "Güvenli olmayan WooCommerce adresi"


class WooCommerceAuthenticationError(WooCommerceClientError):
    default_code = "authentication_failed"
    default_message = "WooCommerce kimlik doğrulaması başarısız"


class WooCommercePermissionError(WooCommerceClientError):
    default_code = "permission_denied"
    default_message = "WooCommerce yetkisi yetersiz"


class WooCommerceTimeoutError(WooCommerceClientError):
    default_code = "timeout"
    default_message = "WooCommerce isteği zaman aşımına uğradı"


class WooCommerceSSLError(WooCommerceClientError):
    default_code = "ssl_error"
    default_message = "WooCommerce SSL doğrulaması başarısız"


class WooCommerceConnectionError(WooCommerceClientError):
    default_code = "connection_failed"
    default_message = "WooCommerce sunucusuna bağlanılamadı"


class WooCommerceResponseError(WooCommerceClientError):
    default_code = "invalid_response"
    default_message = "WooCommerce cevabı geçersiz"


class WooCommerceAPIError(WooCommerceClientError):
    default_code = "api_error"
    default_message = "WooCommerce API hatası"

    def __init__(
        self,
        message: Optional[str] = None,
        *,
        code: Optional[str] = None,
        status_code: Optional[int] = None,
    ) -> None:
        super().__init__(message, code=code)
        self.status_code = status_code


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _parse_bool(value: Optional[str], default: bool) -> bool:
    if value is None:
        return default
    v = value.strip().lower()
    if v in ("1", "true", "yes", "on"):
        return True
    if v in ("0", "false", "no", "off"):
        return False
    raise WooCommerceConfigurationError(
        "Boolean yapılandırma değeri okunamadı", code="configuration_missing"
    )


def _sanitize_message(text: str, config: "WooCommerceConfig") -> str:
    """Remove any credential-like substrings from a message."""
    if not text:
        return text
    out = text
    for secret in (config.consumer_key, config.consumer_secret):
        if secret:
            out = out.replace(secret, "***")
    # Cap to avoid dumping HTML/JSON error pages verbatim.
    if len(out) > 500:
        out = out[:500] + "…"
    return out


def _normalize_store_url(raw: str) -> str:
    """Validate + normalize the store URL.

    Returns the base URL (no trailing slash and no ``/wp-json/…`` suffix).
    """
    if not raw or not raw.strip():
        raise WooCommerceConfigurationError(
            "WooCommerce mağaza adresi boş", code="configuration_missing"
        )
    trimmed = raw.strip()

    parsed = _urlparse.urlparse(trimmed)
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        raise WooCommerceSecurityError(
            "Yalnızca http/https şemaları desteklenir", code="unsafe_url"
        )
    if not parsed.hostname:
        raise WooCommerceSecurityError(
            "WooCommerce adresinde geçerli bir sunucu adı yok", code="unsafe_url"
        )
    if parsed.username or parsed.password:
        raise WooCommerceSecurityError(
            "URL içinde kullanıcı adı veya şifre bulunamaz", code="unsafe_url"
        )
    if parsed.fragment:
        raise WooCommerceSecurityError(
            "URL fragment (#) taşıyamaz", code="unsafe_url"
        )
    if parsed.query:
        raise WooCommerceSecurityError(
            "URL sorgu parametreleri taşıyamaz", code="unsafe_url"
        )

    path = parsed.path or ""
    # Strip a trailing "/wp-json/wc/v3" or "/wp-json" segment.
    for suffix in ("/wp-json/wc/v3", "/wp-json/wc/v3/", "/wp-json", "/wp-json/"):
        if path.endswith(suffix):
            path = path[: -len(suffix)]
            break
    # Collapse duplicate slashes then strip trailing slash.
    while "//" in path:
        path = path.replace("//", "/")
    if path.endswith("/"):
        path = path[:-1]

    netloc = parsed.hostname.lower()
    if parsed.port:
        netloc += f":{parsed.port}"

    return f"{parsed.scheme.lower()}://{netloc}{path}"


def _default_resolver(host: str) -> List[str]:
    """Default DNS resolver returning distinct IPv4/IPv6 addresses."""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise WooCommerceConnectionError(
            f"DNS çözümlemesi başarısız: {host}", code="connection_failed"
        ) from exc
    seen: set[str] = set()
    out: list[str] = []
    for info in infos:
        addr = info[4][0]
        if addr not in seen:
            seen.add(addr)
            out.append(addr)
    return out


def _is_public_ip(ip_text: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_text)
    except ValueError:
        return False
    if ip.is_loopback or ip.is_private or ip.is_link_local:
        return False
    if ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        return False
    # Explicit block for AWS/GCP/Azure metadata service.
    if ip_text == "169.254.169.254":
        return False
    return True


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #

@dataclass
class WooCommerceConfig:
    """Runtime configuration. Never render this via ``repr``/``str``
    unmodified — the dunder methods below already mask secrets."""

    store_url: str = ""
    consumer_key: str = field(default="", repr=False)
    consumer_secret: str = field(default="", repr=False)
    mode: str = "mock"
    timeout_seconds: float = 20.0
    verify_ssl: bool = True
    app_env: str = "development"

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return (
            "WooCommerceConfig("
            f"store_url={self.store_url!r}, mode={self.mode!r}, "
            f"timeout_seconds={self.timeout_seconds!r}, "
            f"verify_ssl={self.verify_ssl!r}, app_env={self.app_env!r}, "
            "consumer_key=***, consumer_secret=***)"
        )

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.__repr__()

    @property
    def is_mock(self) -> bool:
        return self.mode == "mock"

    @property
    def is_live(self) -> bool:
        return self.mode == "live"

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"

    @property
    def has_credentials(self) -> bool:
        return bool(self.store_url and self.consumer_key and self.consumer_secret)

    # ------------------------------------------------------------------
    @classmethod
    def from_env(cls, env: Optional[dict] = None) -> "WooCommerceConfig":
        e = env if env is not None else os.environ
        mode = (e.get("WOOCOMMERCE_MODE") or "mock").strip().lower()
        if mode not in VALID_MODES:
            raise WooCommerceConfigurationError(
                f"Geçersiz WOOCOMMERCE_MODE: {mode!r}", code="configuration_missing"
            )

        raw_timeout = (e.get("WOOCOMMERCE_TIMEOUT_SECONDS") or "20").strip()
        try:
            timeout = float(raw_timeout)
        except ValueError as exc:
            raise WooCommerceConfigurationError(
                "WOOCOMMERCE_TIMEOUT_SECONDS sayısal bir değer olmalı",
                code="configuration_missing",
            ) from exc
        if timeout <= 0:
            raise WooCommerceConfigurationError(
                "WOOCOMMERCE_TIMEOUT_SECONDS pozitif olmalı", code="configuration_missing"
            )

        verify = _parse_bool(e.get("WOOCOMMERCE_VERIFY_SSL"), default=True)

        store_url_raw = (e.get("WOOCOMMERCE_URL") or "").strip()
        store_url = _normalize_store_url(store_url_raw) if store_url_raw else ""

        return cls(
            store_url=store_url,
            consumer_key=(e.get("WOOCOMMERCE_CONSUMER_KEY") or "").strip(),
            consumer_secret=(e.get("WOOCOMMERCE_CONSUMER_SECRET") or "").strip(),
            mode=mode,
            timeout_seconds=timeout,
            verify_ssl=verify,
            app_env=(e.get("APP_ENV") or "development").strip(),
        )

    # ------------------------------------------------------------------
    def require_live_ready(self) -> None:
        """Raise if any required live-mode value is missing."""
        if not self.is_live:
            return
        missing = []
        if not self.store_url:
            missing.append("WOOCOMMERCE_URL")
        if not self.consumer_key:
            missing.append("WOOCOMMERCE_CONSUMER_KEY")
        if not self.consumer_secret:
            missing.append("WOOCOMMERCE_CONSUMER_SECRET")
        if missing:
            raise WooCommerceConfigurationError(
                "WooCommerce yapılandırması eksik: " + ", ".join(missing),
                code="configuration_missing",
            )
        # Enforce HTTPS in production.
        if self.is_production and self.store_url.startswith("http://"):
            raise WooCommerceSecurityError(
                "Üretim ortamında yalnızca https:// adresi kabul edilir",
                code="unsafe_url",
            )

    def api_base(self) -> str:
        return f"{self.store_url}/wp-json/wc/v3"


# --------------------------------------------------------------------------- #
# Client
# --------------------------------------------------------------------------- #

Resolver = Callable[[str], Iterable[str]]


class WooCommerceClient:
    """Async WooCommerce client. Instantiate per-request; not thread-safe."""

    _MOCK_CATEGORIES = (
        {"id": 1, "name": "Genel", "slug": "genel", "parent": 0},
        {"id": 2, "name": "Test Kategorisi", "slug": "test-kategorisi", "parent": 0},
    )

    def __init__(
        self,
        config: WooCommerceConfig,
        *,
        transport: Optional[httpx.AsyncBaseTransport] = None,
        resolver: Optional[Resolver] = None,
        allow_local_host: bool = False,
    ) -> None:
        self.config = config
        self._transport = transport
        self._resolver = resolver or _default_resolver
        self._allow_local_host = allow_local_host

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    async def test_connection(self) -> dict:
        """Lightweight read-only ping against the WooCommerce REST API."""
        if self.config.is_mock:
            return {
                "connected": True,
                "store_url": self.config.store_url or "",
                "mode": "mock",
                "message": "WooCommerce mock bağlantısı hazır",
            }
        self.config.require_live_ready()
        self._check_host_allowed()
        # Hit the categories endpoint with per_page=1 so the response is tiny.
        await self._request_json("GET", "/products/categories", params={"per_page": 1, "page": 1})
        return {
            "connected": True,
            "store_url": self.config.store_url,
            "mode": "live",
            "message": "WooCommerce bağlantısı başarılı",
        }

    async def get_categories(self) -> List[dict]:
        """Return the full deterministic list of categories."""
        if self.config.is_mock:
            return [dict(c) for c in self._MOCK_CATEGORIES]

        self.config.require_live_ready()
        self._check_host_allowed()

        collected: list[dict] = []
        seen_ids: set[int] = set()
        per_page = 100
        total_pages: Optional[int] = None
        page = 1
        while page <= MAX_CATEGORY_PAGES:
            data, headers = await self._request_json(
                "GET",
                "/products/categories",
                params={"per_page": per_page, "page": page},
                want_headers=True,
            )
            if not isinstance(data, list):
                raise WooCommerceResponseError(
                    "WooCommerce kategori cevabı liste değil",
                    code="invalid_response",
                )
            for raw in data:
                item = self._sanitize_category(raw)
                if item is None:
                    continue
                if item["id"] in seen_ids:
                    continue
                seen_ids.add(item["id"])
                collected.append(item)

            if total_pages is None:
                th = headers.get("x-wp-totalpages") or headers.get("X-WP-TotalPages")
                if th:
                    try:
                        total_pages = int(th)
                    except (TypeError, ValueError):
                        total_pages = None
            if total_pages is not None:
                if page >= total_pages:
                    break
            else:
                if len(data) < per_page:
                    break
            page += 1
        else:  # pragma: no cover - guarded by MAX_CATEGORY_PAGES check
            raise WooCommerceResponseError(
                "WooCommerce kategori sayfası limiti aşıldı",
                code="invalid_response",
            )

        collected.sort(key=lambda c: c["id"])
        return collected

    async def create_product(self, payload: dict) -> dict:
        """Create a WooCommerce product draft. Always forces status='draft'."""
        return await self._send_product("create", payload, external_product_id=None)

    async def update_product(self, external_product_id: int, payload: dict) -> dict:
        """Update an existing WooCommerce product draft."""
        if not isinstance(external_product_id, int) or isinstance(external_product_id, bool) \
                or external_product_id <= 0:
            raise WooCommerceResponseError(
                "Geçersiz WooCommerce ürün kimliği", code="invalid_response"
            )
        return await self._send_product("update", payload, external_product_id=external_product_id)

    # ------------------------------------------------------------------ #
    def _mock_product_id(self, payload: dict) -> int:
        """Deterministic positive integer derived from the payload SKU.

        Same SKU → same mock id, both for create and update.
        """
        import zlib
        seed = str(payload.get("sku") or payload.get("name") or "wc-mock").encode("utf-8")
        return (zlib.crc32(seed) & 0x7FFFFFFF) % 9_000_000 + 1_000_000

    def _normalize_product_response(self, raw: Any) -> dict:
        if not isinstance(raw, dict):
            raise WooCommerceResponseError(
                "WooCommerce ürün cevabı geçersiz", code="invalid_response"
            )
        rid = raw.get("id")
        if not isinstance(rid, int) or isinstance(rid, bool) or rid <= 0:
            raise WooCommerceResponseError(
                "WooCommerce ürün cevabı geçerli bir ID içermiyor",
                code="invalid_response",
            )
        name = raw.get("name") or ""
        permalink = raw.get("permalink") or ""
        if not isinstance(name, str):
            name = ""
        if not isinstance(permalink, str):
            permalink = ""
        return {
            "id": rid,
            "status": "draft",
            "permalink": permalink[:500],
            "name": name[:500],
        }

    async def _send_product(
        self,
        action: str,
        payload: dict,
        *,
        external_product_id: Optional[int],
    ) -> dict:
        # Always force draft. We never accept "publish" here.
        safe_payload = dict(payload)
        safe_payload["status"] = "draft"

        if self.config.is_mock:
            mock_id = external_product_id or self._mock_product_id(safe_payload)
            store = self.config.store_url or "https://mock.woocommerce.local"
            return {
                "id": mock_id,
                "status": "draft",
                "permalink": f"{store}/?p={mock_id}",
                "name": (safe_payload.get("name") or "")[:500],
            }

        self.config.require_live_ready()
        self._check_host_allowed()

        if action == "create":
            method = "POST"
            path = "/products"
        else:
            method = "PUT"
            path = f"/products/{int(external_product_id)}"

        data = await self._request_json(method, path, json_body=safe_payload)
        return self._normalize_product_response(data)

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _check_host_allowed(self) -> None:
        """SSRF guard for live-mode requests."""
        parsed = _urlparse.urlparse(self.config.store_url)
        host = (parsed.hostname or "").lower()
        if not host:
            raise WooCommerceSecurityError(
                "Sunucu adı çözümlenemedi", code="unsafe_url"
            )
        # In non-production dev/test we allow localhost only when explicitly
        # granted. Production always blocks localhost & private ranges.
        allow_local = self._allow_local_host and not self.config.is_production
        if host in ("localhost", "127.0.0.1", "::1"):
            if not allow_local:
                raise WooCommerceSecurityError(
                    "Yerel adres kullanımı engellendi", code="unsafe_url"
                )
            return

        try:
            addresses = list(self._resolver(host))
        except WooCommerceClientError:
            raise
        except Exception as exc:  # pragma: no cover - defensive
            raise WooCommerceConnectionError(
                f"DNS çözümlemesi başarısız: {host}", code="connection_failed"
            ) from exc

        if not addresses:
            raise WooCommerceConnectionError(
                "Sunucu için IP adresi bulunamadı", code="connection_failed"
            )
        for addr in addresses:
            if not _is_public_ip(addr):
                if allow_local and addr in ("127.0.0.1", "::1"):
                    continue
                raise WooCommerceSecurityError(
                    "Hedef IP güvenli değil (private/loopback/metadata)",
                    code="unsafe_url",
                )

    def _build_httpx_client(self) -> httpx.AsyncClient:
        kwargs: dict[str, Any] = {
            "base_url": self.config.api_base(),
            "timeout": httpx.Timeout(self.config.timeout_seconds),
            "follow_redirects": False,
            "verify": self.config.verify_ssl,
            "auth": (self.config.consumer_key, self.config.consumer_secret),
            "headers": {
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
            },
        }
        if self._transport is not None:
            kwargs["transport"] = self._transport
        return httpx.AsyncClient(**kwargs)

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict] = None,
        json_body: Optional[dict] = None,
        want_headers: bool = False,
    ):
        try:
            client = self._build_httpx_client()
        except httpx.InvalidURL as exc:
            raise WooCommerceConfigurationError(
                f"Geçersiz WooCommerce adresi: {_sanitize_message(str(exc), self.config)}",
                code="invalid_url",
            ) from exc

        try:
            async with client:
                try:
                    response = await client.request(method, path, params=params, json=json_body)
                except httpx.TimeoutException as exc:
                    raise WooCommerceTimeoutError(
                        "WooCommerce isteği zaman aşımına uğradı", code="timeout"
                    ) from exc
                except (
                    getattr(httpx, "ConnectError", httpx.HTTPError),
                    getattr(httpx, "ReadError", httpx.HTTPError),
                    getattr(httpx, "NetworkError", httpx.HTTPError),
                ) as exc:
                    text = _sanitize_message(str(exc), self.config).lower()
                    if "ssl" in text or "certificate" in text:
                        raise WooCommerceSSLError(
                            "WooCommerce SSL doğrulaması başarısız", code="ssl_error"
                        ) from exc
                    raise WooCommerceConnectionError(
                        "WooCommerce sunucusuna ulaşılamadı", code="connection_failed"
                    ) from exc
        except WooCommerceClientError:
            raise
        except httpx.HTTPError as exc:
            raise WooCommerceConnectionError(
                "WooCommerce sunucusuna ulaşılamadı", code="connection_failed"
            ) from exc

        return self._process_response(response, want_headers=want_headers)

    def _process_response(self, response: httpx.Response, *, want_headers: bool):
        status = response.status_code

        if status in (301, 302, 303, 307, 308):
            raise WooCommerceSecurityError(
                "WooCommerce sunucusu yönlendirme döndürdü, güvenlik nedeniyle takip edilmedi",
                code="unsafe_redirect",
            )

        # Size guard (Content-Length header + body).
        cl = response.headers.get("content-length")
        if cl:
            try:
                if int(cl) > MAX_RESPONSE_BYTES:
                    raise WooCommerceResponseError(
                        "WooCommerce cevabı beklenenden büyük", code="invalid_response"
                    )
            except ValueError:
                pass

        content = response.content or b""
        if len(content) > MAX_RESPONSE_BYTES:
            raise WooCommerceResponseError(
                "WooCommerce cevabı beklenenden büyük", code="invalid_response"
            )

        # Success path.
        if 200 <= status < 300:
            try:
                data = json.loads(content.decode("utf-8")) if content else None
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise WooCommerceResponseError(
                    "WooCommerce cevabı geçerli JSON değil", code="invalid_json"
                ) from exc
            if want_headers:
                return data, dict(response.headers)
            return data

        # Error path -- extract safe WooCommerce error code/message if any.
        remote_code: Optional[str] = None
        remote_message: Optional[str] = None
        try:
            payload = json.loads(content.decode("utf-8")) if content else None
            if isinstance(payload, dict):
                if isinstance(payload.get("code"), str):
                    remote_code = payload["code"][:64]
                if isinstance(payload.get("message"), str):
                    remote_message = _sanitize_message(payload["message"], self.config)[:200]
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass

        if status == 401:
            raise WooCommerceAuthenticationError(
                remote_message or "WooCommerce kimlik doğrulaması başarısız",
                code="authentication_failed",
            )
        if status == 403:
            raise WooCommercePermissionError(
                remote_message or "WooCommerce yetkisi yetersiz",
                code="permission_denied",
            )
        if status == 404:
            raise WooCommerceAPIError(
                remote_message or "WooCommerce REST API bulunamadı",
                code=remote_code or "not_found",
                status_code=status,
            )
        if status == 408:
            raise WooCommerceTimeoutError(
                remote_message or "WooCommerce isteği zaman aşımına uğradı",
                code="timeout",
            )
        if status == 429:
            raise WooCommerceAPIError(
                remote_message or "WooCommerce hız sınırı aşıldı",
                code=remote_code or "rate_limited",
                status_code=status,
            )
        if 500 <= status < 600:
            raise WooCommerceAPIError(
                remote_message or "WooCommerce uzak sunucu hatası",
                code=remote_code or "server_error",
                status_code=status,
            )
        raise WooCommerceAPIError(
            remote_message or "WooCommerce API hatası",
            code=remote_code or "api_error",
            status_code=status,
        )

    # ------------------------------------------------------------------ #
    def _sanitize_category(self, raw: Any) -> Optional[dict]:
        if not isinstance(raw, dict):
            return None
        cid = raw.get("id")
        if not isinstance(cid, int) or isinstance(cid, bool) or cid <= 0:
            return None
        name = raw.get("name")
        if not isinstance(name, str) or not name.strip():
            return None
        slug = raw.get("slug") or ""
        if not isinstance(slug, str):
            return None
        parent = raw.get("parent", 0)
        if not isinstance(parent, int) or isinstance(parent, bool) or parent < 0:
            return None
        return {"id": cid, "name": name.strip(), "slug": slug.strip(), "parent": parent}


__all__ = [
    "WooCommerceClient",
    "WooCommerceConfig",
    "WooCommerceClientError",
    "WooCommerceConfigurationError",
    "WooCommerceSecurityError",
    "WooCommerceAuthenticationError",
    "WooCommercePermissionError",
    "WooCommerceTimeoutError",
    "WooCommerceSSLError",
    "WooCommerceConnectionError",
    "WooCommerceResponseError",
    "WooCommerceAPIError",
    "USER_AGENT",
    "MAX_RESPONSE_BYTES",
    "MAX_CATEGORY_PAGES",
]
