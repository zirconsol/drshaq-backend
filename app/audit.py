from datetime import datetime

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.models import AuditLog, User


def serialize_instance(instance: object) -> dict:
    mapper = inspect(instance).mapper
    data: dict = {}
    for column in mapper.columns:
        value = getattr(instance, column.key)
        if isinstance(value, datetime):
            data[column.key] = value.isoformat()
        else:
            data[column.key] = value
    return data


def log_audit(
    db: Session,
    actor: User | None,
    entity_type: str,
    entity_id: str,
    action: str,
    before_state: dict | None,
    after_state: dict | None,
) -> None:
    db.add(
        AuditLog(
            actor_user_id=actor.id if actor else None,
            actor_username=actor.username if actor else None,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            before_state=before_state,
            after_state=after_state,
        )
    )
