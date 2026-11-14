import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute
from sqlalchemy import text

from app.core.config import get_settings
from app.core.errors import register_exception_handlers
from app.db import SessionLocal, engine, init_db
from app.routers import admin, ai, chat, customers, orders, products, stats, tickets
from app.services.seed import is_empty, seed_database

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("shopdesk")


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    init_db()
    if settings.auto_seed:
        with SessionLocal() as db:
            if is_empty(db):
                summary = seed_database(db, seed=settings.default_seed)
                logger.info("Seeded empty database with seed=%s", summary.seed)
    yield


def _operation_id(route: APIRoute) -> str:
    # Clean operation IDs (e.g. "list_orders") instead of FastAPI's long defaults.
    # Generated clients and agent tool names come out readable this way.
    return route.name


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description=(
            "Customer-support backend for a small online store: customers, products, "
            "orders, refunds and support tickets. Money is always in integer cents (USD)."
        ),
        lifespan=lifespan,
        generate_unique_id_function=_operation_id,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        start = time.perf_counter()
        response = await call_next(request)
        ms = (time.perf_counter() - start) * 1000
        response.headers["X-Request-ID"] = request_id
        if request.url.path.startswith("/api"):
            logger.info(
                "%s %s -> %s (%.1fms) rid=%s",
                request.method,
                request.url.path,
                response.status_code,
                ms,
                request_id,
            )
        return response

    register_exception_handlers(app)

    @app.get("/api/health", tags=["meta"])
    def health():
        """Liveness + database check."""
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok", "environment": settings.environment}

    for r in (customers, products, orders, tickets, stats, ai, chat, admin):
        app.include_router(r.router)

    return app


app = create_app()
