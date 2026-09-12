"""The demo reset route. The router declares no prefix; create_app() mounts it."""

from __future__ import annotations

import hmac
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from expense_api.config.settings import settings
from expense_api.db.database import get_async_session
from expense_api.demo.schemas import ResetDemoResponse
from expense_api.demo.service import reset_demo

logger = logging.getLogger(__name__)

router = APIRouter()

Session = Annotated[AsyncSession, Depends(get_async_session)]


def _authorise(token: str | None) -> None:
    """404 when disabled, 403 on a bad token.

    404 rather than 403 for the disabled case because the *existence* of a route that deletes
    every claim is itself information; a 403 confirms it is there and only the credential is
    missing. Once the feature is on, the route is no secret and a wrong token deserves a 403.
    """
    if not settings.demo_reset_enabled:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Not found."})

    expected = settings.demo_reset_token
    if expected is None:
        return

    # compare_digest, not ==: a plain comparison returns as soon as two bytes differ, and the
    # time it took is a hint about how much of the token was right.
    if token is None or not hmac.compare_digest(token, expected):
        raise HTTPException(
            status_code=403,
            detail={"code": "bad_demo_token", "message": "That reset token is not valid."},
        )


@router.post("/demo/reset", response_model=ResetDemoResponse, tags=["demo"])
async def reset(
    session: Session,
    x_demo_token: Annotated[str | None, Header(alias="X-Demo-Token")] = None,
) -> ResetDemoResponse:
    """Return the demo to its starting state: the anchor trip, its inbox, nothing claimed yet.

    Deliberately not behind `CurrentUser`. The reset deletes claims for every profile, so there
    is no caller it could be scoped to, and the profile being reset is frequently the one whose
    session is mid-flow. The token is the access control.
    """
    _authorise(x_demo_token)
    logger.warning("Demo reset requested")
    return await reset_demo(session)
