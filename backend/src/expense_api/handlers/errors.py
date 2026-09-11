"""Global exception handlers.

Registered on the app inside create_app() via add_exception_handler, rather than by importing
the app object here for its decorator side effect.

The sanitisation rules matter more than they look:

- A 5xx HTTPException carries a message someone wrote for themselves, not for a caller. Log it
  and replace the body.
- A RequestValidationError from Pydantic v2 includes an `input` field echoing the raw submitted
  value. On a login or an upload that is a credential or a document body in an error response.
  Strip the error down to loc and msg.
- The catch-all exists so an unhandled exception can never return a traceback.
"""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

GENERIC_500 = "Internal Server Error. Please try again later."


async def http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    if exc.status_code >= 500:
        logger.error("Server error on %s %s: %s", request.method, request.url.path, exc.detail)
        return JSONResponse(status_code=exc.status_code, content={"detail": GENERIC_500})

    logger.warning(
        "Client error %s on %s %s: %s",
        exc.status_code,
        request.method,
        request.url.path,
        exc.detail,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers=getattr(exc, "headers", None),
    )


async def validation_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    # Only loc and msg. Dropping `input`, `url`, `type` and `ctx` is the point of this handler.
    sanitised: list[dict[str, Any]] = [
        {"loc": err.get("loc", []), "msg": err.get("msg", "")} for err in exc.errors()
    ]
    logger.warning(
        "Validation error on %s %s: %s fields", request.method, request.url.path, len(sanitised)
    )
    return JSONResponse(status_code=422, content={"detail": sanitised})


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": GENERIC_500})


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
