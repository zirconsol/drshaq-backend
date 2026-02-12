import hashlib
import json
from datetime import datetime, timezone
from email.utils import format_datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.client_ip import build_trusted_proxy_networks, extract_client_ip
from app.config import get_settings
from app.database import get_db
from app.models import Category, Collection, ContentStatus, Product
from app.pagination import paginate_select
from app.rate_limit import InMemoryRateLimiter
from app.schemas import (
    PaginationMeta,
    PublicCatalogResponse,
    PublicProductCategoryRef,
    PublicProductCollectionRef,
    PublicProductImageRead,
    PublicProductListResponse,
    PublicProductRead,
    PublicTaxonomyListResponse,
    PublicTaxonomyRead,
)
from app.storage_utils import build_public_asset_url

router = APIRouter(prefix='/public', tags=['public'])
settings = get_settings()
rate_limiter = InMemoryRateLimiter()
trusted_proxy_networks = build_trusted_proxy_networks(settings.trusted_proxy_cidrs)
CACHE_CONTROL_VALUE = 'public, s-maxage=60, stale-while-revalidate=300'


def _parse_read_keys() -> dict[str, str]:
    keys: dict[str, str] = {}
    if settings.public_read_key:
        keys['legacy'] = settings.public_read_key
    for idx, item in enumerate(settings.public_read_keys, start=1):
        raw = item.strip()
        if not raw:
            continue
        if ':' in raw:
            key_id, key_val = raw.split(':', 1)
        else:
            key_id, key_val = f'key-{idx}', raw
        key_id = key_id.strip()
        key_val = key_val.strip()
        if key_id and key_val:
            keys[key_id] = key_val
    return keys


def _resolve_read_key_id(x_public_read_key: str | None) -> str | None:
    valid_keys = _parse_read_keys()
    if not valid_keys:
        if settings.public_read_require_key:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Clave de lectura publica requerida')
        return None
    if not x_public_read_key:
        if settings.public_read_require_key:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Clave de lectura publica requerida')
        return None
    for key_id, key_value in valid_keys.items():
        if x_public_read_key == key_value:
            return key_id
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Clave de lectura publica invalida')


def _enforce_public_rate_limit(request: Request, endpoint_key: str) -> None:
    client_ip = extract_client_ip(
        request,
        trusted_proxy_networks=trusted_proxy_networks,
        trust_proxy_headers=settings.trust_proxy_headers,
    )
    key = f'{client_ip}:{endpoint_key}'
    allowed, retry_after = rate_limiter.allow(
        key,
        max_requests=settings.public_read_rate_limit_requests,
        window_seconds=settings.public_read_rate_limit_window_seconds,
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail='Rate limit excedido para lectura publica',
            headers={'Retry-After': str(retry_after)},
        )


def _product_to_public(item: Product) -> PublicProductRead:
    category = (
        PublicProductCategoryRef(id=item.category.id, name=item.category.name, slug=item.category.slug)
        if item.category
        else None
    )
    collection = (
        PublicProductCollectionRef(id=item.collection.id, name=item.collection.name, slug=item.collection.slug)
        if item.collection
        else None
    )
    images = [
        PublicProductImageRead(
            id=img.id,
            public_url=build_public_asset_url(img.url),
            alt_text=img.alt_text,
            sort_order=img.sort_order,
        )
        for img in sorted(item.images, key=lambda value: value.sort_order)
    ]
    return PublicProductRead(
        id=item.id,
        name=item.name,
        slug=item.slug,
        description=item.description,
        price_cents=item.price_cents,
        currency=item.currency,
        primary_image_url=build_public_asset_url(item.primary_image_path),
        category=category,
        collection=collection,
        images=images,
    )


def _etag_for_payload(payload: dict) -> str:
    serialized = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=True)
    digest = hashlib.sha256(serialized.encode('utf-8')).hexdigest()
    return f'W/"{digest}"'


def _etag_matches(if_none_match: str | None, etag: str) -> bool:
    if not if_none_match:
        return False
    values = [token.strip() for token in if_none_match.split(',')]
    if '*' in values:
        return True
    etag_without_weak = etag.replace('W/', '')
    return etag in values or etag_without_weak in values


def _cached_json_response(
    payload: dict,
    *,
    last_modified: datetime,
    if_none_match: str | None,
    key_id: str | None,
) -> Response:
    etag = _etag_for_payload(payload)
    normalized_last_modified = last_modified.astimezone(timezone.utc)
    headers = {
        'Cache-Control': CACHE_CONTROL_VALUE,
        'ETag': etag,
        'Last-Modified': format_datetime(normalized_last_modified, usegmt=True),
    }
    if key_id:
        headers['X-Public-Read-Key-Id'] = key_id
    if _etag_matches(if_none_match, etag):
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)
    return JSONResponse(content=payload, headers=headers, status_code=status.HTTP_200_OK)


