from collections import defaultdict
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.audit import log_audit, serialize_instance
from app.config import get_settings
from app.database import get_db
from app.dependencies import get_current_user, require_roles
from app.models import AnalyticsEvent, EventType, Product, ProductRequest, ProductRequestItem, RequestStatus, User, UserRole
from app.pagination import paginate_select
from app.rate_limit import InMemoryRateLimiter
from app.schemas import (
    ProductRequestCreate,
    ProductRequestItemRead,
    ProductRequestListResponse,
    ProductRequestRead,
    ProductRequestStatusUpdate,
)

router = APIRouter(prefix='/requests', tags=['requests'])
settings = get_settings()
rate_limiter = InMemoryRateLimiter()

resolved_statuses = {RequestStatus.fulfilled, RequestStatus.declined_customer, RequestStatus.declined_business}


def _request_to_read(item: ProductRequest) -> ProductRequestRead:
    return ProductRequestRead(
        id=item.id,
        session_id=item.session_id,
        visitor_id=item.visitor_id,
        status=item.status,
        page=item.page,
        source=item.source,
        customer_name=item.customer_name,
        customer_email=item.customer_email,
        customer_phone=item.customer_phone,
        notes=item.notes,
        utm_source=item.utm_source,
        utm_medium=item.utm_medium,
        utm_campaign=item.utm_campaign,
        referrer=item.referrer,
        created_at=item.created_at,
        updated_at=item.updated_at,
        contacted_at=item.contacted_at,
        resolved_at=item.resolved_at,
        items=[
            ProductRequestItemRead(product_id=row.product_id, product_name=row.product_name, quantity=row.quantity)
            for row in sorted(item.items, key=lambda v: (v.created_at, v.id))
        ],
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


def _validate_key(x_events_key: str | None) -> None:
    if settings.public_event_write_key and x_events_key != settings.public_event_write_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Clave de tracking invalida')


@router.post('/public', response_model=ProductRequestRead, status_code=201)
def create_public_request(
    payload: ProductRequestCreate,
    request: Request,
    db: Session = Depends(get_db),
    x_events_key: str | None = Header(default=None, alias='X-Events-Key'),
) -> ProductRequestRead:
    _validate_key(x_events_key)
    _validate_origin(request)

    client_ip = request.client.host if request.client else 'unknown'
    key = f'{client_ip}:{payload.session_id}:{payload.visitor_id or "na"}'
    allowed, retry_after = rate_limiter.allow(
        key,
        max_requests=settings.public_event_rate_limit_requests,
        window_seconds=settings.public_event_rate_limit_window_seconds,
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail='Rate limit excedido para requests',
            headers={'Retry-After': str(retry_after)},
        )

    requested_qty: dict[str, int] = defaultdict(int)
    for row in payload.items:
        requested_qty[row.product_id] += row.quantity

    product_rows = db.execute(select(Product).where(Product.id.in_(requested_qty.keys()))).scalars().all()
    product_by_id = {row.id: row for row in product_rows}
    missing_ids = [product_id for product_id in requested_qty if product_id not in product_by_id]
    if missing_ids:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f'Productos no encontrados: {", ".join(missing_ids)}')

    request_row = ProductRequest(
        session_id=payload.session_id,
        visitor_id=payload.visitor_id,
        status=RequestStatus.submitted,
        page=payload.page,
        source=payload.source,
        customer_name=payload.customer_name,
        customer_email=payload.customer_email,
        customer_phone=payload.customer_phone,
        notes=payload.notes,
        utm_source=payload.utm_source,
        utm_medium=payload.utm_medium,
        utm_campaign=payload.utm_campaign,
        referrer=payload.referrer,
    )
    db.add(request_row)
    db.flush()

    for product_id, quantity in requested_qty.items():
        db.add(
            ProductRequestItem(
                request_id=request_row.id,
                product_id=product_id,
                product_name=product_by_id[product_id].name,
                quantity=quantity,
            )
        )

    db.add(
        AnalyticsEvent(
            event_type=EventType.request_submitted,
            request_id=request_row.id,
            page=payload.page,
            source=payload.source,
            session_id=payload.session_id,
            visitor_id=payload.visitor_id,
            utm_source=payload.utm_source,
            utm_medium=payload.utm_medium,
            utm_campaign=payload.utm_campaign,
            referrer=payload.referrer,
            occurred_at=datetime.now(timezone.utc),
        )
    )

    db.commit()
    created = db.execute(
        select(ProductRequest).options(selectinload(ProductRequest.items)).where(ProductRequest.id == request_row.id)
    ).scalar_one()
    return _request_to_read(created)


