import os
import tempfile
from datetime import date
from pathlib import Path

import pytest

# Point the app at a throwaway database before anything imports it.
_tmp = Path(tempfile.mkdtemp()) / "test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}"
os.environ["AUTO_SEED"] = "false"
os.environ["ADMIN_TOKEN"] = ""
os.environ["GROQ_API_KEY"] = ""  # never call the real provider from tests

from fastapi.testclient import TestClient  # noqa: E402

from app.db import SessionLocal, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.services.seed import SeedCounts, seed_database  # noqa: E402

ANCHOR = date(2026, 6, 1)


@pytest.fixture()
def client():
    """Fresh, deterministically seeded database for every test."""
    init_db()
    with SessionLocal() as db:
        seed_database(
            db, seed=1, counts=SeedCounts(customers=15, products=12, orders=40, tickets=10),
            anchor_date=ANCHOR,
        )
    with TestClient(app) as c:
        yield c
