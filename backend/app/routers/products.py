from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError
from app.core.pagination import PageDep, apply_sort, paginate
from app.db import get_db
from app.models import Product, ProductCategory
from app.schemas import Page, ProductCreate, ProductOut, ProductUpdate

router = APIRouter(prefix="/api/products", tags=["products"])
DB = Annotated[Session, Depends(get_db)]

SORTABLE = {
    "name": Product.name,
    "price": Product.price_cents,
    "stock": Product.stock,
    "created_at": Product.created_at,
    "id": Product.id,
}


def _get(db: Session, product_id: int) -> Product:
    p = db.get(Product, product_id)
    if not p:
        raise NotFoundError(
            f"Product {product_id} not found.",
            details={"hint": "Search with GET /api/products?q=<name or SKU>."},
        )
    return p


@router.get("", response_model=Page[ProductOut])
def list_products(
    db: DB,
    pg: PageDep,
    q: Annotated[str | None, Query(description="Search name or SKU")] = None,
    category: ProductCategory | None = None,
    in_stock: Annotated[bool | None, Query(description="true = stock > 0, false = stock = 0")] = None,
    active: Annotated[bool | None, Query(description="Filter by is_active")] = None,
    min_price_cents: Annotated[int | None, Query(ge=0)] = None,
    max_price_cents: Annotated[int | None, Query(ge=0)] = None,
    sort: Annotated[str | None, Query(description="name, price, stock, created_at, id")] = None,
):
    """List and search products."""
    stmt = select(Product)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Product.name.ilike(like), Product.sku.ilike(like)))
    if category:
        stmt = stmt.where(Product.category == category)
    if in_stock is not None:
        stmt = stmt.where(Product.stock > 0 if in_stock else Product.stock == 0)
    if active is not None:
        stmt = stmt.where(Product.is_active == active)
    if min_price_cents is not None:
        stmt = stmt.where(Product.price_cents >= min_price_cents)
    if max_price_cents is not None:
        stmt = stmt.where(Product.price_cents <= max_price_cents)
    stmt = apply_sort(stmt, sort, SORTABLE, "name")
    return paginate(db, stmt, pg)


@router.post("", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
def create_product(db: DB, body: ProductCreate):
    """Create a product. SKUs must be unique (uppercase letters, digits, dashes)."""
    if db.scalar(select(Product.id).where(Product.sku == body.sku)):
        raise ConflictError(f"SKU {body.sku} already exists.")
    p = Product(**body.model_dump())
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


@router.get("/{product_id}", response_model=ProductOut)
def get_product(db: DB, product_id: int):
    return _get(db, product_id)


@router.patch("/{product_id}", response_model=ProductOut)
def update_product(db: DB, product_id: int, body: ProductUpdate):
    """Update a product. Price changes don't affect existing orders."""
    p = _get(db, product_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(p, k, v)
    db.commit()
    db.refresh(p)
    return p


@router.delete("/{product_id}", response_model=ProductOut)
def archive_product(db: DB, product_id: int):
    """Archive a product (sets is_active=false). Products are never hard-deleted
    because past orders reference them."""
    p = _get(db, product_id)
    p.is_active = False
    db.commit()
    db.refresh(p)
    return p
