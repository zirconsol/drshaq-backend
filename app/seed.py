from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Category, CategoryCollection, Collection

DEFAULT_DROP_CATEGORIES = [
    ('Montana', 'montana'),
    ('Ye Apparel', 'ye-apparel'),
    ('Camperas', 'camperas'),
]

DEFAULT_PRODUCT_TYPES = [
    ('Remeras', 'remeras'),
    ('Pantalones', 'pantalones'),
    ('Camperas', 'camperas'),
]

DEFAULT_CATEGORY_TYPE_ASSIGNMENTS: dict[str, list[str]] = {
    'montana': ['remeras', 'pantalones'],
    'ye-apparel': ['remeras', 'pantalones'],
    'camperas': ['camperas'],
}


def ensure_default_drop_taxonomy(db: Session) -> None:
    categories_by_slug: dict[str, Category] = {}
    for name, slug in DEFAULT_DROP_CATEGORIES:
        category = db.execute(select(Category).where(Category.slug == slug)).scalar_one_or_none()
        if not category:
            category = Category(name=name, slug=slug)
            db.add(category)
            db.flush()
        categories_by_slug[slug] = category

    product_types_by_slug: dict[str, Collection] = {}
    for name, slug in DEFAULT_PRODUCT_TYPES:
        product_type = db.execute(select(Collection).where(Collection.slug == slug)).scalar_one_or_none()
        if not product_type:
            product_type = Collection(name=name, slug=slug)
            db.add(product_type)
            db.flush()
        product_types_by_slug[slug] = product_type

    for category_slug, type_slugs in DEFAULT_CATEGORY_TYPE_ASSIGNMENTS.items():
        category = categories_by_slug.get(category_slug)
        if not category:
            continue
        for type_slug in type_slugs:
            product_type = product_types_by_slug.get(type_slug)
            if not product_type:
                continue
            exists = db.execute(
                select(CategoryCollection).where(
                    CategoryCollection.category_id == category.id,
                    CategoryCollection.collection_id == product_type.id,
                )
            ).scalar_one_or_none()
            if not exists:
                db.add(CategoryCollection(category_id=category.id, collection_id=product_type.id))

    db.commit()
