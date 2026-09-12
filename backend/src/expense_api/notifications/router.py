"""The signed-in person's inbox. The router declares no prefix; create_app() mounts it."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from expense_api.db.database import get_async_session
from expense_api.db.models import Notification
from expense_api.identity.deps import CurrentUser
from expense_api.notifications.schemas import (
    MarkReadResponse,
    NotificationListResponse,
    NotificationResponse,
)
from expense_api.notifications.service import unread_count

router = APIRouter()

Session = Annotated[AsyncSession, Depends(get_async_session)]


@router.get("/notifications", response_model=NotificationListResponse, tags=["notifications"])
async def list_notifications(
    session: Session,
    user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> NotificationListResponse:
    rows = (
        (
            await session.execute(
                select(Notification)
                .where(Notification.recipient_employee_id == user.id)
                .order_by(Notification.created_at.desc(), Notification.id.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )

    return NotificationListResponse(
        unread_count=await unread_count(session, recipient_id=user.id),
        items=[
            NotificationResponse(
                external_id=row.external_id,
                kind=row.kind.value,
                title=row.title,
                body=row.body,
                trq_id=row.trq_id,
                created_at=row.created_at,
                read_at=row.read_at,
            )
            for row in rows
        ],
    )


@router.post(
    "/notifications/{external_id}/read", response_model=MarkReadResponse, tags=["notifications"]
)
async def mark_read(external_id: str, session: Session, user: CurrentUser) -> MarkReadResponse:
    row = (
        await session.execute(
            select(Notification).where(
                Notification.external_id == external_id,
                # Scoped to the recipient in the same query. Someone else's notification is
                # 404 here, not 403: a 403 would confirm the row exists.
                Notification.recipient_employee_id == user.id,
            )
        )
    ).scalar_one_or_none()

    if row is None:
        raise HTTPException(status_code=404, detail="No such notification")

    marked = 0
    if row.read_at is None:
        row.read_at = datetime.now(UTC)
        marked = 1
    await session.commit()

    return MarkReadResponse(
        unread_count=await unread_count(session, recipient_id=user.id), marked=marked
    )


@router.post("/notifications/read-all", response_model=MarkReadResponse, tags=["notifications"])
async def mark_all_read(session: Session, user: CurrentUser) -> MarkReadResponse:
    # Counted either side rather than read off rowcount: the async Result type does not carry
    # one, and the count is what the caller actually renders.
    before = await unread_count(session, recipient_id=user.id)
    await session.execute(
        update(Notification)
        .where(
            Notification.recipient_employee_id == user.id,
            Notification.read_at.is_(None),
        )
        .values(read_at=datetime.now(UTC))
    )
    await session.commit()

    after = await unread_count(session, recipient_id=user.id)
    return MarkReadResponse(unread_count=after, marked=before - after)
