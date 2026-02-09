from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.audit import log_audit, serialize_instance
from app.database import get_db
from app.dependencies import get_current_user, require_roles
from app.models import Catalog, CatalogImage, CatalogProduct, ContentStatus, Product, User, UserRole
from app.pagination import paginate_select
from app.schemas import (
    CatalogCreate,
    CatalogImageCreate,
    CatalogImageRead,
    CatalogImageUpdate,
    CatalogListResponse,
    CatalogOrderUpdate,
    CatalogProductAttach,
    CatalogProductRead,
    CatalogProductReorder,
    CatalogRead,
    CatalogUpdate,
)

router = APIRouter(prefix='/catalogs', tags=['catalogs'])


def _catalog_to_read(item: Catalog) -> CatalogRead:
    images = [
        CatalogImageRead(id=img.id, url=img.url, alt_text=img.alt_text, sort_order=img.sort_order)
        for img in sorted(item.images, key=lambda i: i.sort_order)
    ]
    products = [
        CatalogProductRead(product_id=link.product_id, sort_order=link.sort_order)
        for link in sorted(item.product_links, key=lambda i: i.sort_order)
    ]
    return CatalogRead(
        id=item.id,
        name=item.name,
        slug=item.slug,
        description=item.description,
        status=item.status,
        sort_order=item.sort_order,
        published_at=item.published_at,
        created_at=item.created_at,
        updated_at=item.updated_at,
        images=images,
        products=products,
    )


@router.post('', response_model=CatalogRead, dependencies=[Depends(require_roles(UserRole.admin, UserRole.editor))])
def create_catalog(
    payload: CatalogCreate,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> CatalogRead:
    if actor.role == UserRole.editor and payload.status != ContentStatus.draft:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Editor solo puede crear borradores')

    existing = db.execute(select(Catalog).where(Catalog.slug == payload.slug)).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail='Slug de catalogo ya existe')

    catalog = Catalog(**payload.model_dump())
    if catalog.status == ContentStatus.published:
        catalog.published_at = datetime.now(timezone.utc)
    db.add(catalog)
    db.flush()
    log_audit(db, actor, 'catalog', catalog.id, 'create', None, serialize_instance(catalog))
    db.commit()

    created = db.execute(
        select(Catalog)
        .options(selectinload(Catalog.images), selectinload(Catalog.product_links))
        .where(Catalog.id == catalog.id)
    ).scalar_one()
    return _catalog_to_read(created)


@router.get('', response_model=CatalogListResponse, dependencies=[Depends(require_roles(UserRole.admin, UserRole.editor))])
def list_catalogs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status_filter: ContentStatus | None = Query(default=None, alias='status'),
    q: str | None = Query(default=None, min_length=2, max_length=120),
    db: Session = Depends(get_db),
) -> CatalogListResponse:
    statement = select(Catalog).options(selectinload(Catalog.images), selectinload(Catalog.product_links))
    if status_filter:
        statement = statement.where(Catalog.status == status_filter)
    if q:
        statement = statement.where(Catalog.name.ilike(f'%{q}%'))
    statement = statement.order_by(Catalog.sort_order.asc(), Catalog.created_at.desc())

    items, meta = paginate_select(db, statement, page, page_size)
    return CatalogListResponse(items=[_catalog_to_read(item) for item in items], meta=meta)


@router.get('/{catalog_id}', response_model=CatalogRead, dependencies=[Depends(require_roles(UserRole.admin, UserRole.editor))])
def get_catalog(catalog_id: str, db: Session = Depends(get_db)) -> CatalogRead:
    catalog = db.execute(
        select(Catalog)
        .options(selectinload(Catalog.images), selectinload(Catalog.product_links))
        .where(Catalog.id == catalog_id)
    ).scalar_one_or_none()
    if not catalog:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Catalogo no encontrado')
    return _catalog_to_read(catalog)


