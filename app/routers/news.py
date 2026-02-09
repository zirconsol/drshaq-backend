from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session, selectinload

from app.audit import log_audit, serialize_instance
from app.config import get_settings
from app.database import get_db
from app.dependencies import get_current_user, require_roles
from app.models import News, NewsImage, User, UserRole
from app.pagination import paginate_select
from app.schemas import (
    NewsCreate,
    NewsImageCreate,
    NewsImageRead,
    NewsImageUpdate,
    NewsListResponse,
    NewsRead,
    NewsUpdate,
)
from app.storage_utils import build_public_asset_url_for_bucket, normalize_storage_path
from app.supabase_storage import SupabaseStorageError, delete_from_supabase

router = APIRouter(prefix='/news', tags=['news'])
settings = get_settings()


def _news_bucket() -> str | None:
    return settings.supabase_news_storage_bucket or settings.supabase_storage_bucket


def _news_to_read(item: News) -> NewsRead:
    bucket = _news_bucket()
    images = [
        NewsImageRead(
            id=img.id,
            url=img.url,
            public_url=build_public_asset_url_for_bucket(img.url, bucket=bucket),
            alt_text=img.alt_text,
            sort_order=img.sort_order,
        )
        for img in sorted(item.images, key=lambda i: i.sort_order)
    ]
    return NewsRead(
        id=item.id,
        title=item.title,
        banner_image_path=item.banner_image_path,
        banner_image_url=build_public_asset_url_for_bucket(item.banner_image_path, bucket=bucket),
        description=item.description,
        is_featured=item.is_featured,
        created_at=item.created_at,
        updated_at=item.updated_at,
        images=images,
    )


def _delete_news_asset(path: str) -> None:
    if settings.asset_provider != 'supabase':
        return
    storage_path = normalize_storage_path(path)
    try:
        delete_from_supabase(storage_path, bucket=_news_bucket())
    except SupabaseStorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f'No se pudo eliminar imagen de noticia en storage: {storage_path}',
        ) from exc


def _unset_other_featured_news(db: Session, *, featured_news_id: str) -> None:
    db.execute(update(News).where(News.id != featured_news_id).values(is_featured=False))


@router.post('', response_model=NewsRead, dependencies=[Depends(require_roles(UserRole.admin, UserRole.editor))])
def create_news(
    payload: NewsCreate,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> NewsRead:
    news_data = payload.model_dump()
    if news_data.get('banner_image_path'):
        news_data['banner_image_path'] = normalize_storage_path(news_data['banner_image_path'])

    news = News(**news_data)
    db.add(news)
    db.flush()
    if news.is_featured:
        _unset_other_featured_news(db, featured_news_id=news.id)
    log_audit(db, actor, 'news', news.id, 'create', None, serialize_instance(news))
    db.commit()
    created = db.execute(select(News).options(selectinload(News.images)).where(News.id == news.id)).scalar_one()
    return _news_to_read(created)


@router.get('', response_model=NewsListResponse, dependencies=[Depends(require_roles(UserRole.admin, UserRole.editor))])
def list_news(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    q: str | None = Query(default=None, min_length=2, max_length=120),
    db: Session = Depends(get_db),
) -> NewsListResponse:
    statement = select(News).options(selectinload(News.images))
    if q:
        statement = statement.where(News.title.ilike(f'%{q}%'))
    statement = statement.order_by(News.created_at.desc())

    items, meta = paginate_select(db, statement, page, page_size)
    return NewsListResponse(items=[_news_to_read(item) for item in items], meta=meta)


@router.get('/featured', response_model=NewsRead, dependencies=[Depends(require_roles(UserRole.admin, UserRole.editor))])
def get_featured_news(db: Session = Depends(get_db)) -> NewsRead:
    featured = (
        db.execute(
            select(News)
            .options(selectinload(News.images))
            .where(News.is_featured.is_(True))
            .order_by(News.updated_at.desc())
        )
        .scalars()
        .first()
    )
    if not featured:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='No hay noticia destacada')
    return _news_to_read(featured)


@router.get('/{news_id}', response_model=NewsRead, dependencies=[Depends(require_roles(UserRole.admin, UserRole.editor))])
def get_news(news_id: str, db: Session = Depends(get_db)) -> NewsRead:
    news = db.execute(select(News).options(selectinload(News.images)).where(News.id == news_id)).scalar_one_or_none()
    if not news:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Noticia no encontrada')
    return _news_to_read(news)


