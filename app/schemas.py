from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models import ContentStatus, EventSource, EventType, RequestStatus, UserRole

SLUG_PATTERN = r'^[a-z0-9]+(?:-[a-z0-9]+)*$'
TRACKING_ID_PATTERN = r'^[A-Za-z0-9][A-Za-z0-9._:-]{7,119}$'
IDEMPOTENCY_KEY_PATTERN = r'^[A-Za-z0-9][A-Za-z0-9._:-]{7,119}$'
PAGE_PATH_PATTERN = r'^/[^\s]{0,254}$'


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
    price_cents: int | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    primary_image_path: str | None = Field(default=None, min_length=3, max_length=1024)
    status: ContentStatus = ContentStatus.draft
    sort_order: int = Field(default=0, ge=0)
    category_id: int | None = Field(default=None, ge=1)
    collection_id: int | None = Field(default=None, ge=1)

    @field_validator('currency')
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip().upper()


class ProductUpdate(StrictSchema):
    name: str | None = Field(default=None, min_length=2, max_length=180)
    slug: str | None = Field(default=None, min_length=2, max_length=180, pattern=SLUG_PATTERN)
    description: str | None = Field(default=None, max_length=4000)
    price_cents: int | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    primary_image_path: str | None = Field(default=None, min_length=3, max_length=1024)
    status: ContentStatus | None = None
    sort_order: int | None = Field(default=None, ge=0)
    category_id: int | None = Field(default=None, ge=1)
    collection_id: int | None = Field(default=None, ge=1)

    @field_validator('currency')
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip().upper()


class ProductOrderUpdate(StrictSchema):
    sort_order: int = Field(ge=0)


class ProductRead(StrictSchema):
    id: str
    name: str
    slug: str
    description: str | None
    price_cents: int | None
    currency: str | None
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


class PublicTaxonomyRead(StrictSchema):
    id: int
    name: str
    slug: str


class PublicTaxonomyListResponse(StrictSchema):
    version: str = 'v1'
    items: list[PublicTaxonomyRead]
    meta: PaginationMeta


class PublicProductImageRead(StrictSchema):
    id: int
    public_url: str | None
    alt_text: str | None
    sort_order: int


class PublicProductCategoryRef(StrictSchema):
    id: int
    name: str
    slug: str


class PublicProductCollectionRef(StrictSchema):
    id: int
    name: str
    slug: str


class PublicProductRead(StrictSchema):
    id: str
    name: str
    slug: str
    description: str | None
    status: str = 'active'
    price_cents: int | None = None
    currency: str | None = None
    visible_variants: list[str] = Field(default_factory=list)
    primary_image_url: str | None
    category: PublicProductCategoryRef | None
    collection: PublicProductCollectionRef | None
    images: list[PublicProductImageRead] = Field(default_factory=list)


class PublicProductListResponse(StrictSchema):
    version: str = 'v1'
    items: list[PublicProductRead]
    meta: PaginationMeta


class PublicCatalogResponse(StrictSchema):
    version: str = 'v1'
    drop_slug: str | None
    cat: str | None
    items: list[PublicProductRead]
    meta: PaginationMeta


class AnalyticsEventCreate(StrictSchema):
    event_type: EventType
    product_id: str | None = Field(default=None, min_length=36, max_length=36)
    catalog_id: str | None = Field(default=None, min_length=36, max_length=36)
    request_id: str | None = Field(default=None, min_length=36, max_length=36)
    page: str = Field(min_length=1, max_length=255, pattern=PAGE_PATH_PATTERN)
    source: EventSource
    session_id: str = Field(min_length=8, max_length=120, pattern=TRACKING_ID_PATTERN)
    visitor_id: str | None = Field(default=None, min_length=8, max_length=120, pattern=TRACKING_ID_PATTERN)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=120, pattern=IDEMPOTENCY_KEY_PATTERN)
    key_id: str | None = Field(default=None, min_length=2, max_length=80)
    occurred_at: datetime | None = None
    utm_source: str | None = Field(default=None, max_length=120)
    utm_medium: str | None = Field(default=None, max_length=120)
    utm_campaign: str | None = Field(default=None, max_length=120)
    referrer: str | None = Field(default=None, max_length=512)

    @field_validator('source', mode='before')
    @classmethod
    def normalize_source(cls, value: EventSource | str) -> EventSource | str:
        if isinstance(value, str):
            return value.strip().lower()
        return value

    @model_validator(mode='after')
    def validate_target(self) -> 'AnalyticsEventCreate':
        if self.event_type == EventType.request_submitted and not self.request_id:
            raise ValueError('request_submitted requiere request_id')
        if self.event_type in {EventType.impression, EventType.click, EventType.add_to_request}:
            if not self.product_id and not self.catalog_id:
                raise ValueError('Debe incluir product_id o catalog_id para atribucion')
        return self


