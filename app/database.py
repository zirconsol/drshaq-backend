from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from app.config import get_settings

settings = get_settings()

connect_args = {'check_same_thread': False} if settings.database_url.startswith('sqlite') else {}
engine = create_engine(settings.database_url, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _apply_schema_updates()


def _apply_schema_updates() -> None:
    inspector = inspect(engine)

    if inspector.has_table('products'):
        existing_columns = {column['name'] for column in inspector.get_columns('products')}
        if 'primary_image_path' not in existing_columns:
            with engine.begin() as conn:
                conn.execute(text('ALTER TABLE products ADD COLUMN primary_image_path VARCHAR(1024)'))
        with engine.begin() as conn:
            if 'price_cents' not in existing_columns:
                conn.execute(text('ALTER TABLE products ADD COLUMN price_cents INTEGER'))
            if 'currency' not in existing_columns:
                conn.execute(text('ALTER TABLE products ADD COLUMN currency VARCHAR(3)'))

    if inspector.has_table('news'):
        existing_columns = {column['name'] for column in inspector.get_columns('news')}
        if 'is_featured' not in existing_columns:
            with engine.begin() as conn:
                conn.execute(text('ALTER TABLE news ADD COLUMN is_featured BOOLEAN NOT NULL DEFAULT FALSE'))

    if inspector.has_table('analytics_events'):
        existing_columns = {column['name'] for column in inspector.get_columns('analytics_events')}
        with engine.begin() as conn:
            if 'visitor_id' not in existing_columns:
                conn.execute(text('ALTER TABLE analytics_events ADD COLUMN visitor_id VARCHAR(120)'))
            if 'request_id' not in existing_columns:
                conn.execute(text('ALTER TABLE analytics_events ADD COLUMN request_id VARCHAR(36)'))
            if 'idempotency_key' not in existing_columns:
                conn.execute(text('ALTER TABLE analytics_events ADD COLUMN idempotency_key VARCHAR(120)'))
            if 'key_id' not in existing_columns:
                conn.execute(text('ALTER TABLE analytics_events ADD COLUMN key_id VARCHAR(80)'))
            if 'received_at' not in existing_columns:
                conn.execute(text('ALTER TABLE analytics_events ADD COLUMN received_at DATETIME'))
                conn.execute(text('UPDATE analytics_events SET received_at = created_at WHERE received_at IS NULL'))
            conn.execute(
                text(
                    'CREATE UNIQUE INDEX IF NOT EXISTS uq_analytics_events_idempotency_key '
                    'ON analytics_events(idempotency_key)'
                )
            )

    if inspector.has_table('product_requests'):
        existing_columns = {column['name'] for column in inspector.get_columns('product_requests')}
        with engine.begin() as conn:
            if 'idempotency_key' not in existing_columns:
                conn.execute(text('ALTER TABLE product_requests ADD COLUMN idempotency_key VARCHAR(120)'))
            if 'total_amount_cents' not in existing_columns:
                conn.execute(text('ALTER TABLE product_requests ADD COLUMN total_amount_cents INTEGER'))
            if 'status_reason' not in existing_columns:
                conn.execute(text('ALTER TABLE product_requests ADD COLUMN status_reason TEXT'))
            if 'status_updated_by_user_id' not in existing_columns:
                conn.execute(text('ALTER TABLE product_requests ADD COLUMN status_updated_by_user_id VARCHAR(36)'))
            if 'status_updated_at' not in existing_columns:
                conn.execute(text('ALTER TABLE product_requests ADD COLUMN status_updated_at DATETIME'))
            if 'paid_at' not in existing_columns:
                conn.execute(text('ALTER TABLE product_requests ADD COLUMN paid_at DATETIME'))
            if 'delivered_at' not in existing_columns:
                conn.execute(text('ALTER TABLE product_requests ADD COLUMN delivered_at DATETIME'))
            conn.execute(
                text(
                    "UPDATE product_requests SET delivered_at = resolved_at "
                    "WHERE delivered_at IS NULL AND status = 'fulfilled' AND resolved_at IS NOT NULL"
                )
            )
            conn.execute(
                text(
                    "UPDATE product_requests SET paid_at = contacted_at "
                    "WHERE paid_at IS NULL AND contacted_at IS NOT NULL "
                    "AND status IN ('contacted', 'in_progress', 'fulfilled', 'declined_customer', 'declined_business')"
                )
            )
            conn.execute(
                text(
                    'CREATE UNIQUE INDEX IF NOT EXISTS uq_product_requests_idempotency_key '
                    'ON product_requests(idempotency_key)'
                )
            )

    if inspector.has_table('product_request_items'):
        existing_columns = {column['name'] for column in inspector.get_columns('product_request_items')}
        with engine.begin() as conn:
            if 'variant_size' not in existing_columns:
                conn.execute(text('ALTER TABLE product_request_items ADD COLUMN variant_size VARCHAR(40)'))
            if 'variant_color' not in existing_columns:
                conn.execute(text('ALTER TABLE product_request_items ADD COLUMN variant_color VARCHAR(60)'))
            if 'unit_price_cents' not in existing_columns:
                conn.execute(text('ALTER TABLE product_request_items ADD COLUMN unit_price_cents INTEGER'))
