from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.audit import log_audit, serialize_instance
from app.client_ip import build_trusted_proxy_networks, extract_client_ip
from app.config import get_settings
from app.database import get_db
from app.dependencies import get_current_user, require_roles
from app.models import (
    AnalyticsEvent,
    EventType,
    Product,
    ProductRequest,
    ProductRequestItem,
    ProductRequestStatusHistory,
    RequestStatus,
    User,
    UserRole,
)
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
trusted_proxy_networks = build_trusted_proxy_networks(settings.trusted_proxy_cidrs)

terminal_statuses = {RequestStatus.fulfilled, RequestStatus.declined_customer, RequestStatus.declined_business}
valid_transitions = {
    RequestStatus.submitted: {RequestStatus.paid},
    RequestStatus.paid: terminal_statuses,
    RequestStatus.fulfilled: set(),
    RequestStatus.declined_customer: set(),
    RequestStatus.declined_business: set(),
}


def _canonical_status(value: RequestStatus) -> RequestStatus:
    if value in {RequestStatus.contacted, RequestStatus.in_progress}:
        return RequestStatus.paid
    return value


def _storage_status(value: RequestStatus) -> RequestStatus:
    if value in {RequestStatus.paid, RequestStatus.in_progress}:
        # Keeps compatibility with existing DB check constraints.
        return RequestStatus.contacted
    return value


