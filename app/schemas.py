from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models import ContentStatus, EventType, UserRole

SLUG_PATTERN = r'^[a-z0-9]+(?:-[a-z0-9]+)*$'


class StrictSchema(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class TokenResponse(StrictSchema):
    access_token: str
    token_type: str = 'bearer'
    expires_in: int
    role: UserRole


class LoginRequest(StrictSchema):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=8, max_length=120)


class UserRead(StrictSchema):
    id: str
    username: str
    role: UserRole
    is_active: bool


class CategoryCreate(StrictSchema):
    name: str = Field(min_length=2, max_length=120)
    slug: str = Field(min_length=2, max_length=120, pattern=SLUG_PATTERN)


class CategoryUpdate(StrictSchema):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    slug: str | None = Field(default=None, min_length=2, max_length=120, pattern=SLUG_PATTERN)


class CategoryRead(StrictSchema):
    id: int
    name: str
    slug: str


class CollectionCreate(StrictSchema):
    name: str = Field(min_length=2, max_length=120)
    slug: str = Field(min_length=2, max_length=120, pattern=SLUG_PATTERN)


class CollectionUpdate(StrictSchema):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    slug: str | None = Field(default=None, min_length=2, max_length=120, pattern=SLUG_PATTERN)


class CollectionRead(StrictSchema):
    id: int
    name: str
    slug: str


class ProductImageCreate(StrictSchema):
    url: str = Field(min_length=3, max_length=1024)
    alt_text: str | None = Field(default=None, max_length=200)
    sort_order: int = Field(default=0, ge=0)


class ProductImageUpdate(StrictSchema):
    url: str | None = Field(default=None, min_length=3, max_length=1024)
    alt_text: str | None = Field(default=None, max_length=200)
    sort_order: int | None = Field(default=None, ge=0)


class ProductImageRead(StrictSchema):
    id: int
    url: str
    public_url: str | None = None
    alt_text: str | None
    sort_order: int


class ProductCreate(StrictSchema):
    name: str = Field(min_length=2, max_length=180)
    slug: str = Field(min_length=2, max_length=180, pattern=SLUG_PATTERN)
    description: str | None = Field(default=None, max_length=4000)
    primary_image_path: str | None = Field(default=None, min_length=3, max_length=1024)
    status: ContentStatus = ContentStatus.draft
    sort_order: int = Field(default=0, ge=0)
    category_id: int | None = Field(default=None, ge=1)
    collection_id: int | None = Field(default=None, ge=1)


class ProductUpdate(StrictSchema):
    name: str | None = Field(default=None, min_length=2, max_length=180)
    slug: str | None = Field(default=None, min_length=2, max_length=180, pattern=SLUG_PATTERN)
    description: str | None = Field(default=None, max_length=4000)
    primary_image_path: str | None = Field(default=None, min_length=3, max_length=1024)
    status: ContentStatus | None = None
    sort_order: int | None = Field(default=None, ge=0)
    category_id: int | None = Field(default=None, ge=1)
    collection_id: int | None = Field(default=None, ge=1)


class ProductOrderUpdate(StrictSchema):
    sort_order: int = Field(ge=0)


class ProductRead(StrictSchema):
    id: str
    name: str
    slug: str
    description: str | None
    primary_image_path: str | None
    primary_image_url: str | None
    status: ContentStatus
    sort_order: int
    category_id: int | None
    collection_id: int | None
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime
    images: list[ProductImageRead] = Field(default_factory=list)


class NewsImageCreate(StrictSchema):
    url: str = Field(min_length=3, max_length=1024)
    alt_text: str | None = Field(default=None, max_length=200)
    sort_order: int = Field(default=0, ge=0)


class NewsImageUpdate(StrictSchema):
    url: str | None = Field(default=None, min_length=3, max_length=1024)
    alt_text: str | None = Field(default=None, max_length=200)
    sort_order: int | None = Field(default=None, ge=0)


class NewsImageRead(StrictSchema):
    id: int
    url: str
    public_url: str | None = None
    alt_text: str | None
    sort_order: int


class NewsCreate(StrictSchema):
    title: str = Field(min_length=2, max_length=220)
    banner_image_path: str | None = Field(default=None, min_length=3, max_length=1024)
    description: str | None = Field(default=None, max_length=8000)
    is_featured: bool = False


class NewsUpdate(StrictSchema):
    title: str | None = Field(default=None, min_length=2, max_length=220)
    banner_image_path: str | None = Field(default=None, min_length=3, max_length=1024)
    description: str | None = Field(default=None, max_length=8000)
    is_featured: bool | None = None


class NewsRead(StrictSchema):
    id: str
    title: str
    banner_image_path: str | None
    banner_image_url: str | None
    description: str | None
    is_featured: bool
    created_at: datetime
    updated_at: datetime
    images: list[NewsImageRead] = Field(default_factory=list)


class CatalogImageCreate(StrictSchema):
    url: str = Field(min_length=10, max_length=1024)
    alt_text: str | None = Field(default=None, max_length=200)
    sort_order: int = Field(default=0, ge=0)


class CatalogImageUpdate(StrictSchema):
    url: str | None = Field(default=None, min_length=10, max_length=1024)
    alt_text: str | None = Field(default=None, max_length=200)
    sort_order: int | None = Field(default=None, ge=0)


class CatalogImageRead(StrictSchema):
    id: int
    url: str
    alt_text: str | None
    sort_order: int


