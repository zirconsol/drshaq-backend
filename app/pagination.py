from math import ceil

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.schemas import PaginationMeta


def paginate_select(db: Session, statement, page: int, page_size: int):
    total = db.execute(select(func.count()).select_from(statement.subquery())).scalar_one()
    items = db.execute(statement.offset((page - 1) * page_size).limit(page_size)).scalars().all()
    total_pages = ceil(total / page_size) if total else 0
    meta = PaginationMeta(page=page, page_size=page_size, total=total, total_pages=total_pages)
    return items, meta