@router.patch('/{news_id}', response_model=NewsRead, dependencies=[Depends(require_roles(UserRole.admin, UserRole.editor))])
def update_news(
    news_id: str,
    payload: NewsUpdate,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> NewsRead:
    news = db.execute(select(News).options(selectinload(News.images)).where(News.id == news_id)).scalar_one_or_none()
    if not news:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Noticia no encontrada')

    data = payload.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='No hay cambios para aplicar')

    before = serialize_instance(news)
    for field, value in data.items():
        if field == 'banner_image_path' and value is not None:
            value = normalize_storage_path(value)
        setattr(news, field, value)
    if data.get('is_featured') is True:
        _unset_other_featured_news(db, featured_news_id=news.id)

    db.flush()
    log_audit(db, actor, 'news', news.id, 'update', before, serialize_instance(news))
    db.commit()
    db.refresh(news)
    return _news_to_read(news)


@router.post(
    '/{news_id}/feature',
    response_model=NewsRead,
    dependencies=[Depends(require_roles(UserRole.admin, UserRole.editor))],
)
def feature_news(
    news_id: str,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> NewsRead:
    news = db.execute(select(News).options(selectinload(News.images)).where(News.id == news_id)).scalar_one_or_none()
    if not news:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Noticia no encontrada')

    before = serialize_instance(news)
    _unset_other_featured_news(db, featured_news_id=news.id)
    news.is_featured = True

    db.flush()
    log_audit(db, actor, 'news', news.id, 'feature', before, serialize_instance(news))
    db.commit()
    db.refresh(news)
    return _news_to_read(news)


@router.delete('/{news_id}', status_code=204, dependencies=[Depends(require_roles(UserRole.admin))])
def delete_news(
    news_id: str,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> None:
    news = db.execute(select(News).options(selectinload(News.images)).where(News.id == news_id)).scalar_one_or_none()
    if not news:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Noticia no encontrada')

    paths_to_delete: list[str] = []
    if news.banner_image_path:
        paths_to_delete.append(news.banner_image_path)
    paths_to_delete.extend([img.url for img in news.images if img.url])
    for path in list(dict.fromkeys(paths_to_delete)):
        _delete_news_asset(path)

    before = serialize_instance(news)
    db.delete(news)
    log_audit(db, actor, 'news', news_id, 'delete', before, None)
    db.commit()


@router.post('/{news_id}/images', response_model=NewsImageRead, dependencies=[Depends(require_roles(UserRole.admin, UserRole.editor))])
def add_news_image(
    news_id: str,
    payload: NewsImageCreate,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> NewsImageRead:
    news = db.get(News, news_id)
    if not news:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Noticia no encontrada')

    image_data = payload.model_dump()
    image_data['url'] = normalize_storage_path(image_data['url'])
    image = NewsImage(news_id=news_id, **image_data)
    db.add(image)
    db.flush()
    log_audit(db, actor, 'news_image', str(image.id), 'create', None, serialize_instance(image))
    db.commit()
    return NewsImageRead(
        id=image.id,
        url=image.url,
        public_url=build_public_asset_url_for_bucket(image.url, bucket=_news_bucket()),
        alt_text=image.alt_text,
        sort_order=image.sort_order,
    )


@router.patch('/{news_id}/images/{image_id}', response_model=NewsImageRead, dependencies=[Depends(require_roles(UserRole.admin, UserRole.editor))])
def update_news_image(
    news_id: str,
    image_id: int,
    payload: NewsImageUpdate,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> NewsImageRead:
    image = db.execute(select(NewsImage).where(NewsImage.id == image_id, NewsImage.news_id == news_id)).scalar_one_or_none()
    if not image:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Imagen de noticia no encontrada')

    data = payload.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='No hay cambios para aplicar')

    before = serialize_instance(image)
    for field, value in data.items():
        if field == 'url' and value is not None:
            value = normalize_storage_path(value)
        setattr(image, field, value)

    db.flush()
    log_audit(db, actor, 'news_image', str(image.id), 'update', before, serialize_instance(image))
    db.commit()
    db.refresh(image)
    return NewsImageRead(
        id=image.id,
        url=image.url,
        public_url=build_public_asset_url_for_bucket(image.url, bucket=_news_bucket()),
        alt_text=image.alt_text,
        sort_order=image.sort_order,
    )


@router.delete('/{news_id}/images/{image_id}', status_code=204, dependencies=[Depends(require_roles(UserRole.admin, UserRole.editor))])
def delete_news_image(
    news_id: str,
    image_id: int,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> None:
    image = db.execute(select(NewsImage).where(NewsImage.id == image_id, NewsImage.news_id == news_id)).scalar_one_or_none()
    if not image:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Imagen de noticia no encontrada')

    if image.url:
        _delete_news_asset(image.url)

    before = serialize_instance(image)
    db.delete(image)
    log_audit(db, actor, 'news_image', str(image.id), 'delete', before, None)
    db.commit()
