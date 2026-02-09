from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.audit import log_audit, serialize_instance
from app.config import get_settings
from app.database import get_db
from app.dependencies import get_current_user, require_roles
from app.models import News, NewsImage, User, UserRole
from app.schemas import NewsImageRead, NewsRead
from app.storage_utils import build_public_asset_url_for_bucket
from app.supabase_storage import SupabaseStorageError, delete_from_supabase, upload_bytes_to_supabase

router = APIRouter(prefix='/admin/news', tags=['admin-news'])
settings = get_settings()


def _news_bucket() -> str | None:
    return settings.supabase_news_storage_bucket or settings.supabase_storage_bucket


def _guess_extension(file: UploadFile) -> str:
    if file.filename:
        ext = Path(file.filename).suffix.lower()
        if ext:
            return ext

    if file.content_type == 'image/jpeg':
        return '.jpg'
    if file.content_type == 'image/png':
        return '.png'
    if file.content_type == 'image/webp':
        return '.webp'
    if file.content_type == 'image/gif':
        return '.gif'
    return '.bin'


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


@router.post(
    '/{news_id}/image/banner',
    response_model=NewsRead,
    dependencies=[Depends(require_roles(UserRole.admin, UserRole.editor))],
)
def upload_banner_image(
    news_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> NewsRead:
    news = db.execute(select(News).options(selectinload(News.images)).where(News.id == news_id)).scalar_one_or_none()
    if not news:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Noticia no encontrada')

    if not file.content_type or not file.content_type.startswith('image/'):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Archivo invalido: debe ser imagen')

    ext = _guess_extension(file)
    storage_path = f'news/{news_id}/cover{ext}'
    content = file.file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Archivo vacio')

    try:
        upload_bytes_to_supabase(storage_path, content, file.content_type, bucket=_news_bucket())
    except SupabaseStorageError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    before = serialize_instance(news)
    news.banner_image_path = storage_path
    db.flush()
    log_audit(db, actor, 'news', news.id, 'set_banner_image', before, serialize_instance(news))
    db.commit()
    db.refresh(news)

    return _news_to_read(news)


@router.post(
    '/{news_id}/image/gallery',
    response_model=NewsImageRead,
    dependencies=[Depends(require_roles(UserRole.admin, UserRole.editor))],
)
def upload_gallery_image(
    news_id: str,
    file: UploadFile = File(...),
    alt_text: str | None = Form(default=None),
    sort_order: int | None = Form(default=None),
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> NewsImageRead:
    news = db.get(News, news_id)
    if not news:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Noticia no encontrada')

    if not file.content_type or not file.content_type.startswith('image/'):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Archivo invalido: debe ser imagen')

    ext = _guess_extension(file)
    storage_path = f'news/{news_id}/gallery/{uuid4()}{ext}'
    content = file.file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Archivo vacio')

    try:
        upload_bytes_to_supabase(storage_path, content, file.content_type, bucket=_news_bucket())
    except SupabaseStorageError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    if sort_order is None:
        max_sort_order = db.execute(select(func.max(NewsImage.sort_order)).where(NewsImage.news_id == news_id)).scalar_one()
        sort_order = (max_sort_order or 0) + 1

    image = NewsImage(news_id=news_id, url=storage_path, alt_text=alt_text, sort_order=sort_order)
    db.add(image)
    db.flush()
    log_audit(db, actor, 'news_image', str(image.id), 'create', None, serialize_instance(image))
    db.commit()
    db.refresh(image)

    return NewsImageRead(
        id=image.id,
        url=image.url,
        public_url=build_public_asset_url_for_bucket(image.url, bucket=_news_bucket()),
        alt_text=image.alt_text,
        sort_order=image.sort_order,
    )


@router.delete(
    '/{news_id}/image/banner',
    response_model=NewsRead,
    dependencies=[Depends(require_roles(UserRole.admin, UserRole.editor))],
)
def delete_banner_image(
    news_id: str,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> NewsRead:
    news = db.execute(select(News).options(selectinload(News.images)).where(News.id == news_id)).scalar_one_or_none()
    if not news:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Noticia no encontrada')

    if not news.banner_image_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='La noticia no tiene banner asignado')

    path_to_delete = news.banner_image_path
    try:
        delete_from_supabase(path_to_delete, bucket=_news_bucket())
    except SupabaseStorageError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    before = serialize_instance(news)
    news.banner_image_path = None
    db.flush()
    log_audit(db, actor, 'news', news.id, 'delete_banner_image', before, serialize_instance(news))
    db.commit()
    db.refresh(news)

    return _news_to_read(news)