def _resolve_catalog_ids(db: Session, *, drop_slug: str | None, collection_slug: str | None) -> tuple[int | None, int | None]:
    category_id = None
    collection_id = None
    if drop_slug:
        category_id = db.execute(select(Category.id).where(Category.slug == drop_slug)).scalar_one_or_none()
        if category_id is None:
            return None, None
    if collection_slug:
        collection_id = db.execute(select(Collection.id).where(Collection.slug == collection_slug)).scalar_one_or_none()
        if collection_id is None:
            return None, None
    return category_id, collection_id


def _empty_products_response(*, page: int, page_size: int) -> PublicProductListResponse:
    return PublicProductListResponse(
        items=[],
        meta=PaginationMeta(page=page, page_size=page_size, total=0, total_pages=0),
    )


@router.get('/products')
def list_public_products(
    request: Request,
    db: Session = Depends(get_db),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    q: str | None = Query(default=None, min_length=2, max_length=120),
    category_id: int | None = Query(default=None, ge=1),
    collection_id: int | None = Query(default=None, ge=1),
    drop_slug: str | None = Query(default=None, min_length=2, max_length=120),
    status_filter: str = Query(default='active', alias='status'),
    if_none_match: str | None = Header(default=None, alias='If-None-Match'),
    x_public_read_key: str | None = Header(default=None, alias='X-Public-Read-Key'),
) -> Response:
    key_id = _resolve_read_key_id(x_public_read_key)
    _enforce_public_rate_limit(request, 'public-products')
    if status_filter.strip().lower() != 'active':
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='status soportado: active')

    effective_category_id = category_id
    if drop_slug:
        effective_category_id = db.execute(select(Category.id).where(Category.slug == drop_slug)).scalar_one_or_none()
        if effective_category_id is None:
            payload = _empty_products_response(page=page, page_size=page_size).model_dump(mode='json')
            return _cached_json_response(payload, last_modified=datetime.now(timezone.utc), if_none_match=if_none_match, key_id=key_id)

    filters = [Product.status == ContentStatus.published]
    if q:
        filters.append(Product.name.ilike(f'%{q.strip()}%'))
    if effective_category_id:
        filters.append(Product.category_id == effective_category_id)
    if collection_id:
        filters.append(Product.collection_id == collection_id)

    statement = (
        select(Product)
        .options(selectinload(Product.images), selectinload(Product.category), selectinload(Product.collection))
        .where(*filters)
        .order_by(Product.sort_order.asc(), Product.created_at.desc())
    )
    items, meta = paginate_select(db, statement, page, page_size)
    response_model = PublicProductListResponse(items=[_product_to_public(item) for item in items], meta=meta)
    last_modified = db.execute(select(func.max(Product.updated_at)).where(*filters)).scalar_one_or_none() or datetime.now(timezone.utc)
    payload = response_model.model_dump(mode='json')
    return _cached_json_response(payload, last_modified=last_modified, if_none_match=if_none_match, key_id=key_id)


@router.get('/products/{product_id}')
def get_public_product(
    product_id: str,
    request: Request,
    db: Session = Depends(get_db),
    if_none_match: str | None = Header(default=None, alias='If-None-Match'),
    x_public_read_key: str | None = Header(default=None, alias='X-Public-Read-Key'),
) -> Response:
    key_id = _resolve_read_key_id(x_public_read_key)
    _enforce_public_rate_limit(request, 'public-product-detail')
    product = db.execute(
        select(Product)
        .options(selectinload(Product.images), selectinload(Product.category), selectinload(Product.collection))
        .where(Product.id == product_id, Product.status == ContentStatus.published)
    ).scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Producto publico no encontrado')
    payload = _product_to_public(product).model_dump(mode='json')
    last_modified = product.updated_at or product.created_at or datetime.now(timezone.utc)
    return _cached_json_response(payload, last_modified=last_modified, if_none_match=if_none_match, key_id=key_id)


