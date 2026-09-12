"""Response models for the identity surface."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class CurrentUserResponse(BaseModel):
    emp_code: str
    name: str
    email: str
    role: str
    designation: str
    department: str
    profile: Literal["employee", "admin"]
    reporting_manager_code: str | None
