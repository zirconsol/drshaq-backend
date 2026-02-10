from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum as SqlEnum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UserRole(str, Enum):
    admin = 'admin'
    editor = 'editor'


class ContentStatus(str, Enum):
    draft = 'draft'
    published = 'published'
    archived = 'archived'


class EventType(str, Enum):
    impression = 'impression'
    click = 'click'
    cta_click = 'cta_click'
    add_to_request = 'add_to_request'
    request_submitted = 'request_submitted'


class RequestStatus(str, Enum):
    submitted = 'submitted'
    contacted = 'contacted'
    fulfilled = 'fulfilled'
    declined_customer = 'declined_customer'
    declined_business = 'declined_business'


class User(Base):
    __tablename__ = 'users'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(SqlEnum(UserRole), default=UserRole.editor)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    audit_logs: Mapped[list[AuditLog]] = relationship(back_populates='actor')


class Category(Base):
    __tablename__ = 'categories'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    products: Mapped[list[Product]] = relationship(back_populates='category')
    collection_links: Mapped[list[CategoryCollection]] = relationship(
        back_populates='category',
        cascade='all, delete-orphan',
    )


class Collection(Base):
    __tablename__ = 'collections'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    products: Mapped[list[Product]] = relationship(back_populates='collection')
    category_links: Mapped[list[CategoryCollection]] = relationship(
        back_populates='collection',
        cascade='all, delete-orphan',
    )


