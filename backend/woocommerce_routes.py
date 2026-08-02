"""FastAPI router for WooCommerce integration endpoints (Phase 3A Part A).

Provides:
    GET  /api/integrations/woocommerce/status
    POST /api/integrations/woocommerce/test
    GET  /api/integrations/woocommerce/categories
    GET  /api/integrations/woocommerce/category-mappings
    POST /api/integrations/woocommerce/category-mappings
    DELETE /api/integrations/woocommerce/category-mappings/{mapping_id}

Never makes a real HTTP call when ``WOOCOMMERCE_MODE=mock``.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database import get_db
from integrations.woocommerce_client import (
    WooCommerceAPIError,
    WooCommerceAuthenticationError,
    WooCommerceClient,
    WooCommerceClientError,
    WooCommerceConfig,
    WooCommerceConfigurationError,
    WooCommerceConnectionError,
    WooCommercePermissionError,
    WooCommerceResponseError,
    WooCommerceSSLError,
    WooCommerceSecurityError,
    WooCommerceTimeoutError,
)
from models import Activity, CategoryMapping
from woocommerce_schemas import (
    CategoryMappingCreate,
    CategoryMappingDeleteResponse,
    CategoryMappingListResponse,
    CategoryMappingMutationResponse,
    CategoryMappingResponse,
    WooCommerceCategoryListResponse,
    WooCommerceCategoryResponse,
    WooCommerceStatusResponse,
    WooCommerceTestResponse,
)

router = APIRouter(prefix="/api/integrations/woocommerce", tags=["woocommerce"])

CHANNEL = "woocommerce"


# --------------------------------------------------------------------------- #
# In-memory connection status (reset on process restart)
# --------------------------------------------------------------------------- #

class _ConnectionStatus:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self.connected: bool = False
        self.last_checked_at: Optional[datetime] = None
        self.last_error: Optional[str] = None

    async def record_success(self) -> None:
        async with self._lock:
            self.connected = True
            self.last_checked_at = datetime.now(timezone.utc)
            self.last_error = None

    async def record_failure(self, error: str) -> None:
        async with self._lock:
            self.connected = False
            self.last_checked_at = datetime.now(timezone.utc)
            self.last_error = error

    def snapshot(self) -> dict:
        return {
            "connected": self.connected,
            "last_checked_at": self.last_checked_at,
            "last_error": self.last_error,
        }

    def reset(self) -> None:
        self.connected = False
        self.last_checked_at = None
        self.last_error = None


_status_state = _ConnectionStatus()


def _reset_status_state_for_tests() -> None:
    """Helper for tests only."""
    _status_state.reset()


# --------------------------------------------------------------------------- #
# Dependency
# --------------------------------------------------------------------------- #

def get_woocommerce_client() -> WooCommerceClient:
    """Build a client from the current environment. Override in tests."""
    config = WooCommerceConfig.from_env()
    return WooCommerceClient(config)


# --------------------------------------------------------------------------- #
# Error mapping
# --------------------------------------------------------------------------- #

def map_woocommerce_error_to_http_exception(exc: WooCommerceClientError) -> HTTPException:
    if isinstance(exc, WooCommerceConfigurationError):
        return HTTPException(status_code=400, detail=exc.message)
    if isinstance(exc, WooCommerceSecurityError):
        return HTTPException(status_code=400, detail=exc.message)
    if isinstance(exc, WooCommerceAuthenticationError):
        return HTTPException(status_code=401, detail=exc.message)
    if isinstance(exc, WooCommercePermissionError):
        return HTTPException(status_code=403, detail=exc.message)
    if isinstance(exc, WooCommerceTimeoutError):
        return HTTPException(status_code=504, detail=exc.message)
    if isinstance(exc, WooCommerceSSLError):
        return HTTPException(status_code=502, detail=exc.message)
    if isinstance(exc, WooCommerceConnectionError):
        return HTTPException(status_code=502, detail=exc.message)
    if isinstance(exc, WooCommerceResponseError):
        return HTTPException(status_code=502, detail=exc.message)
    if isinstance(exc, WooCommerceAPIError):
        code = getattr(exc, "status_code", None)
        if code == 429:
            return HTTPException(status_code=429, detail=exc.message)
        if code and 400 <= code < 500:
            return HTTPException(status_code=400, detail=exc.message)
        return HTTPException(status_code=502, detail=exc.message)
    return HTTPException(status_code=502, detail="WooCommerce hatası")


# --------------------------------------------------------------------------- #
# Serializers
# --------------------------------------------------------------------------- #

def _mapping_to_response(m: CategoryMapping) -> CategoryMappingResponse:
    created = m.created_at
    if created and created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    updated = m.updated_at
    if updated and updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    return CategoryMappingResponse(
        id=m.id,
        channel=m.channel,
        local_category=m.local_category,
        external_category_id=m.external_category_id,
        external_category_name=m.external_category_name,
        created_at=created,
        updated_at=updated,
    )


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #

@router.get("/status", response_model=WooCommerceStatusResponse)
def get_status(client: WooCommerceClient = Depends(get_woocommerce_client)):
    cfg = client.config
    snap = _status_state.snapshot()

    if cfg.is_mock:
        return WooCommerceStatusResponse(
            configured=True,
            connected=True,
            mode="mock",
            store_url=cfg.store_url or None,
            last_checked_at=snap["last_checked_at"],
            error=None,
            message="WooCommerce mock modu hazır",
        )

    # live
    if not cfg.has_credentials:
        return WooCommerceStatusResponse(
            configured=False,
            connected=False,
            mode="live",
            store_url=cfg.store_url or None,
            last_checked_at=snap["last_checked_at"],
            error=snap["last_error"],
            message="WooCommerce yapılandırması eksik",
        )

    if snap["last_checked_at"] is None:
        return WooCommerceStatusResponse(
            configured=True,
            connected=False,
            mode="live",
            store_url=cfg.store_url,
            last_checked_at=None,
            error=None,
            message="WooCommerce bağlantısı henüz test edilmedi",
        )

    return WooCommerceStatusResponse(
        configured=True,
        connected=snap["connected"],
        mode="live",
        store_url=cfg.store_url,
        last_checked_at=snap["last_checked_at"],
        error=snap["last_error"],
        message=(
            "WooCommerce bağlantısı aktif" if snap["connected"]
            else "WooCommerce bağlantısı başarısız"
        ),
    )


@router.post("/test", response_model=WooCommerceTestResponse)
async def post_test(client: WooCommerceClient = Depends(get_woocommerce_client)):
    cfg = client.config
    try:
        result = await client.test_connection()
    except WooCommerceClientError as exc:
        await _status_state.record_failure(exc.message)
        raise map_woocommerce_error_to_http_exception(exc) from None

    await _status_state.record_success()
    return WooCommerceTestResponse(
        connected=bool(result.get("connected")),
        configured=cfg.is_mock or cfg.has_credentials,
        mode=result.get("mode", cfg.mode),
        store_url=result.get("store_url") or (cfg.store_url or None),
        checked_at=datetime.now(timezone.utc),
        message=result.get("message", ""),
    )


@router.get("/categories", response_model=WooCommerceCategoryListResponse)
async def get_categories(client: WooCommerceClient = Depends(get_woocommerce_client)):
    try:
        categories = await client.get_categories()
    except WooCommerceClientError as exc:
        raise map_woocommerce_error_to_http_exception(exc) from None
    return WooCommerceCategoryListResponse(
        mode=client.config.mode,
        count=len(categories),
        categories=[WooCommerceCategoryResponse(**c) for c in categories],
    )


# --------------------------------------------------------------------------- #
# Category mappings CRUD
# --------------------------------------------------------------------------- #

@router.get("/category-mappings", response_model=CategoryMappingListResponse)
def list_category_mappings(
    local_category: Optional[str] = Query(default=None, max_length=200),
    db: Session = Depends(get_db),
):
    q = db.query(CategoryMapping).filter(CategoryMapping.channel == CHANNEL)
    if local_category is not None:
        target = local_category.strip()
        if target:
            q = q.filter(CategoryMapping.local_category == target)
    rows = q.order_by(CategoryMapping.local_category.asc()).all()
    return CategoryMappingListResponse(
        count=len(rows),
        mappings=[_mapping_to_response(m) for m in rows],
    )


@router.post("/category-mappings", response_model=CategoryMappingMutationResponse)
async def create_or_update_category_mapping(
    payload: CategoryMappingCreate,
    response: Response,
    db: Session = Depends(get_db),
    client: WooCommerceClient = Depends(get_woocommerce_client),
):
    # Remote validation: make sure the category exists on the channel.
    try:
        remote_categories = await client.get_categories()
    except WooCommerceClientError as exc:
        raise map_woocommerce_error_to_http_exception(exc) from None

    if not any(c["id"] == payload.external_category_id for c in remote_categories):
        raise HTTPException(
            status_code=422,
            detail="Seçilen WooCommerce kategorisi bulunamadı",
        )

    external_name = payload.external_category_name.strip()

    existing = (
        db.query(CategoryMapping)
        .filter(
            CategoryMapping.channel == CHANNEL,
            CategoryMapping.local_category == payload.local_category,
        )
        .one_or_none()
    )

    if existing is not None:
        changed = (
            existing.external_category_id != payload.external_category_id
            or existing.external_category_name != external_name
        )
        if changed:
            existing.external_category_id = payload.external_category_id
            existing.external_category_name = external_name
            existing.updated_at = datetime.now(timezone.utc)
        db.add(
            Activity(
                kind="integration",
                message=(
                    f"WooCommerce kategori eşleştirmesi güncellendi: "
                    f"{existing.local_category} → {external_name} (#{payload.external_category_id})"
                ),
            )
        )
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, detail="Kategori eşleştirmesi güncellenemedi")
        db.refresh(existing)
        response.status_code = 200
        return CategoryMappingMutationResponse(
            created=False,
            updated=True,
            mapping=_mapping_to_response(existing),
            message="Kategori eşleştirmesi güncellendi",
        )

    row = CategoryMapping(
        channel=CHANNEL,
        local_category=payload.local_category,
        external_category_id=payload.external_category_id,
        external_category_name=external_name,
    )
    db.add(row)
    db.add(
        Activity(
            kind="integration",
            message=(
                f"WooCommerce kategori eşleştirmesi oluşturuldu: "
                f"{payload.local_category} → {external_name} (#{payload.external_category_id})"
            ),
        )
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        # Race with another writer -- fetch the existing row.
        existing = (
            db.query(CategoryMapping)
            .filter(
                CategoryMapping.channel == CHANNEL,
                CategoryMapping.local_category == payload.local_category,
            )
            .one_or_none()
        )
        if existing is None:
            raise HTTPException(409, detail="Kategori eşleştirmesi kaydedilemedi") from None
        response.status_code = 200
        return CategoryMappingMutationResponse(
            created=False,
            updated=True,
            mapping=_mapping_to_response(existing),
            message="Kategori eşleştirmesi güncellendi",
        )
    db.refresh(row)
    response.status_code = 201
    return CategoryMappingMutationResponse(
        created=True,
        updated=False,
        mapping=_mapping_to_response(row),
        message="Kategori eşleştirmesi oluşturuldu",
    )


@router.delete(
    "/category-mappings/{mapping_id}",
    response_model=CategoryMappingDeleteResponse,
)
def delete_category_mapping(mapping_id: str, db: Session = Depends(get_db)):
    row = (
        db.query(CategoryMapping)
        .filter(CategoryMapping.id == mapping_id, CategoryMapping.channel == CHANNEL)
        .one_or_none()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Kategori eşleştirmesi bulunamadı")
    local = row.local_category
    ext_id = row.external_category_id
    db.delete(row)
    db.add(
        Activity(
            kind="integration",
            message=f"WooCommerce kategori eşleştirmesi silindi: {local} (#{ext_id})",
        )
    )
    db.commit()
    return CategoryMappingDeleteResponse(
        deleted=True,
        id=mapping_id,
        message="Kategori eşleştirmesi silindi",
    )
