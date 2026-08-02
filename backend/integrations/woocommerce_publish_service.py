"""Single-product WooCommerce draft publishing (Phase 3A Part B1).

All business logic for turning an approved Merchant Core suggestion into a
WooCommerce product draft lives here. Kept out of ``server.py`` and route
files by design.

The service performs:
    * publish precondition validation (returns Turkish blocking reasons),
    * neutral payload construction that never invents data,
    * idempotent ProductPublication row upserting (create vs update),
    * Activity logging (exactly one entry per attempt),
    * safe error snapshotting (never contains credentials).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import merchant_service
from integrations.woocommerce_client import (
    WooCommerceClient,
    WooCommerceClientError,
)
from models import (
    Activity,
    CategoryMapping,
    Product,
    ProductPublication,
    ProductSuggestion,
)

logger = logging.getLogger("merchant-os.publish")

CHANNEL = "woocommerce"
_SNAPSHOT_LIMIT = 8_000

_ALLOWED_META_KEYS = {
    "ai_merchant_os_seo_title",
    "ai_merchant_os_meta_description",
    "ai_merchant_os_tags",
}


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #

class PublishPreconditionError(Exception):
    """Raised when preconditions fail. Message is Turkish and safe."""

    def __init__(self, reasons: list[str]) -> None:
        self.reasons = reasons
        super().__init__("; ".join(reasons))


# --------------------------------------------------------------------------- #
# Dataclasses
# --------------------------------------------------------------------------- #

@dataclass
class PublishResult:
    action: str  # "draft_created" | "draft_updated"
    publication: ProductPublication
    external_response: dict


# --------------------------------------------------------------------------- #
# Precondition validation
# --------------------------------------------------------------------------- #

def _load_approved_suggestion(db: Session, product: Product) -> Optional[ProductSuggestion]:
    if not product.active_suggestion_id:
        return None
    sug = db.get(ProductSuggestion, product.active_suggestion_id)
    if sug is None or sug.suggestion_status != "approved":
        return None
    return sug


def check_preconditions(
    db: Session,
    product: Product,
    client: WooCommerceClient,
) -> tuple[Optional[ProductSuggestion], Optional[CategoryMapping], list[str]]:
    """Return (approved suggestion, category mapping, blocking reasons)."""
    reasons: list[str] = []

    if product.workflow_status not in ("ready_to_publish", "sent_as_draft"):
        reasons.append("Ürün yayına hazır değil")

    suggestion = _load_approved_suggestion(db, product)
    if suggestion is None:
        reasons.append("Onaylı öneri bulunamadı")

    ok, blockers = merchant_service.passes_publish_validation(product, suggestion)
    if not ok:
        # Merge but keep unique.
        for r in blockers:
            if r not in reasons:
                reasons.append(r)

    candidate = merchant_service.effective_candidate(product, suggestion)
    category = (candidate.get("category") or "").strip()
    mapping: Optional[CategoryMapping] = None
    if category:
        mapping = (
            db.query(CategoryMapping)
            .filter(
                CategoryMapping.channel == CHANNEL,
                CategoryMapping.local_category == category,
            )
            .one_or_none()
        )
        if mapping is None:
            reasons.append("WooCommerce kategori eşleştirmesi eksik")

    # Config sanity for live mode.
    cfg = client.config
    if cfg.is_live and not cfg.has_credentials:
        reasons.append("WooCommerce yapılandırması eksik")

    return suggestion, mapping, reasons


# --------------------------------------------------------------------------- #
# Payload
# --------------------------------------------------------------------------- #

def _tags_from_suggestion(suggestion: ProductSuggestion) -> list[str]:
    if not suggestion.suggested_tags:
        return []
    try:
        data = json.loads(suggestion.suggested_tags)
    except (TypeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [str(t).strip() for t in data if isinstance(t, str) and t.strip()]


def build_woocommerce_payload(
    product: Product,
    suggestion: ProductSuggestion,
    mapping: CategoryMapping,
) -> dict:
    """Build the WooCommerce request body from the effective candidate.

    Approved suggestion fields override name/description/category/SEO/tags.
    Original product supplies sku/price/stock/image. status is always draft.
    Source product_url is never used as permalink.
    """
    candidate = merchant_service.effective_candidate(product, suggestion)
    name = (candidate.get("name") or "").strip()
    description = (candidate.get("description") or "").strip()
    sku = (candidate.get("sku") or "").strip()

    payload: dict = {
        "name": name,
        "type": "simple",
        "status": "draft",
        "sku": sku,
        "regular_price": f"{float(candidate['price']):.2f}",
        "description": description,
        "manage_stock": True,
        "stock_quantity": int(candidate.get("stock") or 0),
        "categories": [{"id": int(mapping.external_category_id)}],
    }

    image_url = (candidate.get("image_url") or "").strip()
    if image_url.startswith(("http://", "https://")):
        payload["images"] = [{"src": image_url}]

    meta: list[dict] = []
    seo = (suggestion.suggested_seo_title or "").strip()
    if seo:
        meta.append({"key": "ai_merchant_os_seo_title", "value": seo})
    meta_desc = (suggestion.suggested_meta_description or "").strip()
    if meta_desc:
        meta.append({"key": "ai_merchant_os_meta_description", "value": meta_desc})
    tags = _tags_from_suggestion(suggestion)
    if tags:
        meta.append({"key": "ai_merchant_os_tags", "value": ", ".join(tags)})

    # Defensive: only keep meta keys from the approved allowlist.
    payload["meta_data"] = [m for m in meta if m.get("key") in _ALLOWED_META_KEYS]

    return payload


# --------------------------------------------------------------------------- #
# Snapshotting
# --------------------------------------------------------------------------- #

def _sanitize_and_serialize(obj: object) -> str:
    """Serialize to JSON, truncate. Never returns credentials because the
    input never contains them (payloads/responses built here only reference
    already-sanitized product data)."""
    try:
        text = json.dumps(obj, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = json.dumps({"note": "unserializable"})
    if len(text) > _SNAPSHOT_LIMIT:
        text = text[:_SNAPSHOT_LIMIT] + "…"
    return text


# --------------------------------------------------------------------------- #
# Idempotent upsert
# --------------------------------------------------------------------------- #

def _get_or_create_publication(db: Session, product: Product) -> ProductPublication:
    row = (
        db.query(ProductPublication)
        .filter(
            ProductPublication.product_id == product.id,
            ProductPublication.channel == CHANNEL,
        )
        .one_or_none()
    )
    if row is not None:
        return row
    row = ProductPublication(
        product_id=product.id,
        channel=CHANNEL,
        publication_status="pending",
        attempt_count=0,
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        row = (
            db.query(ProductPublication)
            .filter(
                ProductPublication.product_id == product.id,
                ProductPublication.channel == CHANNEL,
            )
            .one_or_none()
        )
        if row is None:  # pragma: no cover - defensive
            raise
    return row


# --------------------------------------------------------------------------- #
# Public entrypoint
# --------------------------------------------------------------------------- #

async def publish_product_to_woocommerce(
    db: Session,
    product: Product,
    client: WooCommerceClient,
) -> PublishResult:
    """Publish (or re-publish) a single product as a WooCommerce draft."""
    suggestion, mapping, reasons = check_preconditions(db, product, client)
    if reasons:
        raise PublishPreconditionError(reasons)

    assert suggestion is not None and mapping is not None  # for type checkers
    payload = build_woocommerce_payload(product, suggestion, mapping)

    # Ensure we have a publication row *before* the remote call so attempt
    # counters can be persisted regardless of outcome.
    publication = _get_or_create_publication(db, product)
    existing_external_id: Optional[int] = None
    if publication.external_product_id:
        try:
            existing_external_id = int(publication.external_product_id)
            if existing_external_id <= 0:
                existing_external_id = None
        except (TypeError, ValueError):
            existing_external_id = None

    # Commit the pending record + reserve a unique row before the slow call so
    # concurrent duplicate attempts hit the DB constraint.
    db.commit()
    db.refresh(publication)

    action = "draft_updated" if existing_external_id is not None else "draft_created"
    try:
        if existing_external_id is not None:
            response = await client.update_product(existing_external_id, payload)
        else:
            response = await client.create_product(payload)
    except WooCommerceClientError as exc:
        _record_failure(db, product, publication, payload, exc)
        db.commit()
        raise

    _record_success(
        db,
        product=product,
        publication=publication,
        payload=payload,
        response=response,
        action=action,
    )
    db.commit()
    db.refresh(publication)
    db.refresh(product)
    return PublishResult(action=action, publication=publication, external_response=response)


def _record_success(
    db: Session,
    *,
    product: Product,
    publication: ProductPublication,
    payload: dict,
    response: dict,
    action: str,
) -> None:
    now = datetime.now(timezone.utc)
    publication.attempt_count = (publication.attempt_count or 0) + 1
    publication.external_product_id = str(response["id"])
    publication.external_url = response.get("permalink") or None
    publication.publication_status = action
    publication.payload_snapshot = _sanitize_and_serialize(payload)
    publication.response_snapshot = _sanitize_and_serialize(response)
    publication.last_error = None
    publication.last_success_at = now
    publication.updated_at = now

    product.workflow_status = "sent_as_draft"

    message = (
        "Ürün WooCommerce'e taslak olarak gönderildi"
        if action == "draft_created"
        else "WooCommerce ürün taslağı güncellendi"
    )
    db.add(Activity(
        kind="integration",
        message=(
            f"{message}: {product.sku} → #{response['id']}"
        ),
    ))


def _record_failure(
    db: Session,
    product: Product,
    publication: ProductPublication,
    payload: dict,
    exc: WooCommerceClientError,
) -> None:
    now = datetime.now(timezone.utc)
    publication.attempt_count = (publication.attempt_count or 0) + 1
    publication.publication_status = "failed"
    publication.payload_snapshot = _sanitize_and_serialize(payload)
    # Preserve previous success info (external_product_id, external_url,
    # last_success_at) — set by prior successful attempts.
    short_error = (exc.message or "")[:500]
    publication.last_error = json.dumps(
        {"code": exc.code, "message": short_error},
        ensure_ascii=False,
    )
    publication.response_snapshot = None
    publication.updated_at = now

    db.add(Activity(
        kind="integration",
        message=(
            f"WooCommerce taslak gönderimi başarısız: {product.sku} ({exc.code})"
        ),
    ))
