"""Phase 2 Merchant Core routes: quality, suggestions, approval, revisions."""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ai_service import AIProviderError
from database import get_db
from models import (
    Activity, Product, ProductIssue, ProductRevision, ProductSuggestion,
)
import merchant_service
import revision_service

router = APIRouter(prefix="/api")

MAX_BULK = 500


def _iso_utc(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


# ---------------- Schemas ----------------
class BulkIdsIn(BaseModel):
    ids: List[str] = Field(min_length=1, max_length=MAX_BULK)


class SuggestionUpdate(BaseModel):
    suggested_name: Optional[str] = None
    suggested_description: Optional[str] = None
    suggested_category: Optional[str] = None
    suggested_seo_title: Optional[str] = Field(default=None, max_length=120)
    suggested_meta_description: Optional[str] = Field(default=None, max_length=320)
    suggested_tags: Optional[List[str]] = None


# ---------------- Serialization ----------------
def _issue_dict(i: ProductIssue) -> dict:
    return {
        "id": i.id,
        "product_id": i.product_id,
        "issue_code": i.issue_code,
        "field_name": i.field_name,
        "severity": i.severity,
        "message": i.message,
        "recommendation": i.recommendation,
        "is_resolved": i.is_resolved,
        "created_at": _iso_utc(i.created_at),
        "resolved_at": _iso_utc(i.resolved_at),
    }


def _suggestion_dict(s: Optional[ProductSuggestion]) -> Optional[dict]:
    if s is None:
        return None
    try:
        tags = json.loads(s.suggested_tags) if s.suggested_tags else []
        if not isinstance(tags, list):
            tags = []
    except (TypeError, ValueError):
        tags = []
    return {
        "id": s.id,
        "product_id": s.product_id,
        "suggested_name": s.suggested_name,
        "suggested_description": s.suggested_description,
        "suggested_category": s.suggested_category,
        "suggested_seo_title": s.suggested_seo_title,
        "suggested_meta_description": s.suggested_meta_description,
        "suggested_tags": tags,
        "provider": s.provider,
        "model": s.model,
        "suggestion_status": s.suggestion_status,
        "created_at": _iso_utc(s.created_at),
        "updated_at": _iso_utc(s.updated_at),
        "approved_at": _iso_utc(s.approved_at),
    }


def _revision_dict(r: ProductRevision) -> dict:
    return {
        "id": r.id,
        "product_id": r.product_id,
        "action_type": r.action_type,
        "source": r.source,
        "before_snapshot": revision_service.loads(r.before_snapshot),
        "after_snapshot": revision_service.loads(r.after_snapshot),
        "created_at": _iso_utc(r.created_at),
    }


def _get_product_or_404(db: Session, pid: str) -> Product:
    p = db.get(Product, pid)
    if not p:
        raise HTTPException(404, "Ürün bulunamadı")
    return p


# ---------------- Quality ----------------
@router.post("/products/{pid}/analyze")
def analyze_one(pid: str, db: Session = Depends(get_db)):
    p = _get_product_or_404(db, pid)
    result = merchant_service.analyze_and_transition(db, p)
    db.add(Activity(kind="edit", message=f"Kalite analizi yapıldı: {p.sku} (skor {result['score']})"))
    db.commit()
    db.refresh(p)
    return {
        "product_id": p.id,
        "score": p.quality_score,
        "workflow_status": p.workflow_status,
        "issues": [_issue_dict(i) for i in
                   db.query(ProductIssue).filter(ProductIssue.product_id == p.id,
                                                 ProductIssue.is_resolved.is_(False)).all()],
    }


@router.get("/products/{pid}/issues")
def list_issues(pid: str, db: Session = Depends(get_db)):
    _get_product_or_404(db, pid)
    rows = (db.query(ProductIssue)
            .filter(ProductIssue.product_id == pid, ProductIssue.is_resolved.is_(False))
            .order_by(ProductIssue.severity.desc()).all())
    return [_issue_dict(i) for i in rows]


@router.post("/products/analyze-all")
def analyze_all(db: Session = Depends(get_db)):
    products = db.query(Product).all()
    for p in products:
        merchant_service.analyze_and_transition(db, p)
    db.add(Activity(kind="bulk", message=f"Tüm katalog analiz edildi: {len(products)} ürün"))
    db.commit()
    return {"processed": len(products)}


# ---------------- Suggestions ----------------
@router.post("/products/{pid}/suggest")
async def create_suggestion_endpoint(pid: str, db: Session = Depends(get_db)):
    p = _get_product_or_404(db, pid)
    try:
        suggestion = await merchant_service.create_suggestion(db, p)
    except AIProviderError as exc:
        db.rollback()
        raise HTTPException(502, f"AI sağlayıcı hatası: {exc}")
    db.commit()
    db.refresh(p)
    return _suggestion_dict(suggestion)


@router.get("/products/{pid}/suggestion")
def get_active_suggestion(pid: str, db: Session = Depends(get_db)):
    p = _get_product_or_404(db, pid)
    if not p.active_suggestion_id:
        return None
    return _suggestion_dict(db.get(ProductSuggestion, p.active_suggestion_id))


@router.patch("/products/{pid}/suggestion")
def patch_suggestion(pid: str, payload: SuggestionUpdate, db: Session = Depends(get_db)):
    p = _get_product_or_404(db, pid)
    updates = payload.model_dump(exclude_unset=True)
    try:
        s = merchant_service.update_suggestion(db, p, updates)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    db.commit()
    return _suggestion_dict(s)


@router.post("/products/{pid}/suggestion/approve")
def approve(pid: str, db: Session = Depends(get_db)):
    p = _get_product_or_404(db, pid)
    try:
        s, info = merchant_service.approve_suggestion(db, p)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    db.commit()
    db.refresh(p)
    return {
        "suggestion": _suggestion_dict(s),
        "workflow_status": p.workflow_status,
        "ready_to_publish": info["ready_to_publish"],
        "blocking_reasons": info["blocking_reasons"],
    }


@router.post("/products/{pid}/suggestion/reject")
def reject(pid: str, db: Session = Depends(get_db)):
    p = _get_product_or_404(db, pid)
    try:
        s = merchant_service.reject_suggestion(db, p)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    db.commit()
    db.refresh(p)
    return {"suggestion": _suggestion_dict(s), "workflow_status": p.workflow_status}


# ---------------- Revisions ----------------
@router.get("/products/{pid}/revisions")
def list_revisions(pid: str, db: Session = Depends(get_db)):
    _get_product_or_404(db, pid)
    rows = (db.query(ProductRevision)
            .filter(ProductRevision.product_id == pid)
            .order_by(ProductRevision.created_at.desc()).limit(100).all())
    return [_revision_dict(r) for r in rows]


@router.post("/products/{pid}/revisions/{rev_id}/revert")
def revert(pid: str, rev_id: str, db: Session = Depends(get_db)):
    p = _get_product_or_404(db, pid)
    try:
        merchant_service.revert_to_revision(db, p, rev_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    db.commit()
    db.refresh(p)
    return {
        "workflow_status": p.workflow_status,
        "active_suggestion": _suggestion_dict(
            db.get(ProductSuggestion, p.active_suggestion_id) if p.active_suggestion_id else None
        ),
    }


# ---------------- Bulk ----------------
@router.post("/bulk/analyze")
def bulk_analyze(payload: BulkIdsIn, db: Session = Depends(get_db)):
    result = merchant_service.analyze_bulk(db, payload.ids)
    db.commit()
    return result


@router.post("/bulk/suggest")
async def bulk_suggest(payload: BulkIdsIn, db: Session = Depends(get_db)):
    products = db.query(Product).filter(Product.id.in_(payload.ids)).all()
    processed = failed = 0
    failures: list[dict] = []
    for p in products:
        try:
            await merchant_service.create_suggestion(db, p)
            db.commit()  # persist each success independently
            processed += 1
        except AIProviderError as exc:
            # This product's pending changes get rolled back; prior committed
            # products are safe. Continue with the next product so a transient
            # provider error doesn't stop the batch.
            db.rollback()
            failed += 1
            failures.append({"product_id": p.id, "sku": p.sku, "reason": str(exc)})
        except Exception as exc:
            db.rollback()
            failed += 1
            failures.append({"product_id": p.id, "sku": p.sku, "reason": str(exc)})
    db.add(Activity(kind="bulk", message=f"Toplu AI önerisi: {processed} başarılı, {failed} hata"))
    db.commit()
    return {"processed": processed, "failed": failed, "failures": failures}


@router.post("/bulk/approve")
def bulk_approve(payload: BulkIdsIn, db: Session = Depends(get_db)):
    products = db.query(Product).filter(Product.id.in_(payload.ids)).all()
    approved = skipped = failed = 0
    skipped_reasons: list[dict] = []
    for p in products:
        if not p.active_suggestion_id:
            skipped += 1
            skipped_reasons.append({"product_id": p.id, "sku": p.sku, "reason": "Aktif öneri yok"})
            continue
        sug = db.get(ProductSuggestion, p.active_suggestion_id)
        if sug is None or sug.suggestion_status != "draft":
            skipped += 1
            skipped_reasons.append({"product_id": p.id, "sku": p.sku, "reason": "Onaya uygun taslak öneri yok"})
            continue
        # Pre-check: would approving this suggestion make the effective
        # candidate publishable? If not, DO NOT mutate the suggestion.
        ok, blocking = merchant_service.would_publish_if_approved(p, sug)
        if not ok:
            skipped += 1
            skipped_reasons.append({
                "product_id": p.id, "sku": p.sku,
                "reason": "Yayına hazır değil: " + ", ".join(blocking),
            })
            continue
        try:
            merchant_service.approve_suggestion(db, p)
            approved += 1
        except ValueError as exc:
            failed += 1
            skipped_reasons.append({"product_id": p.id, "sku": p.sku, "reason": str(exc)})
    db.add(Activity(kind="bulk", message=f"Toplu onaylama: {approved} onaylandı, {skipped} atlandı, {failed} hata"))
    db.commit()
    return {
        "processed": len(products),
        "approved": approved,
        "skipped": skipped,
        "failed": failed,
        "reasons": skipped_reasons,
    }


@router.post("/bulk/reject")
def bulk_reject(payload: BulkIdsIn, db: Session = Depends(get_db)):
    products = db.query(Product).filter(Product.id.in_(payload.ids)).all()
    rejected = skipped = 0
    for p in products:
        if not p.active_suggestion_id:
            skipped += 1
            continue
        try:
            merchant_service.reject_suggestion(db, p)
            rejected += 1
        except ValueError:
            skipped += 1
    db.add(Activity(kind="bulk", message=f"Toplu red: {rejected} red, {skipped} atlandı"))
    db.commit()
    return {"processed": len(products), "rejected": rejected, "skipped": skipped}


# ---------------- Ready-to-publish export ----------------
@router.get("/export/ready-to-publish")
def export_ready_to_publish(db: Session = Depends(get_db)):
    products = db.query(Product).filter(Product.workflow_status == "ready_to_publish").all()
    buf = io.StringIO()
    buf.write("\ufeff")
    writer = csv.writer(buf)
    writer.writerow([
        "sku", "approved_name", "approved_description", "approved_category",
        "seo_title", "meta_description", "tags",
        "price", "stock", "image_url", "product_url",
        "quality_score", "workflow_status",
    ])
    for p in products:
        sug = db.get(ProductSuggestion, p.active_suggestion_id) if p.active_suggestion_id else None
        try:
            tags_list = json.loads(sug.suggested_tags) if sug and sug.suggested_tags else []
        except (TypeError, ValueError):
            tags_list = []
        writer.writerow([
            p.sku,
            (sug.suggested_name if sug else p.name) or "",
            (sug.suggested_description if sug else p.description) or "",
            (sug.suggested_category if sug else p.category) or "",
            (sug.suggested_seo_title if sug else "") or "",
            (sug.suggested_meta_description if sug else "") or "",
            ", ".join(tags_list),
            p.price if p.price is not None else "",
            p.stock if p.stock is not None else "",
            p.image_url or "",
            p.product_url or "",
            p.quality_score if p.quality_score is not None else "",
            p.workflow_status,
        ])
    db.add(Activity(kind="export", message=f"Yayına hazır ürünler dışa aktarıldı: {len(products)}"))
    db.commit()
    data = buf.getvalue().encode("utf-8")
    return StreamingResponse(
        io.BytesIO(data),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=yayina-hazir-urunler.csv"},
    )