@router.get('', response_model=ProductRequestListResponse, dependencies=[Depends(require_roles(UserRole.admin, UserRole.editor))])
def list_requests(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status_filter: RequestStatus | None = Query(default=None, alias='status'),
    start_at: datetime | None = Query(default=None),
    end_at: datetime | None = Query(default=None),
    session_id: str | None = Query(default=None, min_length=8, max_length=120),
    product_id: str | None = Query(default=None, min_length=36, max_length=36),
    db: Session = Depends(get_db),
) -> ProductRequestListResponse:
    statement = select(ProductRequest).options(selectinload(ProductRequest.items))

    if status_filter:
        statement = statement.where(ProductRequest.status == status_filter)
    if start_at:
        statement = statement.where(ProductRequest.created_at >= start_at)
    if end_at:
        statement = statement.where(ProductRequest.created_at <= end_at)
    if session_id:
        statement = statement.where(ProductRequest.session_id == session_id)
    if product_id:
        statement = statement.where(
            ProductRequest.id.in_(
                select(ProductRequestItem.request_id).where(ProductRequestItem.product_id == product_id)
            )
        )

    statement = statement.order_by(ProductRequest.created_at.desc())
    items, meta = paginate_select(db, statement, page, page_size)
    return ProductRequestListResponse(items=[_request_to_read(item) for item in items], meta=meta)


@router.get('/{request_id}', response_model=ProductRequestRead, dependencies=[Depends(require_roles(UserRole.admin, UserRole.editor))])
def get_request(request_id: str, db: Session = Depends(get_db)) -> ProductRequestRead:
    request_row = db.execute(
        select(ProductRequest).options(selectinload(ProductRequest.items)).where(ProductRequest.id == request_id)
    ).scalar_one_or_none()
    if not request_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Request no encontrado')
    return _request_to_read(request_row)


@router.patch(
    '/{request_id}/status',
    response_model=ProductRequestRead,
    dependencies=[Depends(require_roles(UserRole.admin, UserRole.editor))],
)
def update_request_status(
    request_id: str,
    payload: ProductRequestStatusUpdate,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> ProductRequestRead:
    request_row = db.execute(
        select(ProductRequest).options(selectinload(ProductRequest.items)).where(ProductRequest.id == request_id)
    ).scalar_one_or_none()
    if not request_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Request no encontrado')

    before = serialize_instance(request_row)
    now = datetime.now(timezone.utc)
    request_row.status = payload.status
    if payload.notes is not None:
        request_row.notes = payload.notes

    if payload.status == RequestStatus.submitted:
        request_row.contacted_at = None
        request_row.resolved_at = None
    elif payload.status == RequestStatus.contacted:
        if request_row.contacted_at is None:
            request_row.contacted_at = now
        request_row.resolved_at = None
    elif payload.status in resolved_statuses:
        if request_row.contacted_at is None:
            request_row.contacted_at = now
        request_row.resolved_at = now

    db.flush()
    log_audit(db, actor, 'product_request', request_row.id, 'update_status', before, serialize_instance(request_row))
    db.commit()
    db.refresh(request_row)
    return _request_to_read(request_row)