class CategoryCollection(Base):
    __tablename__ = 'category_collections'
    __table_args__ = (UniqueConstraint('category_id', 'collection_id', name='uq_category_collection'),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    category_id: Mapped[int] = mapped_column(ForeignKey('categories.id', ondelete='CASCADE'), index=True)
    collection_id: Mapped[int] = mapped_column(ForeignKey('collections.id', ondelete='CASCADE'), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    category: Mapped[Category] = relationship(back_populates='collection_links')
    collection: Mapped[Collection] = relationship(back_populates='category_links')


class Product(Base):
    __tablename__ = 'products'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(180), index=True)
    slug: Mapped[str] = mapped_column(String(180), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    primary_image_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    status: Mapped[ContentStatus] = mapped_column(SqlEnum(ContentStatus), default=ContentStatus.draft, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, index=True)
    category_id: Mapped[int | None] = mapped_column(ForeignKey('categories.id', ondelete='SET NULL'), nullable=True)
    collection_id: Mapped[int | None] = mapped_column(
        ForeignKey('collections.id', ondelete='SET NULL'), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    category: Mapped[Category | None] = relationship(back_populates='products')
    collection: Mapped[Collection | None] = relationship(back_populates='products')
    images: Mapped[list[ProductImage]] = relationship(back_populates='product', cascade='all, delete-orphan')
    catalog_links: Mapped[list[CatalogProduct]] = relationship(back_populates='product', cascade='all, delete-orphan')
    events: Mapped[list[AnalyticsEvent]] = relationship(back_populates='product')
    request_items: Mapped[list[ProductRequestItem]] = relationship(back_populates='product')


class ProductImage(Base):
    __tablename__ = 'product_images'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[str] = mapped_column(ForeignKey('products.id', ondelete='CASCADE'), index=True)
    url: Mapped[str] = mapped_column(String(1024))
    alt_text: Mapped[str | None] = mapped_column(String(200), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    product: Mapped[Product] = relationship(back_populates='images')


class News(Base):
    __tablename__ = 'news'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    title: Mapped[str] = mapped_column(String(220), index=True)
    banner_image_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_featured: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    images: Mapped[list[NewsImage]] = relationship(back_populates='news', cascade='all, delete-orphan')


class NewsImage(Base):
    __tablename__ = 'news_images'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    news_id: Mapped[str] = mapped_column(ForeignKey('news.id', ondelete='CASCADE'), index=True)
    url: Mapped[str] = mapped_column(String(1024))
    alt_text: Mapped[str | None] = mapped_column(String(200), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    news: Mapped[News] = relationship(back_populates='images')


class Catalog(Base):
    __tablename__ = 'catalogs'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(180), index=True)
    slug: Mapped[str] = mapped_column(String(180), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[ContentStatus] = mapped_column(SqlEnum(ContentStatus), default=ContentStatus.draft, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    images: Mapped[list[CatalogImage]] = relationship(back_populates='catalog', cascade='all, delete-orphan')
    product_links: Mapped[list[CatalogProduct]] = relationship(back_populates='catalog', cascade='all, delete-orphan')
    events: Mapped[list[AnalyticsEvent]] = relationship(back_populates='catalog')


class CatalogImage(Base):
    __tablename__ = 'catalog_images'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    catalog_id: Mapped[str] = mapped_column(ForeignKey('catalogs.id', ondelete='CASCADE'), index=True)
    url: Mapped[str] = mapped_column(String(1024))
    alt_text: Mapped[str | None] = mapped_column(String(200), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    catalog: Mapped[Catalog] = relationship(back_populates='images')


class CatalogProduct(Base):
    __tablename__ = 'catalog_products'
    __table_args__ = (UniqueConstraint('catalog_id', 'product_id', name='uq_catalog_product'),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    catalog_id: Mapped[str] = mapped_column(ForeignKey('catalogs.id', ondelete='CASCADE'), index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey('products.id', ondelete='CASCADE'), index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    catalog: Mapped[Catalog] = relationship(back_populates='product_links')
    product: Mapped[Product] = relationship(back_populates='catalog_links')


class ProductRequest(Base):
    __tablename__ = 'product_requests'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    session_id: Mapped[str] = mapped_column(String(120), index=True)
    visitor_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    status: Mapped[RequestStatus] = mapped_column(SqlEnum(RequestStatus), default=RequestStatus.submitted, index=True)
    page: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    source: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    customer_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    customer_email: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    customer_phone: Mapped[str | None] = mapped_column(String(60), nullable=True, index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    utm_source: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    utm_medium: Mapped[str | None] = mapped_column(String(120), nullable=True)
    utm_campaign: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    referrer: Mapped[str | None] = mapped_column(String(512), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    contacted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

    items: Mapped[list[ProductRequestItem]] = relationship(back_populates='request', cascade='all, delete-orphan')
    events: Mapped[list[AnalyticsEvent]] = relationship(back_populates='request')


class ProductRequestItem(Base):
    __tablename__ = 'product_request_items'
    __table_args__ = (UniqueConstraint('request_id', 'product_id', name='uq_request_product'),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(ForeignKey('product_requests.id', ondelete='CASCADE'), index=True)
    product_id: Mapped[str | None] = mapped_column(ForeignKey('products.id', ondelete='SET NULL'), nullable=True, index=True)
    product_name: Mapped[str] = mapped_column(String(180))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    request: Mapped[ProductRequest] = relationship(back_populates='items')
    product: Mapped[Product | None] = relationship(back_populates='request_items')


class AnalyticsEvent(Base):
    __tablename__ = 'analytics_events'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[EventType] = mapped_column(SqlEnum(EventType), index=True)
    product_id: Mapped[str | None] = mapped_column(ForeignKey('products.id', ondelete='SET NULL'), nullable=True, index=True)
    catalog_id: Mapped[str | None] = mapped_column(ForeignKey('catalogs.id', ondelete='SET NULL'), nullable=True, index=True)
    page: Mapped[str] = mapped_column(String(255), index=True)
    source: Mapped[str] = mapped_column(String(255), index=True)
    session_id: Mapped[str] = mapped_column(String(120), index=True)
    visitor_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    request_id: Mapped[str | None] = mapped_column(
        ForeignKey('product_requests.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )
    utm_source: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    utm_medium: Mapped[str | None] = mapped_column(String(120), nullable=True)
    utm_campaign: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    referrer: Mapped[str | None] = mapped_column(String(512), nullable=True, index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    product: Mapped[Product | None] = relationship(back_populates='events')
    catalog: Mapped[Catalog | None] = relationship(back_populates='events')
    request: Mapped[ProductRequest | None] = relationship(back_populates='events')


class AuditLog(Base):
    __tablename__ = 'audit_logs'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_user_id: Mapped[str | None] = mapped_column(ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True)
    actor_username: Mapped[str | None] = mapped_column(String(50), nullable=True)
    entity_type: Mapped[str] = mapped_column(String(80), index=True)
    entity_id: Mapped[str] = mapped_column(String(80), index=True)
    action: Mapped[str] = mapped_column(String(80), index=True)
    before_state: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after_state: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    actor: Mapped[User | None] = relationship(back_populates='audit_logs')