def _request_to_read(item: ProductRequest) -> ProductRequestRead:
    return ProductRequestRead(
        id=item.id,
        idempotency_key=item.idempotency_key,
        session_id=item.session_id,
        visitor_id=item.visitor_id,
        status=_canonical_status(item.status),
        status_reason=item.status_reason,
        status_updated_by_user_id=item.status_updated_by_user_id,
        status_updated_at=item.status_updated_at,
        page=item.page,
        page_path=item.page,
        source=item.source,
        customer_name=item.customer_name,
        customer_email=item.customer_email,
        customer_phone=item.customer_phone,
        notes=item.notes,
        utm_source=item.utm_source,
        utm_medium=item.utm_medium,
        utm_campaign=item.utm_campaign,
        referrer=item.referrer,
        total_amount_cents=item.total_amount_cents,
        created_at=item.created_at,
        updated_at=item.updated_at,
        contacted_at=item.contacted_at,
        paid_at=item.paid_at,
        delivered_at=item.delivered_at,
        resolved_at=item.resolved_at,
        items=[
            ProductRequestItemRead(
                product_id=row.product_id,
                product_name=row.product_name,
                qty=row.quantity,
                variant_size=row.variant_size,
                variant_color=row.variant_color,
                unit_price_cents=row.unit_price_cents,
                quantity=row.quantity,
            )
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


def _validate_key(x_events_key: str | None) -> str | None:
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


@router.post('/public', response_model=ProductRequestRead, status_code=201)
def create_public_request(
    payload: ProductRequestCreate,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    x_events_key: str | None = Header(default=None, alias='X-Events-Key'),
) -> ProductRequestRead:
    key_id = _validate_key(x_events_key)
    _validate_origin(request)

    client_ip = extract_client_ip(
        request,
        trusted_proxy_networks=trusted_proxy_networks,
        trust_proxy_headers=settings.trust_proxy_headers,
    )
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

    existing = db.execute(
        select(ProductRequest).options(selectinload(ProductRequest.items)).where(
            ProductRequest.idempotency_key == payload.idempotency_key
        )
    ).scalar_one_or_none()
    if existing:
        response.status_code = status.HTTP_200_OK
        return _request_to_read(existing)

    merged_items: dict[str, dict] = {}
    for row in payload.items:
        item = merged_items.get(row.product_id)
        if item is None:
            merged_items[row.product_id] = {
                'qty': row.qty,
                'variant_size': row.variant_size,
                'variant_color': row.variant_color,
                'unit_price_cents': row.unit_price_cents,
            }
            continue

        item['qty'] += row.qty
        if item['variant_size'] != row.variant_size:
            item['variant_size'] = None
        if item['variant_color'] != row.variant_color:
            item['variant_color'] = None
        if item['unit_price_cents'] != row.unit_price_cents:
            item['unit_price_cents'] = None

    product_rows = db.execute(select(Product).where(Product.id.in_(merged_items.keys()))).scalars().all()
    product_by_id = {row.id: row for row in product_rows}
    missing_ids = [product_id for product_id in merged_items if product_id not in product_by_id]
    if missing_ids:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f'Productos no encontrados: {", ".join(missing_ids)}')

    request_row = ProductRequest(
        idempotency_key=payload.idempotency_key,
        session_id=payload.session_id,
        visitor_id=payload.visitor_id,
        status=RequestStatus.submitted,
        page=payload.page_path,
        source=payload.source.value,
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

    total_amount_cents = 0
    total_has_unknown_price = False
    for product_id, item in merged_items.items():
        resolved_unit_price_cents = item['unit_price_cents']
        if resolved_unit_price_cents is None:
            resolved_unit_price_cents = product_by_id[product_id].price_cents
        if resolved_unit_price_cents is None:
            total_has_unknown_price = True
        else:
            total_amount_cents += resolved_unit_price_cents * item['qty']
        db.add(
            ProductRequestItem(
                request_id=request_row.id,
                product_id=product_id,
                product_name=product_by_id[product_id].name,
                quantity=item['qty'],
                variant_size=item['variant_size'],
                variant_color=item['variant_color'],
                unit_price_cents=resolved_unit_price_cents,
            )
        )
    request_row.total_amount_cents = None if total_has_unknown_price else total_amount_cents

    now = datetime.now(timezone.utc)
    db.add(
        AnalyticsEvent(
            event_type=EventType.request_submitted,
            request_id=request_row.id,
            page=payload.page_path,
            source=payload.source.value,
            session_id=payload.session_id,
            visitor_id=payload.visitor_id,
            idempotency_key=f'request:{payload.idempotency_key}',
            key_id=key_id,
            utm_source=payload.utm_source,
            utm_medium=payload.utm_medium,
            utm_campaign=payload.utm_campaign,
            referrer=payload.referrer,
            occurred_at=now,
            received_at=now,
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
    source: str | None = Query(default=None, min_length=1, max_length=255),
    db: Session = Depends(get_db),
) -> ProductRequestListResponse:
    statement = select(ProductRequest).options(selectinload(ProductRequest.items))

    if status_filter:
        normalized_status = _canonical_status(status_filter)
        if normalized_status == RequestStatus.paid:
            statement = statement.where(
                ProductRequest.status.in_([RequestStatus.paid, RequestStatus.in_progress, RequestStatus.contacted])
            )
        else:
            statement = statement.where(ProductRequest.status == normalized_status)
    if start_at:
        statement = statement.where(ProductRequest.created_at >= start_at)
    if end_at:
        statement = statement.where(ProductRequest.created_at <= end_at)
    if session_id:
        statement = statement.where(ProductRequest.session_id == session_id)
    if source:
        statement = statement.where(ProductRequest.source == source.strip().lower())
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

    current_status = _canonical_status(request_row.status)
    target_status = _canonical_status(payload.status)
    storage_target_status = _storage_status(target_status)
    now = datetime.now(timezone.utc)

    if target_status == RequestStatus.submitted and current_status != RequestStatus.submitted:
        if not settings.request_allow_reopen_to_submitted:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail='Revertir a submitted no esta habilitado en este entorno',
            )
        if not payload.reason:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='reason obligatorio para reabrir')
    elif target_status != current_status and target_status not in valid_transitions.get(current_status, set()):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f'Transicion invalida: {current_status.value} -> {target_status.value}',
        )

    before = serialize_instance(request_row)
    previous_status = request_row.status
    request_row.status = storage_target_status
    if payload.notes is not None:
        request_row.notes = payload.notes
    request_row.status_reason = payload.reason
    request_row.status_updated_by_user_id = actor.id
    request_row.status_updated_at = now

    if target_status == RequestStatus.submitted:
        request_row.contacted_at = None
        request_row.paid_at = None
        request_row.delivered_at = None
        request_row.resolved_at = None
    elif target_status == RequestStatus.paid:
        if request_row.contacted_at is None:
            request_row.contacted_at = now
        if request_row.paid_at is None:
            request_row.paid_at = now
        request_row.delivered_at = None
        request_row.resolved_at = None
    elif target_status == RequestStatus.fulfilled:
        if request_row.contacted_at is None:
            request_row.contacted_at = now
        if request_row.paid_at is None:
            request_row.paid_at = now
        request_row.delivered_at = now
        request_row.resolved_at = now
    elif target_status in terminal_statuses:
        if request_row.contacted_at is None:
            request_row.contacted_at = now
        request_row.delivered_at = None
        request_row.resolved_at = now

    if storage_target_status != previous_status:
        db.add(
            ProductRequestStatusHistory(
                request_id=request_row.id,
                previous_status=previous_status,
                new_status=storage_target_status,
                reason=payload.reason,
                changed_by_user_id=actor.id,
                changed_by_username=actor.username,
                changed_at=now,
            )
        )

    db.flush()
    log_audit(db, actor, 'product_request', request_row.id, 'update_status', before, serialize_instance(request_row))
    db.commit()
    db.refresh(request_row)
    return _request_to_read(request_row)
