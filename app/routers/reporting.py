from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_roles
from app.models import AnalyticsEvent, Catalog, EventType, Product, UserRole
from app.schemas import (
    CatalogKpi,
    KpiReportResponse,
    KpiSummary,
    ProductKpi,
    TopProductsResponse,
    UTMReferrerKpi,
    UTMReferrerResponse,
)

router = APIRouter(prefix='/reporting', tags=['reporting'])


impression_case = case((AnalyticsEvent.event_type == EventType.impression, 1), else_=0)
click_case = case((AnalyticsEvent.event_type == EventType.click, 1), else_=0)


def _resolve_dates(start_at: datetime | None, end_at: datetime | None) -> tuple[datetime, datetime]:
    end = end_at or datetime.now(timezone.utc)
    start = start_at or (end - timedelta(days=30))
    return start, end


def _ctr(clicks: int, impressions: int) -> float:
    return round((clicks / impressions) * 100, 2) if impressions > 0 else 0.0


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
