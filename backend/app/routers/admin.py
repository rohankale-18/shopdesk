"""Admin endpoints for regenerating data.

Disabled when ADMIN_ENABLED=false. If ADMIN_TOKEN is set, callers must send
it in the X-Admin-Token header. Never expose these to an AI agent's toolset.
"""

import secrets
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import ForbiddenError
from app.db import get_db
from app.schemas import SeedRequest, SeedResult
from app.services.seed import SeedCounts, reset_database, seed_database


def require_admin(
    settings: Annotated[Settings, Depends(get_settings)],
    x_admin_token: Annotated[str | None, Header()] = None,
) -> None:
    if not settings.admin_enabled:
        raise ForbiddenError("Admin endpoints are disabled (ADMIN_ENABLED=false).")
    if settings.admin_token and not (
        x_admin_token and secrets.compare_digest(x_admin_token, settings.admin_token)
    ):
        raise ForbiddenError("Missing or wrong X-Admin-Token header.")


router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])
DB = Annotated[Session, Depends(get_db)]


@router.post("/seed", response_model=SeedResult)
def seed(
    db: DB,
    body: SeedRequest,
    anchor_date: Annotated[
        date | None,
        Query(
            description="Generate dates relative to this day (default: today). "
            "Fix it for fully reproducible timestamps."
        ),
    ] = None,
):
    """Generate deterministic fake data. Same seed -> same data."""
    summary = seed_database(
        db,
        seed=body.seed,
        counts=SeedCounts(
            customers=body.customers,
            products=body.products,
            orders=body.orders,
            tickets=body.tickets,
        ),
        reset=body.reset,
        anchor_date=anchor_date,
    )
    return SeedResult(**summary.__dict__)


@router.post("/reset", status_code=204)
def reset(db: DB):
    """Delete all data and recreate empty tables."""
    reset_database(db)
