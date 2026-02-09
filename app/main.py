import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth import ensure_seed_users
from app.config import get_settings
from app.database import SessionLocal, init_db
from app.routers import admin_news, admin_products, analytics, assets, audit, auth, catalogs, news, products, reporting, taxonomy
from app.seed import ensure_default_drop_taxonomy

settings = get_settings()

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s %(message)s',
)
logger = logging.getLogger('dashboard_api')

app = FastAPI(title=settings.app_name, version='1.0.0')

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_credentials=True,
    allow_methods=['GET', 'POST', 'PATCH', 'DELETE', 'OPTIONS'],
    allow_headers=['Authorization', 'Content-Type'],
)

app.include_router(auth.router, prefix=settings.api_prefix)
app.include_router(taxonomy.router, prefix=settings.api_prefix)
app.include_router(products.router, prefix=settings.api_prefix)
app.include_router(admin_products.router, prefix=settings.api_prefix)
app.include_router(news.router, prefix=settings.api_prefix)
app.include_router(admin_news.router, prefix=settings.api_prefix)
app.include_router(catalogs.router, prefix=settings.api_prefix)
app.include_router(analytics.router, prefix=settings.api_prefix)
app.include_router(reporting.router, prefix=settings.api_prefix)
app.include_router(audit.router, prefix=settings.api_prefix)
app.include_router(assets.router, prefix=settings.api_prefix)


@app.on_event('startup')
def on_startup() -> None:
    init_db()
    db = SessionLocal()
    try:
        ensure_default_drop_taxonomy(db)
        ensure_seed_users(db)
    finally:
        db.close()
    logger.info('Dashboard API ready')


@app.get('/healthz')
def healthcheck() -> dict:
    return {'status': 'ok'}
