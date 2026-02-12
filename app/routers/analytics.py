import logging
from collections import Counter
from datetime import datetime, timezone
from threading import Lock

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.client_ip import build_trusted_proxy_networks, extract_client_ip
from app.config import get_settings
from app.database import get_db
from app.dependencies import require_roles
from app.models import AnalyticsEvent, Catalog, EventType, Product, ProductRequest, UserRole
from app.rate_limit import InMemoryRateLimiter
from app.schemas import AnalyticsEventCreate, AnalyticsEventRead, AnalyticsIngestionMetricsRead, AnalyticsPublicEventCreate

router = APIRouter(prefix='/analytics', tags=['analytics'])
settings = get_settings()
rate_limiter = InMemoryRateLimiter()
logger = logging.getLogger('dashboard_api.analytics')
trusted_proxy_networks = build_trusted_proxy_networks(settings.trusted_proxy_cidrs)


class InMemoryIngestionMetrics:
    def __init__(self) -> None:
        self._counter: Counter[str] = Counter()
        self._lock = Lock()

    def inc(self, key: str, amount: int = 1) -> None:
        with self._lock:
            self._counter[key] += amount

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return {
                'total': int(self._counter.get('total', 0)),
                'ingested': int(self._counter.get('ingested', 0)),
                'duplicated': int(self._counter.get('duplicated', 0)),
                'rate_limited': int(self._counter.get('rate_limited', 0)),
                'unauthorized': int(self._counter.get('unauthorized', 0)),
            }


ingestion_metrics = InMemoryIngestionMetrics()


def _parse_write_keys() -> dict[str, str]:
    keys: dict[str, str] = {}
    if settings.public_event_write_key:
        keys['legacy'] = settings.public_event_write_key
    for idx, item in enumerate(settings.public_event_write_keys, start=1):
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


def _resolve_key_id(x_events_key: str | None) -> str | None:
    valid_keys = _parse_write_keys()
    if not valid_keys:
        if settings.public_event_require_key:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Clave de tracking requerida')
        return None
    if not x_events_key:
        if settings.public_event_require_key:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Clave de tracking requerida')
        return None
    for key_id, key_val in valid_keys.items():
        if x_events_key == key_val:
            return key_id
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Clave de tracking invalida')


def _enforce_rate_limit(
    *,
    session_id: str,
    visitor_id: str | None,
    request: Request,
    max_requests: int,
    window_seconds: int,
) -> None:
    client_ip = extract_client_ip(
        request,
        trusted_proxy_networks=trusted_proxy_networks,
        trust_proxy_headers=settings.trust_proxy_headers,
    )
    key = f'{client_ip}:{visitor_id or "na"}:{session_id}'
    allowed, retry_after = rate_limiter.allow(key, max_requests=max_requests, window_seconds=window_seconds)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail='Rate limit excedido para eventos',
            headers={'Retry-After': str(retry_after)},
        )


def _validate_origin(request: Request) -> None:
    allowed_origins = settings.public_tracking_allowed_origins
    if not allowed_origins:
        return
    origin = request.headers.get('origin')
    if not origin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Origin requerido')
    if origin not in allowed_origins:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Origin no permitido')


