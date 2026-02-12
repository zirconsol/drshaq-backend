from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_roles
from app.models import AnalyticsEvent, Catalog, EventType, Product, ProductRequest, ProductRequestItem, RequestStatus, UserRole
from app.schemas import (
    CatalogKpi,
    FunnelKpiResponse,
    KpiReportResponse,
    KpiSummary,
    ProductKpi,
    TopProductsResponse,
    TopRequestedProductKpi,
    TopRequestedProductsResponse,
    UTMReferrerKpi,
    UTMReferrerResponse,
)

router = APIRouter(prefix='/reporting', tags=['reporting'])


impression_case = case((AnalyticsEvent.event_type == EventType.impression, 1), else_=0)
click_case = case((AnalyticsEvent.event_type == EventType.click, 1), else_=0)
fulfilled_qty_case = case((ProductRequest.status == RequestStatus.fulfilled, ProductRequestItem.quantity), else_=0)


def _resolve_dates(
    start_at: datetime | None,
    end_at: datetime | None,
    *,
    from_at: datetime | None = None,
    to_at: datetime | None = None,
    tz: str = 'UTC',
) -> tuple[datetime, datetime]:
    requested_tz = tz or 'UTC'
    try:
        zone = ZoneInfo(requested_tz)
    except ZoneInfoNotFoundError:
        zone = ZoneInfo('UTC')

    end_local = end_at or to_at or datetime.now(zone)
    start_local = start_at or from_at or (end_local - timedelta(days=30))

    if start_local.tzinfo is None:
        start_local = start_local.replace(tzinfo=zone)
    if end_local.tzinfo is None:
        end_local = end_local.replace(tzinfo=zone)

    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def _ctr(clicks: int, impressions: int) -> float:
    return round((clicks / impressions) * 100, 2) if impressions > 0 else 0.0


def _rate(part: int, total: int) -> float:
    return round((part / total) * 100, 2) if total > 0 else 0.0


def _normalize_source(source: str | None) -> str | None:
    if source is None:
        return None
    normalized = source.strip().lower()
    return normalized or None


@router.get('/kpis', response_model=KpiReportResponse, dependencies=[Depends(require_roles(UserRole.admin, UserRole.editor))])
def get_kpis(
    start_at: datetime | None = Query(default=None),
    end_at: datetime | None = Query(default=None),
    product_id: str | None = Query(default=None, min_length=36, max_length=36),
    catalog_id: str | None = Query(default=None, min_length=36, max_length=36),
    top_limit: int = Query(default=10, ge=1, le=100),
    db: Session = Depends(get_db),
) -> KpiReportResponse:
    start, end = _resolve_dates(start_at, end_at)

    base_filters = [AnalyticsEvent.occurred_at >= start, AnalyticsEvent.occurred_at <= end]
    if product_id:
        base_filters.append(AnalyticsEvent.product_id == product_id)
    if catalog_id:
        base_filters.append(AnalyticsEvent.catalog_id == catalog_id)

    totals_stmt = select(
        func.coalesce(func.sum(impression_case), 0).label('impressions'),
        func.coalesce(func.sum(click_case), 0).label('clicks'),
    ).where(*base_filters)
    totals = db.execute(totals_stmt).one()
    impressions = int(totals.impressions or 0)
    clicks = int(totals.clicks or 0)

    product_rows = db.execute(
        select(
            Product.id,
            Product.name,
            func.coalesce(func.sum(impression_case), 0).label('impressions'),
            func.coalesce(func.sum(click_case), 0).label('clicks'),
        )
        .join(Product, AnalyticsEvent.product_id == Product.id)
        .where(*base_filters)
        .group_by(Product.id, Product.name)
        .order_by(func.sum(click_case).desc(), func.sum(impression_case).desc())
        .limit(top_limit)
    ).all()

    catalog_rows = db.execute(
        select(
            Catalog.id,
            Catalog.name,
            func.coalesce(func.sum(impression_case), 0).label('impressions'),
            func.coalesce(func.sum(click_case), 0).label('clicks'),
        )
        .join(Catalog, AnalyticsEvent.catalog_id == Catalog.id)
        .where(*base_filters)
        .group_by(Catalog.id, Catalog.name)
        .order_by(func.sum(click_case).desc(), func.sum(impression_case).desc())
        .limit(top_limit)
    ).all()

    by_product = [
        ProductKpi(
            product_id=row.id,
            product_name=row.name,
            impressions=int(row.impressions or 0),
            clicks=int(row.clicks or 0),
            ctr=_ctr(int(row.clicks or 0), int(row.impressions or 0)),
        )
        for row in product_rows
    ]

    by_catalog = [
        CatalogKpi(
            catalog_id=row.id,
            catalog_name=row.name,
            impressions=int(row.impressions or 0),
            clicks=int(row.clicks or 0),
            ctr=_ctr(int(row.clicks or 0), int(row.impressions or 0)),
        )
        for row in catalog_rows
    ]

    return KpiReportResponse(
        start_at=start,
        end_at=end,
        total=KpiSummary(impressions=impressions, clicks=clicks, ctr=_ctr(clicks, impressions)),
        by_product=by_product,
        by_catalog=by_catalog,
    )


