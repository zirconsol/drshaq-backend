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

    if inspector.has_table('news'):
        existing_columns = {column['name'] for column in inspector.get_columns('news')}
        if 'is_featured' not in existing_columns:
            with engine.begin() as conn:
                conn.execute(text('ALTER TABLE news ADD COLUMN is_featured BOOLEAN NOT NULL DEFAULT FALSE'))