class CatalogCreate(StrictSchema):
    name: str = Field(min_length=2, max_length=180)
    slug: str = Field(min_length=2, max_length=180, pattern=SLUG_PATTERN)
    description: str | None = Field(default=None, max_length=4000)
    status: ContentStatus = ContentStatus.draft
    sort_order: int = Field(default=0, ge=0)


class CatalogUpdate(StrictSchema):
    name: str | None = Field(default=None, min_length=2, max_length=180)
    slug: str | None = Field(default=None, min_length=2, max_length=180, pattern=SLUG_PATTERN)
    description: str | None = Field(default=None, max_length=4000)
    status: ContentStatus | None = None
    sort_order: int | None = Field(default=None, ge=0)


class CatalogOrderUpdate(StrictSchema):
    sort_order: int = Field(ge=0)


class CatalogProductAttach(StrictSchema):
    product_id: str = Field(min_length=36, max_length=36)
    sort_order: int = Field(default=0, ge=0)


class CatalogProductReorder(StrictSchema):
    sort_order: int = Field(ge=0)


class CatalogProductRead(StrictSchema):
    product_id: str
    sort_order: int


class CatalogRead(StrictSchema):
    id: str
    name: str
    slug: str
    description: str | None
    status: ContentStatus
    sort_order: int
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime
    images: list[CatalogImageRead] = Field(default_factory=list)
    products: list[CatalogProductRead] = Field(default_factory=list)


class PaginationMeta(StrictSchema):
    page: int
    page_size: int
    total: int
    total_pages: int


class ProductListResponse(StrictSchema):
    items: list[ProductRead]
    meta: PaginationMeta


class CatalogListResponse(StrictSchema):
    items: list[CatalogRead]
    meta: PaginationMeta


class CategoryListResponse(StrictSchema):
    items: list[CategoryRead]
    meta: PaginationMeta


class CollectionListResponse(StrictSchema):
    items: list[CollectionRead]
    meta: PaginationMeta


class NewsListResponse(StrictSchema):
    items: list[NewsRead]
    meta: PaginationMeta


class CategoryProductTypeListResponse(StrictSchema):
    category_id: int
    items: list[CollectionRead]
    meta: PaginationMeta


class AnalyticsEventCreate(StrictSchema):
    event_type: EventType
    product_id: str | None = Field(default=None, min_length=36, max_length=36)
    catalog_id: str | None = Field(default=None, min_length=36, max_length=36)
    page: str = Field(min_length=1, max_length=255)
    source: str = Field(min_length=1, max_length=255)
    session_id: str = Field(min_length=8, max_length=120)
    occurred_at: datetime | None = None
    utm_source: str | None = Field(default=None, max_length=120)
    utm_medium: str | None = Field(default=None, max_length=120)
    utm_campaign: str | None = Field(default=None, max_length=120)
    referrer: str | None = Field(default=None, max_length=512)

    @model_validator(mode='after')
    def validate_target(self) -> 'AnalyticsEventCreate':
        if not self.product_id and not self.catalog_id:
            raise ValueError('Debe incluir product_id o catalog_id para atribucion')
        return self


class AnalyticsEventRead(StrictSchema):
    id: int
    event_type: EventType
    product_id: str | None
    catalog_id: str | None
    page: str
    source: str
    session_id: str
    occurred_at: datetime


class KpiSummary(StrictSchema):
    impressions: int
    clicks: int
    ctr: float


class ProductKpi(StrictSchema):
    product_id: str
    product_name: str
    impressions: int
    clicks: int
    ctr: float


class CatalogKpi(StrictSchema):
    catalog_id: str
    catalog_name: str
    impressions: int
    clicks: int
    ctr: float


class UTMReferrerKpi(StrictSchema):
    utm_source: str | None
    utm_campaign: str | None
    referrer: str | None
    impressions: int
    clicks: int
    ctr: float


class KpiReportResponse(StrictSchema):
    start_at: datetime
    end_at: datetime
    total: KpiSummary
    by_product: list[ProductKpi]
    by_catalog: list[CatalogKpi]


class TopProductsResponse(StrictSchema):
    start_at: datetime
    end_at: datetime
    items: list[ProductKpi]


class UTMReferrerResponse(StrictSchema):
    start_at: datetime
    end_at: datetime
    items: list[UTMReferrerKpi]


class AuditLogRead(StrictSchema):
    id: int
    actor_user_id: str | None
    actor_username: str | None
    entity_type: str
    entity_id: str
    action: str
    before_state: dict | None
    after_state: dict | None
    created_at: datetime


class AuditLogListResponse(StrictSchema):
    items: list[AuditLogRead]
    meta: PaginationMeta


class AssetUploadRequest(StrictSchema):
    file_name: str = Field(min_length=3, max_length=255)
    content_type: str = Field(min_length=3, max_length=120)
    entity_type: str = Field(min_length=3, max_length=40)
    product_id: str | None = Field(default=None, min_length=36, max_length=36)
    news_id: str | None = Field(default=None, min_length=36, max_length=36)

    @field_validator('entity_type')
    @classmethod
    def normalize_entity(cls, value: str) -> str:
        return value.lower()

    @model_validator(mode='after')
    def validate_product_link(self) -> 'AssetUploadRequest':
        if self.entity_type.startswith('product') and not self.product_id:
            raise ValueError('product_id es obligatorio para uploads de imagen de producto')
        if self.entity_type.startswith('news') and not self.news_id:
            raise ValueError('news_id es obligatorio para uploads de imagen de noticia')
        return self


class AssetUploadResponse(StrictSchema):
    provider: str
    object_key: str
    public_url: str | None
    upload_url: str | None
    expires_in: int | None
    note: str | None = None
