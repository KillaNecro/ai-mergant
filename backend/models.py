"""SQLAlchemy models for AI Merchant OS Lite."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, String,
    Text, UniqueConstraint,
)

from database import Base


def _uuid():
    return str(uuid.uuid4())


def _now():
    return datetime.now(timezone.utc)


# ---------------- Products ----------------
class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("sku", name="uq_products_sku"),
        Index("ix_products_category", "category"),
        Index("ix_products_workflow_status", "workflow_status"),
        Index("ix_products_quality_score", "quality_score"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    sku = Column(String, nullable=False)
    name = Column(String, nullable=False)
    improved_name = Column(String, nullable=True)  # legacy Phase 1
    description = Column(Text, nullable=True)
    improved_description = Column(Text, nullable=True)  # legacy Phase 1
    category = Column(String, nullable=True)
    price = Column(Float, nullable=True)
    stock = Column(Integer, nullable=True, default=0)
    image_url = Column(String, nullable=True)
    product_url = Column(String, nullable=True)
    is_edited = Column(Boolean, default=False, nullable=False)
    # Phase 2 additions
    workflow_status = Column(String, nullable=False, default="imported")
    quality_score = Column(Integer, nullable=True)
    quality_analyzed_at = Column(DateTime, nullable=True)
    active_suggestion_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=_now, nullable=False)
    updated_at = Column(DateTime, default=_now, onupdate=_now, nullable=False)


class Activity(Base):
    __tablename__ = "activities"
    id = Column(String, primary_key=True, default=_uuid)
    kind = Column(String, nullable=False)
    message = Column(String, nullable=False)
    created_at = Column(DateTime, default=_now, nullable=False)


class Meta(Base):
    __tablename__ = "meta"
    key = Column(String, primary_key=True)
    value = Column(String, nullable=True)


# ---------------- Phase 2 tables ----------------
class ProductIssue(Base):
    __tablename__ = "product_issues"
    __table_args__ = (
        Index("ix_issues_product_id", "product_id"),
        Index("ix_issues_severity", "severity"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    product_id = Column(String, ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    issue_code = Column(String, nullable=False)
    field_name = Column(String, nullable=True)
    severity = Column(String, nullable=False)  # info | warning | critical
    message = Column(String, nullable=False)
    recommendation = Column(String, nullable=True)
    is_resolved = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=_now, nullable=False)
    resolved_at = Column(DateTime, nullable=True)


class ProductSuggestion(Base):
    __tablename__ = "product_suggestions"
    __table_args__ = (Index("ix_suggestions_product_id", "product_id"),)

    id = Column(String, primary_key=True, default=_uuid)
    product_id = Column(String, ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    suggested_name = Column(String, nullable=True)
    suggested_description = Column(Text, nullable=True)
    suggested_category = Column(String, nullable=True)
    suggested_seo_title = Column(String, nullable=True)
    suggested_meta_description = Column(String, nullable=True)
    suggested_tags = Column(Text, nullable=True)  # JSON-serialized list
    provider = Column(String, nullable=False)  # demo | gemini
    model = Column(String, nullable=True)
    suggestion_status = Column(String, nullable=False, default="draft")  # draft | approved | rejected
    created_at = Column(DateTime, default=_now, nullable=False)
    updated_at = Column(DateTime, default=_now, onupdate=_now, nullable=False)
    approved_at = Column(DateTime, nullable=True)


class ProductRevision(Base):
    __tablename__ = "product_revisions"
    __table_args__ = (
        Index("ix_revisions_product_id", "product_id"),
        Index("ix_revisions_created_at", "created_at"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    product_id = Column(String, ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    action_type = Column(String, nullable=False)  # analyze | suggest | edit | approve | reject | revert
    source = Column(String, nullable=False)  # import | quality_engine | ai | user | approval | revert
    before_snapshot = Column(Text, nullable=True)  # JSON string
    after_snapshot = Column(Text, nullable=True)   # JSON string
    created_at = Column(DateTime, default=_now, nullable=False)


# ---------------- Phase 3A: WooCommerce integration ----------------
class ProductPublication(Base):
    """Tracks the publication status of a product on an external channel.

    In Phase 3A Part A this table is created but never written to; Part B
    will add draft-publishing logic that reads/writes this row.

    publication_status values (application-managed enum, kept as string):
        pending | draft_created | draft_updated | failed
    """
    __tablename__ = "product_publications"
    __table_args__ = (
        UniqueConstraint("product_id", "channel", name="uq_product_publications_product_channel"),
        Index("ix_product_publications_product_id", "product_id"),
        Index("ix_product_publications_channel", "channel"),
        Index("ix_product_publications_status", "publication_status"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    product_id = Column(String, ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    channel = Column(String, nullable=False, default="woocommerce")
    external_product_id = Column(String, nullable=True)
    external_url = Column(String, nullable=True)
    publication_status = Column(String, nullable=False, default="pending")
    payload_snapshot = Column(Text, nullable=True)   # JSON-serialized sanitized request payload
    response_snapshot = Column(Text, nullable=True)  # JSON-serialized sanitized remote response
    last_error = Column(Text, nullable=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=_now, nullable=False)
    updated_at = Column(DateTime, default=_now, onupdate=_now, nullable=False)
    last_success_at = Column(DateTime, nullable=True)


class CategoryMapping(Base):
    """Maps a local catalog category name to an external channel category."""
    __tablename__ = "category_mappings"
    __table_args__ = (
        UniqueConstraint("channel", "local_category", name="uq_category_mappings_channel_local_category"),
        Index("ix_category_mappings_channel", "channel"),
        Index("ix_category_mappings_local_category", "local_category"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    channel = Column(String, nullable=False, default="woocommerce")
    local_category = Column(String, nullable=False)
    external_category_id = Column(Integer, nullable=False)
    external_category_name = Column(String, nullable=False)
    created_at = Column(DateTime, default=_now, nullable=False)
    updated_at = Column(DateTime, default=_now, onupdate=_now, nullable=False)
