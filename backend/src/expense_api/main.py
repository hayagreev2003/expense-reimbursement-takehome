"""Application factory.

Domain routers are included here and only here, each with its prefix applied at include time,
so the whole URL map is readable in one place. Routers themselves declare no prefix.
"""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from expense_api.approvals.router import router as approvals_router
from expense_api.claims.router import router as claims_router
from expense_api.config.logging_config import setup_logging
from expense_api.config.settings import settings
from expense_api.handlers.errors import register_exception_handlers
from expense_api.identity.router import router as identity_router
from expense_api.notifications.router import router as notifications_router

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    setup_logging(settings.log_level)

    app = FastAPI(
        title="Nortex Travel Expense Settlement",
        version="0.1.0",
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

    @app.get("/api/v1/health", tags=["meta"])
    async def health() -> dict[str, str]:
        return {"status": "ok", "environment": settings.app_env}

    logger.info("Application started in %s mode", settings.app_env)
    return app


app = create_app()
