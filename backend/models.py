"""SQLAlchemy models for AI Merchant OS Lite."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, Column, DateTime, Float, Index, Integer, String, Text,
    UniqueConstraint,
)

from database import Base


def _uuid():
    return str(uuid.uuid4())


def _now():
    return datetime.now(timezone.utc)


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("sku", name="uq_products_sku"),
        Index("ix_products_category", "category"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    sku = Column(String, nullable=False)
    name = Column(String, nullable=False)
    improved_name = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    improved_description = Column(Text, nullable=True)
    category = Column(String, nullable=True)
    price = Column(Float, nullable=True)
    stock = Column(Integer, nullable=True, default=0)
    image_url = Column(String, nullable=True)
    product_url = Column(String, nullable=True)
    is_edited = Column(Boolean, default=False, nullable=False)
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
