from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.audit import log_audit, serialize_instance
from app.config import get_settings
from app.database import get_db
from app.dependencies import get_current_user, require_roles
from app.models import Category, CategoryCollection, Collection, ContentStatus, Product, ProductImage, User, UserRole
from app.pagination import paginate_select
from app.schemas import (
    ProductCreate,
    ProductImageCreate,
    ProductImageRead,
    ProductImageUpdate,
    ProductListResponse,
    ProductOrderUpdate,
    ProductRead,
    ProductUpdate,
)
from app.storage_utils import build_public_asset_url, normalize_storage_path
from app.supabase_storage import SupabaseStorageError, delete_from_supabase

router = APIRouter(prefix='/products', tags=['products'])
settings = get_settings()


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


def _validate_product_relations(db: Session, category_id: int | None, collection_id: int | None) -> None:
    if category_id is not None and not db.get(Category, category_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Categoria no encontrada')
    if collection_id is not None and not db.get(Collection, collection_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Tipo de producto no encontrado')
    if collection_id is not None and category_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='Si se informa tipo de producto, category_id es obligatorio',
        )
    if category_id is not None and collection_id is not None:
        link = db.execute(
            select(CategoryCollection).where(
                CategoryCollection.category_id == category_id,
                CategoryCollection.collection_id == collection_id,
            )
        ).scalar_one_or_none()
        if not link:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail='El tipo de producto no pertenece a la categoria seleccionada',
            )


def _delete_product_asset(path: str) -> None:
    if settings.asset_provider != 'supabase':
        return
    storage_path = normalize_storage_path(path)
    try:
        delete_from_supabase(storage_path)
    except SupabaseStorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f'No se pudo eliminar imagen en storage: {storage_path}',
        ) from exc


@router.post('', response_model=ProductRead, dependencies=[Depends(require_roles(UserRole.admin, UserRole.editor))])
def create_product(
    payload: ProductCreate,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> ProductRead:
    if actor.role == UserRole.editor and payload.status != ContentStatus.draft:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Editor solo puede crear borradores')

    existing = db.execute(select(Product).where(Product.slug == payload.slug)).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail='Slug de producto ya existe')

    _validate_product_relations(db, payload.category_id, payload.collection_id)

    product_data = payload.model_dump()
    if product_data.get('primary_image_path'):
        product_data['primary_image_path'] = normalize_storage_path(product_data['primary_image_path'])
    product = Product(**product_data)
    if product.status == ContentStatus.published:
        product.published_at = datetime.now(timezone.utc)
    db.add(product)
    db.flush()
    log_audit(db, actor, 'product', product.id, 'create', None, serialize_instance(product))
    db.commit()

    statement = select(Product).options(selectinload(Product.images)).where(Product.id == product.id)
    created = db.execute(statement).scalar_one()
    return _product_to_read(created)


@router.get('', response_model=ProductListResponse, dependencies=[Depends(require_roles(UserRole.admin, UserRole.editor))])
def list_products(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status_filter: ContentStatus | None = Query(default=None, alias='status'),
    category_id: int | None = Query(default=None, ge=1),
    collection_id: int | None = Query(default=None, ge=1),
    q: str | None = Query(default=None, min_length=2, max_length=120),
    db: Session = Depends(get_db),
) -> ProductListResponse:
    statement = select(Product).options(selectinload(Product.images))
    if status_filter:
        statement = statement.where(Product.status == status_filter)
    if category_id:
        statement = statement.where(Product.category_id == category_id)
    if collection_id:
        statement = statement.where(Product.collection_id == collection_id)
    if q:
        statement = statement.where(Product.name.ilike(f'%{q}%'))

    statement = statement.order_by(Product.sort_order.asc(), Product.created_at.desc())
    items, meta = paginate_select(db, statement, page, page_size)
    return ProductListResponse(items=[_product_to_read(item) for item in items], meta=meta)


@router.get('/{product_id}', response_model=ProductRead, dependencies=[Depends(require_roles(UserRole.admin, UserRole.editor))])
def get_product(product_id: str, db: Session = Depends(get_db)) -> ProductRead:
    statement = select(Product).options(selectinload(Product.images)).where(Product.id == product_id)
    product = db.execute(statement).scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Producto no encontrado')
    return _product_to_read(product)


@router.patch('/{product_id}', response_model=ProductRead, dependencies=[Depends(require_roles(UserRole.admin, UserRole.editor))])
def update_product(
    product_id: str,
    payload: ProductUpdate,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> ProductRead:
    statement = select(Product).options(selectinload(Product.images)).where(Product.id == product_id)
    product = db.execute(statement).scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Producto no encontrado')

    before = serialize_instance(product)
    data = payload.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='No hay cambios para aplicar')

    if 'status' in data and actor.role != UserRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Solo admin puede cambiar status')

    if 'slug' in data:
        existing = db.execute(select(Product).where(Product.slug == data['slug'], Product.id != product_id)).scalar_one_or_none()
        if existing:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail='Slug de producto ya existe')

    effective_category_id = data['category_id'] if 'category_id' in data else product.category_id
    effective_collection_id = data['collection_id'] if 'collection_id' in data else product.collection_id
    _validate_product_relations(db, effective_category_id, effective_collection_id)

    for field, value in data.items():
        if field == 'primary_image_path' and value is not None:
            value = normalize_storage_path(value)
        setattr(product, field, value)

    if product.status == ContentStatus.published and product.published_at is None:
        product.published_at = datetime.now(timezone.utc)
    if product.status != ContentStatus.published:
        product.published_at = None

    db.flush()
    log_audit(db, actor, 'product', product.id, 'update', before, serialize_instance(product))
    db.commit()
    db.refresh(product)
    return _product_to_read(product)


