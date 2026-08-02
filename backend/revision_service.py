"""Serialize product/suggestion snapshots and record revisions."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from models import Product, ProductRevision, ProductSuggestion


def _dt(v):
    if isinstance(v, datetime):
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        return v.isoformat().replace("+00:00", "Z")
    return v


def snapshot_product(p: Product) -> dict:
    return {
        "id": p.id,
        "sku": p.sku,
        "name": p.name,
        "description": p.description,
        "category": p.category,
        "price": p.price,
        "stock": p.stock,
        "image_url": p.image_url,
        "product_url": p.product_url,
        "workflow_status": p.workflow_status,
        "quality_score": p.quality_score,
        "active_suggestion_id": p.active_suggestion_id,
        "updated_at": _dt(p.updated_at),
    }


def snapshot_suggestion(s: Optional[ProductSuggestion]) -> Optional[dict]:
    if s is None:
        return None
    return {
        "id": s.id,
        "product_id": s.product_id,
        "suggested_name": s.suggested_name,
        "suggested_description": s.suggested_description,
        "suggested_category": s.suggested_category,
        "suggested_seo_title": s.suggested_seo_title,
        "suggested_meta_description": s.suggested_meta_description,
        "suggested_tags": s.suggested_tags,
        "provider": s.provider,
        "model": s.model,
        "suggestion_status": s.suggestion_status,
        "created_at": _dt(s.created_at),
        "updated_at": _dt(s.updated_at),
        "approved_at": _dt(s.approved_at),
    }


def _dumps(obj) -> Optional[str]:
    if obj is None:
        return None
    return json.dumps(obj, ensure_ascii=False, default=_dt)


def loads(text: Optional[str]) -> Optional[dict]:
    if not text:
        return None
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return None


def create_revision(
    db: Session,
    *,
    product_id: str,
    action_type: str,
    source: str,
    before: Optional[dict],
    after: Optional[dict],
) -> ProductRevision:
    rev = ProductRevision(
        product_id=product_id,
        action_type=action_type,
        source=source,
        before_snapshot=_dumps(before),
        after_snapshot=_dumps(after),
    )
    db.add(rev)
    db.flush()
    return rev
