from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from time import perf_counter

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import SessionLocal, init_db
from app.models import AnalyticsEvent

logger = logging.getLogger('dashboard_api.retention')


@dataclass
class TrackingPurgeResult:
    dry_run: bool
    retention_days: int
    cutoff_at: str
    candidates: int
    deleted: int
    elapsed_ms: int


def purge_tracking_events(
    session: Session,
    *,
    retention_days: int,
    dry_run: bool,
    now: datetime | None = None,
) -> TrackingPurgeResult:
    started = perf_counter()
    reference = now or datetime.now(timezone.utc)
    cutoff = reference - timedelta(days=retention_days)
    cutoff_expr = func.coalesce(AnalyticsEvent.received_at, AnalyticsEvent.created_at, AnalyticsEvent.occurred_at)

    candidates = int(session.execute(select(func.count()).where(cutoff_expr < cutoff)).scalar_one() or 0)
    deleted = 0

    if not dry_run and candidates > 0:
        deleted = int(session.execute(delete(AnalyticsEvent).where(cutoff_expr < cutoff)).rowcount or 0)
        session.commit()

    elapsed_ms = int((perf_counter() - started) * 1000)
    result = TrackingPurgeResult(
        dry_run=dry_run,
        retention_days=retention_days,
        cutoff_at=cutoff.isoformat(),
        candidates=candidates,
        deleted=deleted,
        elapsed_ms=elapsed_ms,
    )
    logger.info(
        'tracking_retention_purge dry_run=%s retention_days=%s cutoff_at=%s candidates=%s deleted=%s elapsed_ms=%s',
        result.dry_run,
        result.retention_days,
        result.cutoff_at,
        result.candidates,
        result.deleted,
        result.elapsed_ms,
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Purge tracking events older than retention window.')
    parser.add_argument('--days', type=int, default=None, help='Retention window in days')
    parser.add_argument('--dry-run', action='store_true', help='Preview candidates without deleting')
    parser.add_argument('--apply', action='store_true', help='Delete matching events')
    args = parser.parse_args(argv)

    settings = get_settings()
    retention_days = args.days if args.days is not None else settings.tracking_retention_days
    dry_run = True
    if args.apply:
        dry_run = False
    elif args.dry_run:
        dry_run = True

    init_db()
    with SessionLocal() as session:
        result = purge_tracking_events(session, retention_days=retention_days, dry_run=dry_run)
    print(json.dumps(asdict(result), ensure_ascii=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