@router.post('/{product_id}/publish', response_model=ProductRead, dependencies=[Depends(require_roles(UserRole.admin))])
def publish_product(
    product_id: str,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> ProductRead:
    product = db.execute(select(Product).options(selectinload(Product.images)).where(Product.id == product_id)).scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Producto no encontrado')
    before = serialize_instance(product)
    product.status = ContentStatus.published
    product.published_at = datetime.now(timezone.utc)
    db.flush()
    log_audit(db, actor, 'product', product.id, 'publish', before, serialize_instance(product))
    db.commit()
    db.refresh(product)
    return _product_to_read(product)


@router.post('/{product_id}/archive', response_model=ProductRead, dependencies=[Depends(require_roles(UserRole.admin))])
def archive_product(
    product_id: str,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> ProductRead:
    product = db.execute(select(Product).options(selectinload(Product.images)).where(Product.id == product_id)).scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Producto no encontrado')
    before = serialize_instance(product)
    product.status = ContentStatus.archived
    db.flush()
    log_audit(db, actor, 'product', product.id, 'archive', before, serialize_instance(product))
    db.commit()
    db.refresh(product)
    return _product_to_read(product)


@router.post('/{product_id}/order', response_model=ProductRead, dependencies=[Depends(require_roles(UserRole.admin, UserRole.editor))])
def reorder_product(
    product_id: str,
    payload: ProductOrderUpdate,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> ProductRead:
    product = db.execute(select(Product).options(selectinload(Product.images)).where(Product.id == product_id)).scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Producto no encontrado')
    before = serialize_instance(product)
    product.sort_order = payload.sort_order
    db.flush()
    log_audit(db, actor, 'product', product.id, 'reorder', before, serialize_instance(product))
    db.commit()
    db.refresh(product)
    return _product_to_read(product)


@router.delete('/{product_id}', status_code=204, dependencies=[Depends(require_roles(UserRole.admin))])
def delete_product(
    product_id: str,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> None:
    product = db.execute(select(Product).options(selectinload(Product.images)).where(Product.id == product_id)).scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Producto no encontrado')

    # Borra primero los objetos remotos para evitar residuos en el bucket.
    paths_to_delete: list[str] = []
    if product.primary_image_path:
        paths_to_delete.append(product.primary_image_path)
    paths_to_delete.extend([img.url for img in product.images if img.url])
    for path in list(dict.fromkeys(paths_to_delete)):
        _delete_product_asset(path)

    before = serialize_instance(product)
    db.delete(product)
    log_audit(db, actor, 'product', product_id, 'delete', before, None)
    db.commit()


@router.post('/{product_id}/images', response_model=ProductImageRead, dependencies=[Depends(require_roles(UserRole.admin, UserRole.editor))])
def add_product_image(
    product_id: str,
    payload: ProductImageCreate,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> ProductImageRead:
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Producto no encontrado')
    image_data = payload.model_dump()
    image_data['url'] = normalize_storage_path(image_data['url'])
    image = ProductImage(product_id=product_id, **image_data)
    db.add(image)
    db.flush()
    log_audit(db, actor, 'product_image', str(image.id), 'create', None, serialize_instance(image))
    db.commit()
    return ProductImageRead(
        id=image.id,
        url=image.url,
        public_url=build_public_asset_url(image.url),
        alt_text=image.alt_text,
        sort_order=image.sort_order,
    )


@router.patch('/{product_id}/images/{image_id}', response_model=ProductImageRead, dependencies=[Depends(require_roles(UserRole.admin, UserRole.editor))])
def update_product_image(
    product_id: str,
    image_id: int,
    payload: ProductImageUpdate,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> ProductImageRead:
    image = db.execute(
        select(ProductImage).where(ProductImage.id == image_id, ProductImage.product_id == product_id)
    ).scalar_one_or_none()
    if not image:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Imagen no encontrada')

    data = payload.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='No hay cambios para aplicar')

    before = serialize_instance(image)
    for field, value in data.items():
        if field == 'url' and value is not None:
            value = normalize_storage_path(value)
        setattr(image, field, value)
    db.flush()
    log_audit(db, actor, 'product_image', str(image.id), 'update', before, serialize_instance(image))
    db.commit()
    db.refresh(image)
    return ProductImageRead(
        id=image.id,
        url=image.url,
        public_url=build_public_asset_url(image.url),
        alt_text=image.alt_text,
        sort_order=image.sort_order,
    )


@router.delete('/{product_id}/images/{image_id}', status_code=204, dependencies=[Depends(require_roles(UserRole.admin, UserRole.editor))])
def delete_product_image(
    product_id: str,
    image_id: int,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> None:
    image = db.execute(
        select(ProductImage).where(ProductImage.id == image_id, ProductImage.product_id == product_id)
    ).scalar_one_or_none()
    if not image:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Imagen no encontrada')

    if image.url:
        _delete_product_asset(image.url)

    before = serialize_instance(image)
    db.delete(image)
    log_audit(db, actor, 'product_image', str(image.id), 'delete', before, None)
    db.commit()
