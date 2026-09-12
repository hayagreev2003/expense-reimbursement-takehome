"""Response models for the notification surface."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, field_serializer


class NotificationResponse(BaseModel):
    external_id: str
    kind: str
    title: str
    body: str
    trq_id: str | None
    created_at: datetime
    read_at: datetime | None

    @field_serializer("created_at", "read_at")
    def _utc(self, value: datetime | None) -> str | None:
        """Explicit Z. A naive timestamp is reparsed as local time in the browser and the
        inbox silently reorders itself by hours."""
        if value is None:
            return None
        stamped = value.isoformat()
        return stamped.replace("+00:00", "Z") if stamped.endswith("+00:00") else f"{stamped}Z"


class NotificationListResponse(BaseModel):
    unread_count: int
    items: list[NotificationResponse]


class MarkReadResponse(BaseModel):
    unread_count: int
    marked: int