@router.get('/top-products', response_model=TopProductsResponse, dependencies=[Depends(require_roles(UserRole.admin, UserRole.editor))])
def get_top_products(
    start_at: datetime | None = Query(default=None),
    end_at: datetime | None = Query(default=None),
    limit: int = Query(default=10, ge=1, le=100),
    db: Session = Depends(get_db),
) -> TopProductsResponse:
    start, end = _resolve_dates(start_at, end_at)
    base_filters = [AnalyticsEvent.occurred_at >= start, AnalyticsEvent.occurred_at <= end]

    rows = db.execute(
        select(
            Product.id,
            Product.name,
            func.coalesce(func.sum(impression_case), 0).label('impressions'),
            func.coalesce(func.sum(click_case), 0).label('clicks'),
        )
        .join(Product, AnalyticsEvent.product_id == Product.id)
        .where(*base_filters)
        .group_by(Product.id, Product.name)
        .order_by(func.sum(click_case).desc(), func.sum(impression_case).desc())
        .limit(limit)
    ).all()

    items = [
        ProductKpi(
            product_id=row.id,
            product_name=row.name,
            impressions=int(row.impressions or 0),
            clicks=int(row.clicks or 0),
            ctr=_ctr(int(row.clicks or 0), int(row.impressions or 0)),
        )
        for row in rows
    ]

    return TopProductsResponse(start_at=start, end_at=end, items=items)


