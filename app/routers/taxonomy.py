from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import log_audit, serialize_instance
from app.database import get_db
from app.dependencies import get_current_user, require_roles
from app.models import Category, CategoryCollection, Collection, User, UserRole
from app.pagination import paginate_select
from app.schemas import (
    CategoryCreate,
    CategoryListResponse,
    CategoryProductTypeListResponse,
    CategoryRead,
    CategoryUpdate,
    CollectionCreate,
    CollectionListResponse,
    CollectionRead,
    CollectionUpdate,
)

router = APIRouter(prefix='/taxonomy', tags=['taxonomy'])


def _category_to_read(item: Category) -> CategoryRead:
    return CategoryRead(id=item.id, name=item.name, slug=item.slug)


def _collection_to_read(item: Collection) -> CollectionRead:
    return CollectionRead(id=item.id, name=item.name, slug=item.slug)


@router.post('/categories', response_model=CategoryRead, dependencies=[Depends(require_roles(UserRole.admin, UserRole.editor))])
def create_category(
    payload: CategoryCreate,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> CategoryRead:
    existing = db.execute(select(Category).where((Category.slug == payload.slug) | (Category.name == payload.name))).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail='Categoria duplicada por nombre o slug')
    category = Category(name=payload.name, slug=payload.slug)
    db.add(category)
    db.flush()
    log_audit(db, actor, 'category', str(category.id), 'create', None, serialize_instance(category))
    db.commit()
    db.refresh(category)
    return _category_to_read(category)


@router.get('/categories', response_model=CategoryListResponse, dependencies=[Depends(require_roles(UserRole.admin, UserRole.editor))])
def list_categories(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> CategoryListResponse:
    items, meta = paginate_select(db, select(Category).order_by(Category.name), page, page_size)
    return CategoryListResponse(items=[_category_to_read(item) for item in items], meta=meta)


@router.patch('/categories/{category_id}', response_model=CategoryRead, dependencies=[Depends(require_roles(UserRole.admin, UserRole.editor))])
def update_category(
    category_id: int,
    payload: CategoryUpdate,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> CategoryRead:
    category = db.get(Category, category_id)
    if not category:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Categoria no encontrada')
    before = serialize_instance(category)
    data = payload.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='No hay cambios para aplicar')

    if 'slug' in data:
        existing = db.execute(
            select(Category).where(Category.slug == data['slug'], Category.id != category_id)
        ).scalar_one_or_none()
        if existing:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail='Slug ya existe')
    if 'name' in data:
        existing = db.execute(
            select(Category).where(Category.name == data['name'], Category.id != category_id)
        ).scalar_one_or_none()
        if existing:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail='Nombre ya existe')

    for field, value in data.items():
        setattr(category, field, value)

    db.flush()
    log_audit(db, actor, 'category', str(category.id), 'update', before, serialize_instance(category))
    db.commit()
    db.refresh(category)
    return _category_to_read(category)