def _validate_references(*, product_id: str | None, catalog_id: str | None, request_id: str | None, db: Session) -> None:
    if product_id and not db.get(Product, product_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Producto no encontrado para evento')
    if catalog_id and not db.get(Catalog, catalog_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Catalogo no encontrado para evento')
    if request_id and not db.get(ProductRequest, request_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Request no encontrado para evento')


def _to_read(event: AnalyticsEvent) -> AnalyticsEventRead:
    return AnalyticsEventRead(
        id=event.id,
        event_name=event.event_type,
        event_type=event.event_type,
        product_id=event.product_id,
        catalog_id=event.catalog_id,
        request_id=event.request_id,
        idempotency_key=event.idempotency_key,
        key_id=event.key_id,
        page=event.page,
        page_path=event.page,
        source=event.source,
        session_id=event.session_id,
        visitor_id=event.visitor_id,
        occurred_at=event.occurred_at,
        received_at=event.received_at or event.created_at,
    )


def _store_event(
    *,
    event_type: EventType,
    page: str,
    source: str,
    session_id: str,
    visitor_id: str | None,
    product_id: str | None,
    catalog_id: str | None,
    request_id: str | None,
    idempotency_key: str | None,
    key_id: str | None,
    occurred_at: datetime | None,
    utm_source: str | None,
    utm_medium: str | None,
    utm_campaign: str | None,
    referrer: str | None,
    db: Session,
) -> AnalyticsEventRead:
    if idempotency_key:
        existing = db.execute(select(AnalyticsEvent).where(AnalyticsEvent.idempotency_key == idempotency_key)).scalar_one_or_none()
        if existing:
            return _to_read(existing)

    now = datetime.now(timezone.utc)
    event = AnalyticsEvent(
        event_type=event_type,
        page=page,
        source=source,
        session_id=session_id,
        visitor_id=visitor_id,
        product_id=product_id,
        catalog_id=catalog_id,
        request_id=request_id,
        idempotency_key=idempotency_key,
        key_id=key_id,
        occurred_at=occurred_at or now,
        received_at=now,
        utm_source=utm_source,
        utm_medium=utm_medium,
        utm_campaign=utm_campaign,
        referrer=referrer,
    )
    db.add(event)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        if idempotency_key:
            existing = db.execute(select(AnalyticsEvent).where(AnalyticsEvent.idempotency_key == idempotency_key)).scalar_one_or_none()
            if existing:
                return _to_read(existing)
        raise
    db.refresh(event)
    return _to_read(event)


@router.post('/events', response_model=AnalyticsEventRead, dependencies=[Depends(require_roles(UserRole.admin, UserRole.editor))])
def register_event(
    payload: AnalyticsEventCreate,
    request: Request,
    db: Session = Depends(get_db),
) -> AnalyticsEventRead:
    _enforce_rate_limit(
        session_id=payload.session_id,
        visitor_id=payload.visitor_id,
        request=request,
        max_requests=settings.event_rate_limit_requests,
        window_seconds=settings.event_rate_limit_window_seconds,
    )
    _validate_references(product_id=payload.product_id, catalog_id=payload.catalog_id, request_id=payload.request_id, db=db)
    return _store_event(
        event_type=payload.event_type,
        page=payload.page,
        source=payload.source.value,
        session_id=payload.session_id,
        visitor_id=payload.visitor_id,
        product_id=payload.product_id,
        catalog_id=payload.catalog_id,
        request_id=payload.request_id,
        idempotency_key=payload.idempotency_key,
        key_id=payload.key_id,
        occurred_at=payload.occurred_at,
        utm_source=payload.utm_source,
        utm_medium=payload.utm_medium,
        utm_campaign=payload.utm_campaign,
        referrer=payload.referrer,
        db=db,
    )


@router.post('/public/events', response_model=AnalyticsEventRead)
def register_public_event(
    payload: AnalyticsPublicEventCreate,
    request: Request,
    db: Session = Depends(get_db),
    x_events_key: str | None = Header(default=None, alias='X-Events-Key'),
    x_request_id: str | None = Header(default=None, alias='X-Request-Id'),
) -> AnalyticsEventRead:
    ingestion_metrics.inc('total')
    try:
        key_id = _resolve_key_id(x_events_key)
    except HTTPException:
        ingestion_metrics.inc('unauthorized')
        raise

    _validate_origin(request)
    try:
        _enforce_rate_limit(
            session_id=payload.session_id,
            visitor_id=payload.visitor_id,
            request=request,
            max_requests=settings.public_event_rate_limit_requests,
            window_seconds=settings.public_event_rate_limit_window_seconds,
        )
    except HTTPException:
        ingestion_metrics.inc('rate_limited')
        raise

    _validate_references(product_id=payload.product_id, catalog_id=payload.catalog_id, request_id=payload.request_id, db=db)

    existing = db.execute(
        select(AnalyticsEvent).where(AnalyticsEvent.idempotency_key == payload.idempotency_key)
    ).scalar_one_or_none()
    if existing:
        ingestion_metrics.inc('duplicated')
        return _to_read(existing)

    result = _store_event(
        event_type=payload.event_name,
        page=payload.page_path,
        source=payload.source.value,
        session_id=payload.session_id,
        visitor_id=payload.visitor_id,
        product_id=payload.product_id,
        catalog_id=payload.catalog_id,
        request_id=payload.request_id,
        idempotency_key=payload.idempotency_key,
        key_id=key_id,
        occurred_at=payload.occurred_at,
        utm_source=payload.utm_source,
        utm_medium=payload.utm_medium,
        utm_campaign=payload.utm_campaign,
        referrer=payload.referrer,
        db=db,
    )
    ingestion_metrics.inc('ingested')
    logger.info(
        'analytics_public_event_ingested request_id=%s event_name=%s source=%s visitor_id=%s session_id=%s',
        x_request_id or 'na',
        payload.event_name.value,
        payload.source.value,
        payload.visitor_id,
        payload.session_id,
    )
    return result


@router.get(
    '/public/metrics',
    response_model=AnalyticsIngestionMetricsRead,
    dependencies=[Depends(require_roles(UserRole.admin, UserRole.editor))],
)
def get_public_ingestion_metrics() -> AnalyticsIngestionMetricsRead:
    return AnalyticsIngestionMetricsRead(**ingestion_metrics.snapshot())