class AnalyticsPublicEventCreate(StrictSchema):
    event_name: EventType
    source: EventSource
    visitor_id: str = Field(min_length=8, max_length=120, pattern=TRACKING_ID_PATTERN)
    session_id: str = Field(min_length=8, max_length=120, pattern=TRACKING_ID_PATTERN)
    page_path: str = Field(min_length=1, max_length=255, pattern=PAGE_PATH_PATTERN)
    idempotency_key: str = Field(min_length=8, max_length=120, pattern=IDEMPOTENCY_KEY_PATTERN)
    occurred_at: datetime | None = None
    product_id: str | None = Field(default=None, min_length=36, max_length=36)
    catalog_id: str | None = Field(default=None, min_length=36, max_length=36)
    request_id: str | None = Field(default=None, min_length=36, max_length=36)
    utm_source: str | None = Field(default=None, max_length=120)
    utm_medium: str | None = Field(default=None, max_length=120)
    utm_campaign: str | None = Field(default=None, max_length=120)
    referrer: str | None = Field(default=None, max_length=512)

    @field_validator('source', mode='before')
    @classmethod
    def normalize_source(cls, value: EventSource | str) -> EventSource | str:
        if isinstance(value, str):
            return value.strip().lower()
        return value

    @model_validator(mode='after')
    def validate_target(self) -> 'AnalyticsPublicEventCreate':
        if self.event_name == EventType.request_submitted and not self.request_id:
            raise ValueError('request_submitted requiere request_id')
        if self.event_name == EventType.add_to_request and not self.product_id:
            raise ValueError('add_to_request requiere product_id')
        if self.event_name in {EventType.impression, EventType.click} and not self.product_id and not self.catalog_id:
            raise ValueError('impression/click requiere product_id o catalog_id')
        return self


class AnalyticsEventRead(StrictSchema):
    id: int
    event_name: EventType
    event_type: EventType
    product_id: str | None
    catalog_id: str | None
    request_id: str | None
    idempotency_key: str | None
    key_id: str | None
    page: str
    page_path: str
    source: str
    session_id: str
    visitor_id: str | None
    occurred_at: datetime
    received_at: datetime


class AnalyticsIngestionMetricsRead(StrictSchema):
    total: int
    ingested: int
    duplicated: int
    rate_limited: int
    unauthorized: int


class ProductRequestItemCreate(StrictSchema):
    product_id: str = Field(min_length=36, max_length=36)
    qty: int = Field(default=1, ge=1, le=200)
    variant_size: str | None = Field(default=None, max_length=40)
    variant_color: str | None = Field(default=None, max_length=60)
    unit_price_cents: int | None = Field(default=None, ge=0)

    @field_validator('variant_size', 'variant_color')
    @classmethod
    def normalize_variants(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        return trimmed or None


class ProductRequestCreate(StrictSchema):
    idempotency_key: str = Field(min_length=8, max_length=120, pattern=IDEMPOTENCY_KEY_PATTERN)
    session_id: str = Field(min_length=8, max_length=120, pattern=TRACKING_ID_PATTERN)
    visitor_id: str | None = Field(default=None, min_length=8, max_length=120, pattern=TRACKING_ID_PATTERN)
    page_path: str = Field(min_length=1, max_length=255, pattern=PAGE_PATH_PATTERN)
    source: EventSource
    customer_name: str | None = Field(default=None, min_length=2, max_length=160)
    customer_email: str | None = Field(default=None, max_length=160)
    customer_phone: str | None = Field(default=None, max_length=60)
    notes: str | None = Field(default=None, max_length=4000)
    utm_source: str | None = Field(default=None, max_length=120)
    utm_medium: str | None = Field(default=None, max_length=120)
    utm_campaign: str | None = Field(default=None, max_length=120)
    referrer: str | None = Field(default=None, max_length=512)
    items: list[ProductRequestItemCreate] = Field(min_length=1, max_length=50)

    @field_validator('source', mode='before')
    @classmethod
    def normalize_source(cls, value: EventSource | str) -> EventSource | str:
        if isinstance(value, str):
            return value.strip().lower()
        return value


class ProductRequestItemRead(StrictSchema):
    product_id: str | None
    product_name: str
    qty: int
    variant_size: str | None
    variant_color: str | None
    unit_price_cents: int | None
    quantity: int


class ProductRequestRead(StrictSchema):
    id: str
    idempotency_key: str | None
    session_id: str
    visitor_id: str | None
    status: RequestStatus
    status_reason: str | None
    status_updated_by_user_id: str | None
    status_updated_at: datetime | None
    page: str | None
    page_path: str | None
    source: str | None
    customer_name: str | None
    customer_email: str | None
    customer_phone: str | None
    notes: str | None
    utm_source: str | None
    utm_medium: str | None
    utm_campaign: str | None
    referrer: str | None
    total_amount_cents: int | None
    created_at: datetime
    updated_at: datetime
    contacted_at: datetime | None
    paid_at: datetime | None
    delivered_at: datetime | None
    resolved_at: datetime | None
    items: list[ProductRequestItemRead] = Field(default_factory=list)


class ProductRequestListResponse(StrictSchema):
    items: list[ProductRequestRead]
    meta: PaginationMeta


class ProductRequestStatusUpdate(StrictSchema):
    status: RequestStatus
    notes: str | None = Field(default=None, max_length=4000)
    reason: str | None = Field(default=None, max_length=4000)

    @model_validator(mode='after')
    def validate_reason(self) -> 'ProductRequestStatusUpdate':
        if self.status in {RequestStatus.declined_customer, RequestStatus.declined_business} and not self.reason:
            raise ValueError('reason es obligatorio para estados declined_*')
        return self


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


class FunnelKpiResponse(StrictSchema):
    version: str = 'v1'
    start_at: datetime
    end_at: datetime
    cta_users: int
    request_submissions: int
    request_users: int
    fulfilled_requests: int
    fulfilled_users: int
    declined_requests: int
    cta_to_request_rate: float
    request_to_fulfilled_rate: float
    cta_to_fulfilled_rate: float


class TopRequestedProductKpi(StrictSchema):
    product_id: str | None
    product_name: str
    request_count: int
    requested_quantity: int
    fulfilled_quantity: int
    fulfillment_rate: float


class TopRequestedProductsResponse(StrictSchema):
    version: str = 'v1'
    start_at: datetime
    end_at: datetime
    items: list[TopRequestedProductKpi]


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
