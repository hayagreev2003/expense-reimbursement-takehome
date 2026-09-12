"""Application factory.

Domain routers are included here and only here, each with its prefix applied at include time,
so the whole URL map is readable in one place. Routers themselves declare no prefix.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from expense_api.approvals.router import router as approvals_router
from expense_api.claims.router import router as claims_router
from expense_api.config.logging_config import setup_logging
from expense_api.config.settings import settings
from expense_api.demo.router import router as demo_router
from expense_api.evidence.extractors.ocr import warm_cache
from expense_api.handlers.errors import register_exception_handlers
from expense_api.identity.router import router as identity_router
from expense_api.notifications.router import router as notifications_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Read the receipt images once before the first request can ask for them.

    Not a migration - those stay in the entrypoint, because an app that migrates on boot races
    itself as soon as it has more than one worker. This is a read-only cache warm, and it has to
    happen per process, which is exactly what a lifespan is for.

    Without it the first request to a draft claim runs tesseract on the event loop. On a small
    shared-CPU instance that blocks long enough for the health check to fail, the process is
    restarted, the cache is lost, and the next request starts over - so the service never serves
    a claim at all.
    """
    read, seconds = warm_cache(settings.pack_dir / "receipts")
    if read:
        logger.info("Pre-read %d receipt image(s) in %.1fs", read, seconds)
    yield


def create_app() -> FastAPI:
    setup_logging(settings.log_level)

    app = FastAPI(
        title="Nortex Travel Expense Settlement",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
    )

    # add_middleware prepends, so anything added before CORSMiddleware ends up wrapped by it.
    # Upload guards belong before this line so their 413/429 responses still carry CORS headers.
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=settings.cors_allow_origin_regex,
        allow_credentials=True,
        allow_methods=["*"],
        # An explicit list, because the default is the four CORS-safelisted request headers and
        # nothing else. X-Emp-Code is not one of them, so without this every browser request
        # fails its preflight with "does not have HTTP ok status" - a 400 from the middleware
        # that never reaches a route, and looks from the client like the API is down.
        allow_headers=["Content-Type", "X-Emp-Code"],
        # An explicit list, never ["*"]: browsers ignore a wildcard Access-Control-Expose-Headers
        # on credentialed requests, and the header reads as null in client JS.
        expose_headers=["Content-Disposition"],
    )

    register_exception_handlers(app)

    # Prefixes are applied here and only here, so the whole URL map reads in one place.
    app.include_router(identity_router, prefix="/api/v1")
    app.include_router(claims_router, prefix="/api/v1")
    app.include_router(approvals_router, prefix="/api/v1")
    app.include_router(notifications_router, prefix="/api/v1")
    # Always mounted, never always usable: the route itself answers 404 unless
    # DEMO_RESET_ENABLED is on. Mounting conditionally would make the generated OpenAPI - and
    # therefore the frontend's generated client - differ between environments.
    app.include_router(demo_router, prefix="/api/v1")

    @app.get("/api/v1/health", tags=["meta"])
    async def health() -> dict[str, str]:
        return {"status": "ok", "environment": settings.app_env}

    logger.info("Application started in %s mode", settings.app_env)
    return app


app = create_app()
