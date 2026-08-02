"""Workflow status transitions, suggestion lifecycle, and approval.

Single source of truth so quality/suggestion/approval logic stays consistent
across HTTP endpoints and bulk operations.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Iterable, Optional

from sqlalchemy.orm import Session

import ai_service
import quality_service
import revision_service
from models import (
    Activity, Product, ProductIssue, ProductRevision, ProductSuggestion,
)


# ---------------- Status ----------------
STATUS_LABELS = {
    "imported": "İçe Aktarıldı",
    "needs_attention": "Dikkat Gerekiyor",
    "ready_for_ai": "AI İçin Hazır",
    "awaiting_review": "İnceleme Bekliyor",
    "approved": "Onaylandı",
    "ready_to_publish": "Yayına Hazır",
    "sent_as_draft": "Mağazaya Taslak Gönderildi",
}


def _log(db: Session, kind: str, message: str) -> None:
    db.add(Activity(kind=kind, message=message))


def _active_suggestion(db: Session, product: Product) -> Optional[ProductSuggestion]:
    if not product.active_suggestion_id:
        return None
    return db.get(ProductSuggestion, product.active_suggestion_id)


def _unresolved_issues(db: Session, product_id: str) -> list[ProductIssue]:
    return db.query(ProductIssue).filter(
        ProductIssue.product_id == product_id, ProductIssue.is_resolved.is_(False)
    ).all()


def effective_candidate(
    product: Product,
    suggestion: Optional[ProductSuggestion],
) -> dict:
    """Return the effective publish candidate.

    Approved-suggestion fields override original ONLY for:
        name, description, category, seo_title, meta_description, tags.
    Original always supplies: sku, price, stock, image_url, product_url.
    """
    use = suggestion is not None
    return {
        "sku": product.sku,
        "name": (suggestion.suggested_name if use and suggestion.suggested_name else product.name),
        "description": (suggestion.suggested_description if use and suggestion.suggested_description else product.description),
        "category": (suggestion.suggested_category if use and suggestion.suggested_category else product.category),
        "price": product.price,
        "stock": product.stock,
        "image_url": product.image_url,
        "product_url": product.product_url,
        "seo_title": suggestion.suggested_seo_title if use else None,
        "meta_description": suggestion.suggested_meta_description if use else None,
    }


def passes_publish_validation(
    product: Product,
    suggestion: Optional[ProductSuggestion],
    issues: Iterable[ProductIssue] = (),
) -> tuple[bool, list[str]]:
    """Validate the effective publish candidate (Phase 2.1).

    Original-only fields (sku, price, stock) remain blocking. An approved
    suggestion may resolve missing name / description / category coming
    from the original import.
    """
    reasons: list[str] = []
    if suggestion is None or suggestion.suggestion_status != "approved":
        reasons.append("Onaylı bir öneri bulunmuyor")
        # Still validate original blockers so caller sees the full picture.
    candidate = effective_candidate(product, suggestion)
    if not (candidate["sku"] or "").strip():
        reasons.append("SKU eksik")
    if not (candidate["name"] or "").strip():
        reasons.append("Ürün adı eksik")
    if not (candidate["description"] or "").strip():
        reasons.append("Açıklama eksik")
    if not (candidate["category"] or "").strip():
        reasons.append("Kategori eksik")
    if candidate["price"] is None:
        reasons.append("Fiyat eksik")
    elif candidate["price"] <= 0:
        reasons.append("Fiyat geçersiz")
    if candidate["stock"] is None or candidate["stock"] < 0:
        reasons.append("Stok geçersiz")
    return (len(reasons) == 0, reasons)


def would_publish_if_approved(
    product: Product,
    draft_suggestion: Optional[ProductSuggestion],
) -> tuple[bool, list[str]]:
    """Pre-check: assume this draft were approved, would it pass validation?"""
    reasons: list[str] = []
    candidate = effective_candidate(product, draft_suggestion)
    if not (candidate["sku"] or "").strip():
        reasons.append("SKU eksik")
    if not (candidate["name"] or "").strip():
        reasons.append("Ürün adı eksik")
    if not (candidate["description"] or "").strip():
        reasons.append("Açıklama eksik")
    if not (candidate["category"] or "").strip():
        reasons.append("Kategori eksik")
    if candidate["price"] is None:
        reasons.append("Fiyat eksik")
    elif candidate["price"] <= 0:
        reasons.append("Fiyat geçersiz")
    if candidate["stock"] is None or candidate["stock"] < 0:
        reasons.append("Stok geçersiz")
    return (len(reasons) == 0, reasons)


def compute_workflow_status(
    product: Product,
    issues: Iterable[ProductIssue],
    active_suggestion: Optional[ProductSuggestion],
) -> str:
    issues = list(issues)
    # A product that has already been sent to WooCommerce as a draft must not
    # be silently downgraded by unrelated reads. Preserve sent_as_draft when
    # the approved suggestion still passes publish validation.
    if product.workflow_status == "sent_as_draft" and active_suggestion \
            and active_suggestion.suggestion_status == "approved":
        ok, _ = passes_publish_validation(product, active_suggestion, issues)
        if ok:
            return "sent_as_draft"
    if active_suggestion and active_suggestion.suggestion_status == "approved":
        ok, _ = passes_publish_validation(product, active_suggestion, issues)
        return "ready_to_publish" if ok else "approved"
    if active_suggestion and active_suggestion.suggestion_status == "draft":
        return "awaiting_review"
    critical = sum(1 for i in issues if i.severity == "critical")
    score = product.quality_score or 0
    if critical > 0 or score < 60:
        return "needs_attention"
    return "ready_for_ai"


def refresh_workflow(db: Session, product: Product) -> None:
    """Recompute and persist workflow_status. Assumes issues are up to date."""
    issues = _unresolved_issues(db, product.id)
    suggestion = _active_suggestion(db, product)
    product.workflow_status = compute_workflow_status(product, issues, suggestion)


# ---------------- Analyze ----------------
def analyze_and_transition(db: Session, product: Product) -> dict:
    result = quality_service.analyze_product(db, product)
    refresh_workflow(db, product)
    return result


def analyze_bulk(db: Session, product_ids: list[str]) -> dict:
    products = db.query(Product).filter(Product.id.in_(product_ids)).all() if product_ids else []
    processed = 0
    for p in products:
        analyze_and_transition(db, p)
        processed += 1
    _log(db, "bulk", f"Toplu kalite analizi: {processed} ürün")
    return {"processed": processed, "total_requested": len(product_ids)}


# ---------------- Suggestion ----------------
async def create_suggestion(db: Session, product: Product) -> ProductSuggestion:
    issues = _unresolved_issues(db, product.id)
    payload = await ai_service.generate_suggestion(
        name=product.name,
        description=product.description,
        category=product.category,
        image_url=product.image_url,
        product_url=product.product_url,
        price=product.price,
        issue_codes=[i.issue_code for i in issues],
    )

    # Mark any prior draft suggestion as rejected (only one active at a time).
    if product.active_suggestion_id:
        prev = db.get(ProductSuggestion, product.active_suggestion_id)
        if prev and prev.suggestion_status == "draft":
            prev.suggestion_status = "rejected"

    suggestion = ProductSuggestion(
        product_id=product.id,
        suggested_name=payload.get("suggested_name"),
        suggested_description=payload.get("suggested_description"),
        suggested_category=payload.get("suggested_category"),
        suggested_seo_title=payload.get("suggested_seo_title"),
        suggested_meta_description=payload.get("suggested_meta_description"),
        suggested_tags=json.dumps(payload.get("suggested_tags") or [], ensure_ascii=False),
        provider=payload.get("provider", "demo"),
        model=payload.get("model"),
        suggestion_status="draft",
    )
    db.add(suggestion)
    db.flush()

    product.active_suggestion_id = suggestion.id
    refresh_workflow(db, product)

    revision_service.create_revision(
        db,
        product_id=product.id,
        action_type="suggest",
        source="ai",
        before=None,
        after=revision_service.snapshot_suggestion(suggestion),
    )
    _log(db, "edit", f"AI önerisi oluşturuldu ({suggestion.provider}): {product.sku}")
    return suggestion


def update_suggestion(
    db: Session,
    product: Product,
    updates: dict,
) -> ProductSuggestion:
    suggestion = _active_suggestion(db, product)
    if suggestion is None or suggestion.suggestion_status != "draft":
        raise ValueError("Düzenlenebilir bir öneri bulunmuyor")
    before = revision_service.snapshot_suggestion(suggestion)
    for k, v in updates.items():
        if k == "suggested_tags" and isinstance(v, list):
            suggestion.suggested_tags = json.dumps(v, ensure_ascii=False)
        elif hasattr(suggestion, k):
            setattr(suggestion, k, v)
    db.flush()
    revision_service.create_revision(
        db,
        product_id=product.id,
        action_type="edit",
        source="user",
        before=before,
        after=revision_service.snapshot_suggestion(suggestion),
    )
    return suggestion


def approve_suggestion(db: Session, product: Product) -> tuple[ProductSuggestion, dict]:
    suggestion = _active_suggestion(db, product)
    if suggestion is None:
        raise ValueError("Onaylanacak öneri bulunmuyor")
    if suggestion.suggestion_status == "rejected":
        raise ValueError("Reddedilmiş öneri onaylanamaz")
    before = revision_service.snapshot_suggestion(suggestion)
    suggestion.suggestion_status = "approved"
    suggestion.approved_at = datetime.now(timezone.utc)
    db.flush()

    issues = _unresolved_issues(db, product.id)
    ok, reasons = passes_publish_validation(product, suggestion, issues)
    product.workflow_status = "ready_to_publish" if ok else "approved"

    revision_service.create_revision(
        db,
        product_id=product.id,
        action_type="approve",
        source="approval",
        before=before,
        after=revision_service.snapshot_suggestion(suggestion),
    )
    _log(db, "edit", f"Öneri onaylandı: {product.sku}"
         + ("" if ok else f" (yayına hazır değil: {', '.join(reasons)})"))
    return suggestion, {"ready_to_publish": ok, "blocking_reasons": reasons}


def reject_suggestion(db: Session, product: Product) -> ProductSuggestion:
    suggestion = _active_suggestion(db, product)
    if suggestion is None:
        raise ValueError("Reddedilecek öneri bulunmuyor")
    if suggestion.suggestion_status == "approved":
        raise ValueError("Onaylanmış öneri reddedilemez; önce revizyona dönün")
    before = revision_service.snapshot_suggestion(suggestion)
    suggestion.suggestion_status = "rejected"
    product.active_suggestion_id = None
    db.flush()
    refresh_workflow(db, product)
    revision_service.create_revision(
        db,
        product_id=product.id,
        action_type="reject",
        source="user",
        before=before,
        after=revision_service.snapshot_suggestion(suggestion),
    )
    _log(db, "edit", f"Öneri reddedildi: {product.sku}")
    return suggestion


def revert_to_revision(db: Session, product: Product, revision_id: str) -> ProductRevision:
    rev = db.get(ProductRevision, revision_id)
    if rev is None or rev.product_id != product.id:
        raise ValueError("Revizyon bulunamadı")
    snapshot = revision_service.loads(rev.after_snapshot) or revision_service.loads(rev.before_snapshot)
    if not snapshot:
        raise ValueError("Bu revizyon geri yüklenemez (anlık görüntü yok)")

    # We ONLY restore suggestion snapshots. Original product source data is
    # never altered by revert (approve/reject/suggest revisions carry suggestion
    # snapshots; analyze revisions do not carry restorable content).
    is_suggestion = "suggested_name" in snapshot or "suggestion_status" in snapshot
    if not is_suggestion:
        raise ValueError("Bu revizyon türü geri yüklenemez")

    # Reject any current draft, then create a fresh draft from the snapshot.
    if product.active_suggestion_id:
        current = db.get(ProductSuggestion, product.active_suggestion_id)
        if current and current.suggestion_status == "draft":
            current.suggestion_status = "rejected"

    restored = ProductSuggestion(
        product_id=product.id,
        suggested_name=snapshot.get("suggested_name"),
        suggested_description=snapshot.get("suggested_description"),
        suggested_category=snapshot.get("suggested_category"),
        suggested_seo_title=snapshot.get("suggested_seo_title"),
        suggested_meta_description=snapshot.get("suggested_meta_description"),
        suggested_tags=snapshot.get("suggested_tags") if isinstance(snapshot.get("suggested_tags"), str)
                       else json.dumps(snapshot.get("suggested_tags") or [], ensure_ascii=False),
        provider=snapshot.get("provider") or "revert",
        model=snapshot.get("model"),
        suggestion_status="draft",
    )
    db.add(restored)
    db.flush()
    product.active_suggestion_id = restored.id
    refresh_workflow(db, product)

    revision_service.create_revision(
        db,
        product_id=product.id,
        action_type="revert",
        source="revert",
        before=None,
        after=revision_service.snapshot_suggestion(restored),
    )
    _log(db, "edit", f"Öneri revizyondan geri yüklendi: {product.sku}")
    return db.query(ProductRevision).order_by(ProductRevision.created_at.desc()).filter(
        ProductRevision.product_id == product.id
    ).first()