@router.delete('/categories/{category_id}', status_code=204, dependencies=[Depends(require_roles(UserRole.admin))])
def delete_category(
    category_id: int,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> None:
    category = db.get(Category, category_id)
    if not category:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Categoria no encontrada')
    before = serialize_instance(category)
    db.delete(category)
    log_audit(db, actor, 'category', str(category_id), 'delete', before, None)
    db.commit()


@router.post('/collections', response_model=CollectionRead, dependencies=[Depends(require_roles(UserRole.admin, UserRole.editor))])
@router.post('/product-types', response_model=CollectionRead, dependencies=[Depends(require_roles(UserRole.admin, UserRole.editor))])
def create_collection(
    payload: CollectionCreate,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> CollectionRead:
    existing = db.execute(
        select(Collection).where((Collection.slug == payload.slug) | (Collection.name == payload.name))
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail='Tipo de producto duplicado por nombre o slug')
    collection = Collection(name=payload.name, slug=payload.slug)
    db.add(collection)
    db.flush()
    log_audit(db, actor, 'collection', str(collection.id), 'create', None, serialize_instance(collection))
    db.commit()
    db.refresh(collection)
    return _collection_to_read(collection)


@router.get('/collections', response_model=CollectionListResponse, dependencies=[Depends(require_roles(UserRole.admin, UserRole.editor))])
@router.get('/product-types', response_model=CollectionListResponse, dependencies=[Depends(require_roles(UserRole.admin, UserRole.editor))])
def list_collections(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    category_id: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
) -> CollectionListResponse:
    statement = select(Collection)
    if category_id is not None:
        if not db.get(Category, category_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Categoria no encontrada')
        statement = (
            select(Collection)
            .join(CategoryCollection, CategoryCollection.collection_id == Collection.id)
            .where(CategoryCollection.category_id == category_id)
        )

    statement = statement.order_by(Collection.name)
    items, meta = paginate_select(db, statement, page, page_size)
    return CollectionListResponse(items=[_collection_to_read(item) for item in items], meta=meta)


@router.get(
    '/categories/{category_id}/product-types',
    response_model=CategoryProductTypeListResponse,
    dependencies=[Depends(require_roles(UserRole.admin, UserRole.editor))],
)
def list_category_product_types(
    category_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> CategoryProductTypeListResponse:
    if not db.get(Category, category_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Categoria no encontrada')

    statement = (
        select(Collection)
        .join(CategoryCollection, CategoryCollection.collection_id == Collection.id)
        .where(CategoryCollection.category_id == category_id)
        .order_by(Collection.name)
    )
    items, meta = paginate_select(db, statement, page, page_size)
    return CategoryProductTypeListResponse(
        category_id=category_id,
        items=[_collection_to_read(item) for item in items],
        meta=meta,
    )


@router.patch('/collections/{collection_id}', response_model=CollectionRead, dependencies=[Depends(require_roles(UserRole.admin, UserRole.editor))])
@router.patch('/product-types/{collection_id}', response_model=CollectionRead, dependencies=[Depends(require_roles(UserRole.admin, UserRole.editor))])
def update_collection(
    collection_id: int,
    payload: CollectionUpdate,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> CollectionRead:
    collection = db.get(Collection, collection_id)
    if not collection:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Tipo de producto no encontrado')
    before = serialize_instance(collection)
    data = payload.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='No hay cambios para aplicar')

    if 'slug' in data:
        existing = db.execute(
            select(Collection).where(Collection.slug == data['slug'], Collection.id != collection_id)
        ).scalar_one_or_none()
        if existing:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail='Slug ya existe')
    if 'name' in data:
        existing = db.execute(
            select(Collection).where(Collection.name == data['name'], Collection.id != collection_id)
        ).scalar_one_or_none()
        if existing:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail='Nombre ya existe')

    for field, value in data.items():
        setattr(collection, field, value)

    db.flush()
    log_audit(db, actor, 'collection', str(collection.id), 'update', before, serialize_instance(collection))
    db.commit()
    db.refresh(collection)
    return _collection_to_read(collection)


@router.post(
    '/categories/{category_id}/product-types/{collection_id}',
    status_code=204,
    dependencies=[Depends(require_roles(UserRole.admin, UserRole.editor))],
)
def attach_product_type_to_category(
    category_id: int,
    collection_id: int,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> None:
    category = db.get(Category, category_id)
    if not category:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Categoria no encontrada')
    collection = db.get(Collection, collection_id)
    if not collection:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Tipo de producto no encontrado')

    existing = db.execute(
        select(CategoryCollection).where(
            CategoryCollection.category_id == category_id,
            CategoryCollection.collection_id == collection_id,
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail='Tipo de producto ya asignado a la categoria')

    link = CategoryCollection(category_id=category_id, collection_id=collection_id)
    db.add(link)
    db.flush()
    log_audit(
        db,
        actor,
        'category_product_type',
        f'{category_id}:{collection_id}',
        'attach',
        None,
        serialize_instance(link),
    )
    db.commit()


@router.delete(
    '/categories/{category_id}/product-types/{collection_id}',
    status_code=204,
    dependencies=[Depends(require_roles(UserRole.admin, UserRole.editor))],
)
def detach_product_type_from_category(
    category_id: int,
    collection_id: int,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> None:
    link = db.execute(
        select(CategoryCollection).where(
            CategoryCollection.category_id == category_id,
            CategoryCollection.collection_id == collection_id,
        )
    ).scalar_one_or_none()
    if not link:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Relacion categoria-tipo no encontrada')

    before = serialize_instance(link)
    db.delete(link)
    log_audit(db, actor, 'category_product_type', f'{category_id}:{collection_id}', 'detach', before, None)
    db.commit()


@router.delete('/collections/{collection_id}', status_code=204, dependencies=[Depends(require_roles(UserRole.admin))])
@router.delete('/product-types/{collection_id}', status_code=204, dependencies=[Depends(require_roles(UserRole.admin))])
def delete_collection(
    collection_id: int,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> None:
    collection = db.get(Collection, collection_id)
    if not collection:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Tipo de producto no encontrado')
    before = serialize_instance(collection)
    db.delete(collection)
    log_audit(db, actor, 'collection', str(collection_id), 'delete', before, None)
    db.commit()
