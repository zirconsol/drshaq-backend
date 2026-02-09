from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_roles
from app.models import AuditLog, UserRole
from app.pagination import paginate_select
from app.schemas import AuditLogListResponse, AuditLogRead

router = APIRouter(prefix='/audit', tags=['audit'])


@router.get('/logs', response_model=AuditLogListResponse, dependencies=[Depends(require_roles(UserRole.admin))])
def list_audit_logs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    entity_type: str | None = Query(default=None, min_length=2, max_length=80),
    actor_username: str | None = Query(default=None, min_length=2, max_length=50),
    db: Session = Depends(get_db),
) -> AuditLogListResponse:
    statement = select(AuditLog)
    if entity_type:
        statement = statement.where(AuditLog.entity_type == entity_type)
    if actor_username:
        statement = statement.where(AuditLog.actor_username == actor_username)
    statement = statement.order_by(desc(AuditLog.created_at), desc(AuditLog.id))

    logs, meta = paginate_select(db, statement, page, page_size)
    items = [
        AuditLogRead(
            id=log.id,
            actor_user_id=log.actor_user_id,
            actor_username=log.actor_username,
            entity_type=log.entity_type,
            entity_id=log.entity_id,
            action=log.action,
            before_state=log.before_state,
            after_state=log.after_state,
            created_at=log.created_at,
        )
        for log in logs
    ]
    return AuditLogListResponse(items=items, meta=meta)
