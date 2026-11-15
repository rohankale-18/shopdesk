from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import StatsOverview
from app.services.stats import store_overview

router = APIRouter(prefix="/api/stats", tags=["stats"])
DB = Annotated[Session, Depends(get_db)]


@router.get("/overview", response_model=StatsOverview)
def overview(db: DB):
    """Headline numbers for the dashboard."""
    return store_overview(db)
