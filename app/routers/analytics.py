from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.dependencies import require_roles
from app.models import AnalyticsEvent, Catalog, Product, UserRole
from app.rate_limit import InMemoryRateLimiter
from app.schemas import AnalyticsEventCreate, AnalyticsEventRead

router = APIRouter(prefix='/analytics', tags=['analytics'])
settings = get_settings()
rate_limiter = InMemoryRateLimiter()


@router.post('/events', response_model=AnalyticsEventRead, dependencies=[Depends(require_roles(UserRole.admin, UserRole.editor))])
def register_event(
    payload: AnalyticsEventCreate,
    request: Request,
    db: Session = Depends(get_db),
) -> AnalyticsEventRead:
    client_ip = request.client.host if request.client else 'unknown'
    key = f'{client_ip}:{payload.session_id}'
    allowed, retry_after = rate_limiter.allow(
        key,
        max_requests=settings.event_rate_limit_requests,
        window_seconds=settings.event_rate_limit_window_seconds,
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail='Rate limit excedido para eventos',
            headers={'Retry-After': str(retry_after)},
        )

    if payload.product_id and not db.get(Product, payload.product_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Producto no encontrado para evento')
    if payload.catalog_id and not db.get(Catalog, payload.catalog_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Catalogo no encontrado para evento')

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
        page=event.page,
        source=event.source,
        session_id=event.session_id,
        occurred_at=event.occurred_at,
    )