@router.patch('/{catalog_id}', response_model=CatalogRead, dependencies=[Depends(require_roles(UserRole.admin, UserRole.editor))])
def update_catalog(
    catalog_id: str,
    payload: CatalogUpdate,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> CatalogRead:
    catalog = db.execute(
        select(Catalog)
        .options(selectinload(Catalog.images), selectinload(Catalog.product_links))
        .where(Catalog.id == catalog_id)
    ).scalar_one_or_none()
    if not catalog:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Catalogo no encontrado')

    data = payload.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='No hay cambios para aplicar')

    if 'status' in data and actor.role != UserRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Solo admin puede cambiar status')

    if 'slug' in data:
        existing = db.execute(select(Catalog).where(Catalog.slug == data['slug'], Catalog.id != catalog_id)).scalar_one_or_none()
        if existing:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail='Slug de catalogo ya existe')

    before = serialize_instance(catalog)
    for field, value in data.items():
        setattr(catalog, field, value)

    if catalog.status == ContentStatus.published and catalog.published_at is None:
        catalog.published_at = datetime.now(timezone.utc)
    if catalog.status != ContentStatus.published:
        catalog.published_at = None

    db.flush()
    log_audit(db, actor, 'catalog', catalog.id, 'update', before, serialize_instance(catalog))
    db.commit()
    db.refresh(catalog)
    return _catalog_to_read(catalog)


