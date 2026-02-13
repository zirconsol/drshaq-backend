from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.audit import log_audit, serialize_instance
from app.database import get_db
from app.dependencies import get_current_user, require_roles
from app.models import Product, ProductImage, User, UserRole
from app.schemas import ProductImageRead, ProductRead
from app.storage_utils import build_public_asset_url
from app.supabase_storage import SupabaseStorageError, delete_from_supabase, upload_bytes_to_supabase

router = APIRouter(prefix='/admin/products', tags=['admin-products'])


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


def _product_to_read(item: Product) -> ProductRead:
    images = [
        ProductImageRead(
            id=img.id,
            url=img.url,
            public_url=build_public_asset_url(img.url),
            alt_text=img.alt_text,
            sort_order=img.sort_order,
        )
        for img in sorted(item.images, key=lambda i: i.sort_order)
    ]
    return ProductRead(
        id=item.id,
        name=item.name,
        slug=item.slug,
        description=item.description,
        price_cents=item.price_cents,
        currency=item.currency,
        primary_image_path=item.primary_image_path,
        primary_image_url=build_public_asset_url(item.primary_image_path),
        status=item.status,
        sort_order=item.sort_order,
        category_id=item.category_id,
        collection_id=item.collection_id,
        published_at=item.published_at,
        created_at=item.created_at,
        updated_at=item.updated_at,
        images=images,
    )


@router.post(
    '/{product_id}/image/cover',
    response_model=ProductRead,
    dependencies=[Depends(require_roles(UserRole.admin, UserRole.editor))],
)
def upload_cover_image(
    product_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> ProductRead:
    product = db.execute(select(Product).options(selectinload(Product.images)).where(Product.id == product_id)).scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Producto no encontrado')

    if not file.content_type or not file.content_type.startswith('image/'):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Archivo invalido: debe ser imagen')

    ext = _guess_extension(file)
    storage_path = f'products/{product_id}/cover{ext}'
    content = file.file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Archivo vacio')

    try:
        upload_bytes_to_supabase(storage_path, content, file.content_type)
    except SupabaseStorageError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    before = serialize_instance(product)
    product.primary_image_path = storage_path
    db.flush()
    log_audit(db, actor, 'product', product.id, 'set_cover_image', before, serialize_instance(product))
    db.commit()
    db.refresh(product)

    return _product_to_read(product)


@router.post(
    '/{product_id}/image/gallery',
    response_model=ProductImageRead,
    dependencies=[Depends(require_roles(UserRole.admin, UserRole.editor))],
)
def upload_gallery_image(
    product_id: str,
    file: UploadFile = File(...),
    alt_text: str | None = Form(default=None),
    sort_order: int | None = Form(default=None),
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> ProductImageRead:
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Producto no encontrado')

    if not file.content_type or not file.content_type.startswith('image/'):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Archivo invalido: debe ser imagen')

    ext = _guess_extension(file)
    storage_path = f'products/{product_id}/gallery/{uuid4()}{ext}'
    content = file.file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Archivo vacio')

    try:
        upload_bytes_to_supabase(storage_path, content, file.content_type)
    except SupabaseStorageError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    if sort_order is None:
        max_sort_order = db.execute(
            select(func.max(ProductImage.sort_order)).where(ProductImage.product_id == product_id)
        ).scalar_one()
        sort_order = (max_sort_order or 0) + 1

    image = ProductImage(product_id=product_id, url=storage_path, alt_text=alt_text, sort_order=sort_order)
    db.add(image)
    db.flush()
    log_audit(db, actor, 'product_image', str(image.id), 'create', None, serialize_instance(image))
    db.commit()
    db.refresh(image)

    return ProductImageRead(
        id=image.id,
        url=image.url,
        public_url=build_public_asset_url(image.url),
        alt_text=image.alt_text,
        sort_order=image.sort_order,
    )


@router.delete(
    '/{product_id}/image',
    response_model=ProductRead,
    dependencies=[Depends(require_roles(UserRole.admin, UserRole.editor))],
)
def delete_cover_image(
    product_id: str,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> ProductRead:
    product = db.execute(select(Product).options(selectinload(Product.images)).where(Product.id == product_id)).scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Producto no encontrado')

    if not product.primary_image_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='El producto no tiene cover asignada')

    path_to_delete = product.primary_image_path
    try:
        delete_from_supabase(path_to_delete)
    except SupabaseStorageError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    before = serialize_instance(product)
    product.primary_image_path = None
    db.flush()
    log_audit(db, actor, 'product', product.id, 'delete_cover_image', before, serialize_instance(product))
    db.commit()
    db.refresh(product)

    return _product_to_read(product)