@router.get('/utm-referrer', response_model=UTMReferrerResponse, dependencies=[Depends(require_roles(UserRole.admin, UserRole.editor))])
def get_utm_referrer_performance(
    start_at: datetime | None = Query(default=None),
    end_at: datetime | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> UTMReferrerResponse:
    start, end = _resolve_dates(start_at, end_at)
    base_filters = [AnalyticsEvent.occurred_at >= start, AnalyticsEvent.occurred_at <= end]

    rows = db.execute(
        select(
            AnalyticsEvent.utm_source,
            AnalyticsEvent.utm_campaign,
            AnalyticsEvent.referrer,
            func.coalesce(func.sum(impression_case), 0).label('impressions'),
            func.coalesce(func.sum(click_case), 0).label('clicks'),
        )
        .where(*base_filters)
        .group_by(AnalyticsEvent.utm_source, AnalyticsEvent.utm_campaign, AnalyticsEvent.referrer)
        .order_by(func.sum(click_case).desc(), func.sum(impression_case).desc())
        .limit(limit)
    ).all()

    items = [
        UTMReferrerKpi(
            utm_source=row.utm_source,
            utm_campaign=row.utm_campaign,
            referrer=row.referrer,
            impressions=int(row.impressions or 0),
            clicks=int(row.clicks or 0),
            ctr=_ctr(int(row.clicks or 0), int(row.impressions or 0)),
        )
        for row in rows
    ]

    return UTMReferrerResponse(start_at=start, end_at=end, items=items)


@router.get('/funnel', response_model=FunnelKpiResponse, dependencies=[Depends(require_roles(UserRole.admin, UserRole.editor))])
def get_funnel_kpis(
    start_at: datetime | None = Query(default=None),
    end_at: datetime | None = Query(default=None),
    from_at: datetime | None = Query(default=None, alias='from'),
    to_at: datetime | None = Query(default=None, alias='to'),
    tz: str = Query(default='UTC', min_length=2, max_length=50),
    source: str | None = Query(default=None, min_length=1, max_length=255),
    db: Session = Depends(get_db),
) -> FunnelKpiResponse:
    start, end = _resolve_dates(start_at, end_at, from_at=from_at, to_at=to_at, tz=tz)
    identity_expr = func.coalesce(AnalyticsEvent.visitor_id, AnalyticsEvent.session_id)
    request_identity_expr = func.coalesce(ProductRequest.visitor_id, ProductRequest.session_id)
    normalized_source = _normalize_source(source)

    cta_filters = [
        AnalyticsEvent.event_type == EventType.cta_click,
        AnalyticsEvent.occurred_at >= start,
        AnalyticsEvent.occurred_at <= end,
    ]
    request_filters = [ProductRequest.created_at >= start, ProductRequest.created_at <= end]
    if normalized_source:
        cta_filters.append(AnalyticsEvent.source == normalized_source)
        request_filters.append(ProductRequest.source == normalized_source)

    cta_identity_subquery = select(func.distinct(identity_expr).label('identity')).where(*cta_filters).subquery()
    cta_users = int(db.execute(select(func.count()).select_from(cta_identity_subquery)).scalar_one() or 0)

    request_filters_from_cta = [*request_filters, request_identity_expr.in_(select(cta_identity_subquery.c.identity))]

    request_submissions = int(
        db.execute(select(func.count(ProductRequest.id)).where(*request_filters_from_cta)).scalar_one() or 0
    )
    request_users = int(
        db.execute(select(func.count(func.distinct(request_identity_expr))).where(*request_filters_from_cta)).scalar_one()
        or 0
    )
    fulfilled_requests = int(
        db.execute(
            select(func.count(ProductRequest.id)).where(
                *request_filters_from_cta,
                ProductRequest.status == RequestStatus.fulfilled,
            )
        ).scalar_one()
        or 0
    )
    fulfilled_users = int(
        db.execute(
            select(func.count(func.distinct(request_identity_expr))).where(
                *request_filters_from_cta,
                ProductRequest.status == RequestStatus.fulfilled,
            )
        ).scalar_one()
        or 0
    )
    declined_requests = int(
        db.execute(
            select(func.count(ProductRequest.id)).where(
                *request_filters_from_cta,
                ProductRequest.status.in_([RequestStatus.declined_customer, RequestStatus.declined_business]),
            )
        ).scalar_one()
        or 0
    )

    return FunnelKpiResponse(
        start_at=start,
        end_at=end,
        cta_users=cta_users,
        request_submissions=request_submissions,
        request_users=request_users,
        fulfilled_requests=fulfilled_requests,
        fulfilled_users=fulfilled_users,
        declined_requests=declined_requests,
        cta_to_request_rate=_rate(request_users, cta_users),
        request_to_fulfilled_rate=_rate(fulfilled_users, request_users),
        cta_to_fulfilled_rate=_rate(fulfilled_users, cta_users),
    )


@router.get(
    '/top-requested-products',
    response_model=TopRequestedProductsResponse,
    dependencies=[Depends(require_roles(UserRole.admin, UserRole.editor))],
)
def get_top_requested_products(
    start_at: datetime | None = Query(default=None),
    end_at: datetime | None = Query(default=None),
    from_at: datetime | None = Query(default=None, alias='from'),
    to_at: datetime | None = Query(default=None, alias='to'),
    tz: str = Query(default='UTC', min_length=2, max_length=50),
    limit: int = Query(default=10, ge=1, le=100),
    source: str | None = Query(default=None, min_length=1, max_length=255),
    db: Session = Depends(get_db),
) -> TopRequestedProductsResponse:
    start, end = _resolve_dates(start_at, end_at, from_at=from_at, to_at=to_at, tz=tz)
    name_expr = func.coalesce(Product.name, ProductRequestItem.product_name).label('product_name')
    normalized_source = _normalize_source(source)

    filters = [ProductRequest.created_at >= start, ProductRequest.created_at <= end]
    if normalized_source:
        filters.append(ProductRequest.source == normalized_source)

    rows = db.execute(
        select(
            ProductRequestItem.product_id,
            name_expr,
            func.count(func.distinct(ProductRequestItem.request_id)).label('request_count'),
            func.coalesce(func.sum(ProductRequestItem.quantity), 0).label('requested_quantity'),
            func.coalesce(func.sum(fulfilled_qty_case), 0).label('fulfilled_quantity'),
        )
        .join(ProductRequest, ProductRequest.id == ProductRequestItem.request_id)
        .outerjoin(Product, Product.id == ProductRequestItem.product_id)
        .where(*filters)
        .group_by(ProductRequestItem.product_id, name_expr)
        .order_by(func.sum(ProductRequestItem.quantity).desc(), func.count(func.distinct(ProductRequestItem.request_id)).desc())
        .limit(limit)
    ).all()

    items = [
        TopRequestedProductKpi(
            product_id=row.product_id,
            product_name=row.product_name,
            request_count=int(row.request_count or 0),
            requested_quantity=int(row.requested_quantity or 0),
            fulfilled_quantity=int(row.fulfilled_quantity or 0),
            fulfillment_rate=_rate(int(row.fulfilled_quantity or 0), int(row.requested_quantity or 0)),
        )
        for row in rows
    ]

    return TopRequestedProductsResponse(start_at=start, end_at=end, items=items)