@router.post('/{catalog_id}/publish', response_model=CatalogRead, dependencies=[Depends(require_roles(UserRole.admin))])
def publish_catalog(
    catalog_id: str,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> CatalogRead:
    catalog = db.execute(
        select(Catalog)
        .options(selectinload(Catalog.images), selectinload(Catalog.product_links))
        .where(Catalog.id == catalog_id)
    ).scalar_one_or_none()
    if not catalog:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Catalogo no encontrado')

    before = serialize_instance(catalog)
    catalog.status = ContentStatus.published
    catalog.published_at = datetime.now(timezone.utc)
    db.flush()
    log_audit(db, actor, 'catalog', catalog.id, 'publish', before, serialize_instance(catalog))
    db.commit()
    db.refresh(catalog)
    return _catalog_to_read(catalog)


@router.post('/{catalog_id}/archive', response_model=CatalogRead, dependencies=[Depends(require_roles(UserRole.admin))])
def archive_catalog(
    catalog_id: str,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> CatalogRead:
    catalog = db.execute(
        select(Catalog)
        .options(selectinload(Catalog.images), selectinload(Catalog.product_links))
        .where(Catalog.id == catalog_id)
    ).scalar_one_or_none()
    if not catalog:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Catalogo no encontrado')

    before = serialize_instance(catalog)
    catalog.status = ContentStatus.archived
    db.flush()
    log_audit(db, actor, 'catalog', catalog.id, 'archive', before, serialize_instance(catalog))
    db.commit()
    db.refresh(catalog)
    return _catalog_to_read(catalog)


@router.post('/{catalog_id}/order', response_model=CatalogRead, dependencies=[Depends(require_roles(UserRole.admin, UserRole.editor))])
def reorder_catalog(
    catalog_id: str,
    payload: CatalogOrderUpdate,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> CatalogRead:
    catalog = db.execute(
        select(Catalog)
        .options(selectinload(Catalog.images), selectinload(Catalog.product_links))
        .where(Catalog.id == catalog_id)
    ).scalar_one_or_none()
    if not catalog:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Catalogo no encontrado')

    before = serialize_instance(catalog)
    catalog.sort_order = payload.sort_order
    db.flush()
    log_audit(db, actor, 'catalog', catalog.id, 'reorder', before, serialize_instance(catalog))
    db.commit()
    db.refresh(catalog)
    return _catalog_to_read(catalog)


@router.delete('/{catalog_id}', status_code=204, dependencies=[Depends(require_roles(UserRole.admin))])
def delete_catalog(
    catalog_id: str,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> None:
    catalog = db.get(Catalog, catalog_id)
    if not catalog:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Catalogo no encontrado')

    before = serialize_instance(catalog)
    db.delete(catalog)
    log_audit(db, actor, 'catalog', catalog_id, 'delete', before, None)
    db.commit()


@router.post('/{catalog_id}/products', response_model=CatalogRead, dependencies=[Depends(require_roles(UserRole.admin, UserRole.editor))])
def attach_product_to_catalog(
    catalog_id: str,
    payload: CatalogProductAttach,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> CatalogRead:
    catalog = db.execute(
        select(Catalog)
        .options(selectinload(Catalog.images), selectinload(Catalog.product_links))
        .where(Catalog.id == catalog_id)
    ).scalar_one_or_none()
    if not catalog:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Catalogo no encontrado')

    if not db.get(Product, payload.product_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Producto no encontrado')

    existing = db.execute(
        select(CatalogProduct).where(
            CatalogProduct.catalog_id == catalog_id,
            CatalogProduct.product_id == payload.product_id,
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail='Producto ya existe en catalogo')

    link = CatalogProduct(catalog_id=catalog_id, product_id=payload.product_id, sort_order=payload.sort_order)
    db.add(link)
    db.flush()
    log_audit(db, actor, 'catalog_product', f'{catalog_id}:{payload.product_id}', 'attach', None, serialize_instance(link))
    db.commit()
    db.refresh(catalog)
    return _catalog_to_read(catalog)


@router.patch(
    '/{catalog_id}/products/{product_id}',
    response_model=CatalogRead,
    dependencies=[Depends(require_roles(UserRole.admin, UserRole.editor))],
)
def reorder_product_inside_catalog(
    catalog_id: str,
    product_id: str,
    payload: CatalogProductReorder,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> CatalogRead:
    link = db.execute(
        select(CatalogProduct).where(CatalogProduct.catalog_id == catalog_id, CatalogProduct.product_id == product_id)
    ).scalar_one_or_none()
    if not link:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Relacion catalogo-producto no encontrada')

    before = serialize_instance(link)
    link.sort_order = payload.sort_order
    db.flush()
    log_audit(db, actor, 'catalog_product', f'{catalog_id}:{product_id}', 'reorder', before, serialize_instance(link))
    db.commit()

    catalog = db.execute(
        select(Catalog)
        .options(selectinload(Catalog.images), selectinload(Catalog.product_links))
        .where(Catalog.id == catalog_id)
    ).scalar_one()
    return _catalog_to_read(catalog)


@router.delete('/{catalog_id}/products/{product_id}', response_model=CatalogRead, dependencies=[Depends(require_roles(UserRole.admin, UserRole.editor))])
def detach_product_from_catalog(
    catalog_id: str,
    product_id: str,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> CatalogRead:
    link = db.execute(
        select(CatalogProduct).where(CatalogProduct.catalog_id == catalog_id, CatalogProduct.product_id == product_id)
    ).scalar_one_or_none()
    if not link:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Relacion catalogo-producto no encontrada')

    before = serialize_instance(link)
    db.delete(link)
    log_audit(db, actor, 'catalog_product', f'{catalog_id}:{product_id}', 'detach', before, None)
    db.commit()

    catalog = db.execute(
        select(Catalog)
        .options(selectinload(Catalog.images), selectinload(Catalog.product_links))
        .where(Catalog.id == catalog_id)
    ).scalar_one()
    return _catalog_to_read(catalog)


@router.post('/{catalog_id}/images', response_model=CatalogImageRead, dependencies=[Depends(require_roles(UserRole.admin, UserRole.editor))])
def add_catalog_image(
    catalog_id: str,
    payload: CatalogImageCreate,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> CatalogImageRead:
    catalog = db.get(Catalog, catalog_id)
    if not catalog:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Catalogo no encontrado')

    image = CatalogImage(catalog_id=catalog_id, **payload.model_dump())
    db.add(image)
    db.flush()
    log_audit(db, actor, 'catalog_image', str(image.id), 'create', None, serialize_instance(image))
    db.commit()
    return CatalogImageRead(id=image.id, url=image.url, alt_text=image.alt_text, sort_order=image.sort_order)


@router.patch('/{catalog_id}/images/{image_id}', response_model=CatalogImageRead, dependencies=[Depends(require_roles(UserRole.admin, UserRole.editor))])
def update_catalog_image(
    catalog_id: str,
    image_id: int,
    payload: CatalogImageUpdate,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> CatalogImageRead:
    image = db.execute(
        select(CatalogImage).where(CatalogImage.id == image_id, CatalogImage.catalog_id == catalog_id)
    ).scalar_one_or_none()
    if not image:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Imagen no encontrada')

    data = payload.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='No hay cambios para aplicar')

    before = serialize_instance(image)
    for field, value in data.items():
        setattr(image, field, value)
    db.flush()
    log_audit(db, actor, 'catalog_image', str(image.id), 'update', before, serialize_instance(image))
    db.commit()
    db.refresh(image)
    return CatalogImageRead(id=image.id, url=image.url, alt_text=image.alt_text, sort_order=image.sort_order)


@router.delete('/{catalog_id}/images/{image_id}', status_code=204, dependencies=[Depends(require_roles(UserRole.admin, UserRole.editor))])
def delete_catalog_image(
    catalog_id: str,
    image_id: int,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> None:
    image = db.execute(
        select(CatalogImage).where(CatalogImage.id == image_id, CatalogImage.catalog_id == catalog_id)
    ).scalar_one_or_none()
    if not image:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Imagen no encontrada')

    before = serialize_instance(image)
    db.delete(image)
    log_audit(db, actor, 'catalog_image', str(image.id), 'delete', before, None)
    db.commit()
