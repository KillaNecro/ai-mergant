"""Pydantic schemas for the WooCommerce integration API."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class WooCommerceStatusResponse(BaseModel):
    configured: bool
    connected: bool
    mode: str
    store_url: Optional[str] = None
    last_checked_at: Optional[datetime] = None
    error: Optional[str] = None
    message: str


class WooCommerceTestResponse(BaseModel):
    connected: bool
    configured: bool
    mode: str
    store_url: Optional[str] = None
    checked_at: datetime
    message: str


class WooCommerceCategoryResponse(BaseModel):
    id: int
    name: str
    slug: str
    parent: int


class WooCommerceCategoryListResponse(BaseModel):
    mode: str
    count: int
    categories: List[WooCommerceCategoryResponse]


# --------------------------------------------------------------------------- #
# Category mappings
# --------------------------------------------------------------------------- #

_MAX_NAME_LEN = 200


class CategoryMappingCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    local_category: str = Field(min_length=1, max_length=_MAX_NAME_LEN)
    external_category_id: int = Field(gt=0)
    external_category_name: str = Field(min_length=1, max_length=_MAX_NAME_LEN)

    @field_validator("local_category", "external_category_name", mode="before")
    @classmethod
    def _strip(cls, v):
        if v is None:
            return v
        if not isinstance(v, str):
            return v
        return v.strip()

    @field_validator("local_category", "external_category_name")
    @classmethod
    def _require_nonempty(cls, v):
        if not v or not v.strip():
            raise ValueError("Değer boş olamaz")
        return v


class CategoryMappingResponse(BaseModel):
    id: str
    channel: str
    local_category: str
    external_category_id: int
    external_category_name: str
    created_at: datetime
    updated_at: datetime


class CategoryMappingListResponse(BaseModel):
    count: int
    mappings: List[CategoryMappingResponse]


class CategoryMappingMutationResponse(BaseModel):
    created: bool
    updated: bool
    mapping: CategoryMappingResponse
    message: str


class CategoryMappingDeleteResponse(BaseModel):
    deleted: bool
    id: str
    message: str


# --------------------------------------------------------------------------- #
# Publishing
# --------------------------------------------------------------------------- #

class PublishResponse(BaseModel):
    success: bool
    mode: str
    action: str  # draft_created | draft_updated
    product_id: str
    external_product_id: Optional[str] = None
    external_url: Optional[str] = None
    publication_status: str
    workflow_status: str
    attempt_count: int
    message: str


class PublicationStatusResponse(BaseModel):
    product_id: str
    channel: str
    external_product_id: Optional[str] = None
    external_url: Optional[str] = None
    publication_status: str
    attempt_count: int
    last_error: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    last_success_at: Optional[datetime] = None
