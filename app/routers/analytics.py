from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.dependencies import require_roles
from app.models import AnalyticsEvent, Catalog, Product, ProductRequest, UserRole
from app.rate_limit import InMemoryRateLimiter
from app.schemas import AnalyticsEventCreate, AnalyticsEventRead

router = APIRouter(prefix='/analytics', tags=['analytics'])
settings = get_settings()
rate_limiter = InMemoryRateLimiter()


def _enforce_rate_limit(
    payload: AnalyticsEventCreate,
    request: Request,
    *,
    max_requests: int,
    window_seconds: int,
) -> None:
    client_ip = request.client.host if request.client else 'unknown'
    key = f'{client_ip}:{payload.session_id}:{payload.visitor_id or "na"}'
    allowed, retry_after = rate_limiter.allow(
        key,
        max_requests=max_requests,
        window_seconds=window_seconds,
    )
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


def _validate_references(payload: AnalyticsEventCreate, db: Session) -> None:
    if payload.product_id and not db.get(Product, payload.product_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Producto no encontrado para evento')
    if payload.catalog_id and not db.get(Catalog, payload.catalog_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Catalogo no encontrado para evento')
    if payload.request_id and not db.get(ProductRequest, payload.request_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Request no encontrado para evento')


def _store_event(payload: AnalyticsEventCreate, db: Session) -> AnalyticsEventRead:
    occurred_at = payload.occurred_at or datetime.now(timezone.utc)
    event = AnalyticsEvent(**payload.model_dump(exclude={'occurred_at'}), occurred_at=occurred_at)
    db.add(event)
    db.commit()
    db.refresh(event)
    return AnalyticsEventRead(
        id=event.id,
        event_type=event.event_type,
        product_id=event.product_id,
        catalog_id=event.catalog_id,
        request_id=event.request_id,
        page=event.page,
        source=event.source,
        session_id=event.session_id,
        visitor_id=event.visitor_id,
        occurred_at=event.occurred_at,
    )


@router.post('/events', response_model=AnalyticsEventRead, dependencies=[Depends(require_roles(UserRole.admin, UserRole.editor))])
def register_event(
    payload: AnalyticsEventCreate,
    request: Request,
    db: Session = Depends(get_db),
) -> AnalyticsEventRead:
    _enforce_rate_limit(
        payload,
        request,
        max_requests=settings.event_rate_limit_requests,
        window_seconds=settings.event_rate_limit_window_seconds,
    )
    _validate_references(payload, db)
    return _store_event(payload, db)


@router.post('/public/events', response_model=AnalyticsEventRead)
def register_public_event(
    payload: AnalyticsEventCreate,
    request: Request,
    db: Session = Depends(get_db),
    x_events_key: str | None = Header(default=None, alias='X-Events-Key'),
) -> AnalyticsEventRead:
    if settings.public_event_write_key and x_events_key != settings.public_event_write_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Clave de tracking invalida')

    _validate_origin(request)
    _enforce_rate_limit(
        payload,
        request,
        max_requests=settings.public_event_rate_limit_requests,
        window_seconds=settings.public_event_rate_limit_window_seconds,
    )
    _validate_references(payload, db)
    return _store_event(payload, db)