@router.get('/taxonomy/categories')
def list_public_categories(
    request: Request,
    db: Session = Depends(get_db),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    if_none_match: str | None = Header(default=None, alias='If-None-Match'),
    x_public_read_key: str | None = Header(default=None, alias='X-Public-Read-Key'),
) -> Response:
    key_id = _resolve_read_key_id(x_public_read_key)
    _enforce_public_rate_limit(request, 'public-taxonomy-categories')
    statement = (
        select(Category)
        .join(Product, Product.category_id == Category.id)
        .where(Product.status == ContentStatus.published)
        .distinct()
        .order_by(Category.name.asc())
    )
    items, meta = paginate_select(db, statement, page, page_size)
    response_model = PublicTaxonomyListResponse(items=[PublicTaxonomyRead(id=item.id, name=item.name, slug=item.slug) for item in items], meta=meta)
    last_modified = db.execute(select(func.max(Category.updated_at))).scalar_one_or_none() or datetime.now(timezone.utc)
    payload = response_model.model_dump(mode='json')
    return _cached_json_response(payload, last_modified=last_modified, if_none_match=if_none_match, key_id=key_id)


@router.get('/taxonomy/collections')
def list_public_collections(
    request: Request,
    db: Session = Depends(get_db),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    if_none_match: str | None = Header(default=None, alias='If-None-Match'),
    x_public_read_key: str | None = Header(default=None, alias='X-Public-Read-Key'),
) -> Response:
    key_id = _resolve_read_key_id(x_public_read_key)
    _enforce_public_rate_limit(request, 'public-taxonomy-collections')
    statement = (
        select(Collection)
        .join(Product, Product.collection_id == Collection.id)
        .where(Product.status == ContentStatus.published)
        .distinct()
        .order_by(Collection.name.asc())
    )
    items, meta = paginate_select(db, statement, page, page_size)
    response_model = PublicTaxonomyListResponse(
        items=[PublicTaxonomyRead(id=item.id, name=item.name, slug=item.slug) for item in items],
        meta=meta,
    )
    last_modified = db.execute(select(func.max(Collection.updated_at))).scalar_one_or_none() or datetime.now(timezone.utc)
    payload = response_model.model_dump(mode='json')
    return _cached_json_response(payload, last_modified=last_modified, if_none_match=if_none_match, key_id=key_id)


@router.get('/catalog')
def public_catalog(
    request: Request,
    db: Session = Depends(get_db),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    q: str | None = Query(default=None, min_length=2, max_length=120),
    drop_slug: str | None = Query(default=None, min_length=2, max_length=120),
    cat: str | None = Query(default=None, min_length=2, max_length=120),
    collection_slug: str | None = Query(default=None, min_length=2, max_length=120),
    if_none_match: str | None = Header(default=None, alias='If-None-Match'),
    x_public_read_key: str | None = Header(default=None, alias='X-Public-Read-Key'),
) -> Response:
    key_id = _resolve_read_key_id(x_public_read_key)
    _enforce_public_rate_limit(request, 'public-catalog')
    effective_collection_slug = (collection_slug or cat or '').strip().lower() or None
    effective_drop_slug = drop_slug.strip().lower() if drop_slug else None

    category_id, resolved_collection_id = _resolve_catalog_ids(
        db,
        drop_slug=effective_drop_slug,
        collection_slug=effective_collection_slug,
    )
    if (effective_drop_slug and category_id is None) or (effective_collection_slug and resolved_collection_id is None):
        empty = PublicCatalogResponse(
            drop_slug=effective_drop_slug,
            cat=effective_collection_slug,
            items=[],
            meta=PaginationMeta(page=page, page_size=page_size, total=0, total_pages=0),
        )
        return _cached_json_response(
            empty.model_dump(mode='json'),
            last_modified=datetime.now(timezone.utc),
            if_none_match=if_none_match,
            key_id=key_id,
        )

    filters = [Product.status == ContentStatus.published]
    if q:
        filters.append(Product.name.ilike(f'%{q.strip()}%'))
    if category_id:
        filters.append(Product.category_id == category_id)
    if resolved_collection_id:
        filters.append(Product.collection_id == resolved_collection_id)

    statement = (
        select(Product)
        .options(selectinload(Product.images), selectinload(Product.category), selectinload(Product.collection))
        .where(*filters)
        .order_by(Product.sort_order.asc(), Product.created_at.desc())
    )
    items, meta = paginate_select(db, statement, page, page_size)
    response_model = PublicCatalogResponse(
        drop_slug=effective_drop_slug,
        cat=effective_collection_slug,
        items=[_product_to_public(item) for item in items],
        meta=meta,
    )
    last_modified = db.execute(select(func.max(Product.updated_at)).where(*filters)).scalar_one_or_none() or datetime.now(timezone.utc)
    payload = response_model.model_dump(mode='json')
    return _cached_json_response(payload, last_modified=last_modified, if_none_match=if_none_match, key_id=key_id)
