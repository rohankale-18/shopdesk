from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, Query
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError


@dataclass
class PageParams:
    page: int
    page_size: int

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


def page_params(
    page: Annotated[int, Query(ge=1, description="1-based page number")] = 1,
    page_size: Annotated[int, Query(ge=1, le=100, description="Items per page (max 100)")] = 20,
) -> PageParams:
    return PageParams(page=page, page_size=page_size)


PageDep = Annotated[PageParams, Depends(page_params)]


def paginate(db: Session, stmt: Select, params: PageParams) -> dict[str, Any]:
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    items = db.scalars(stmt.limit(params.page_size).offset(params.offset)).all()
    return {"items": items, "total": total, "page": params.page, "page_size": params.page_size}


def apply_sort(stmt: Select, sort: str | None, allowed: dict[str, Any], default: str) -> Select:
    """`sort=field` ascending, `sort=-field` descending. Only whitelisted fields."""
    key = sort or default
    desc = key.startswith("-")
    name = key.lstrip("-")
    if name not in allowed:
        raise AppError(
            f"Can't sort by '{name}'.",
            details={"allowed": sorted(allowed) + sorted(f"-{k}" for k in allowed)},
        )
    col = allowed[name]
    return stmt.order_by(col.desc() if desc else col.asc())
