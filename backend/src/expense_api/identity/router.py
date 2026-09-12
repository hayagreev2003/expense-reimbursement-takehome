"""Who am I. The router declares no prefix; create_app() mounts it."""

from __future__ import annotations

from fastapi import APIRouter

from expense_api.identity.deps import CurrentUser, profile_for
from expense_api.identity.schemas import CurrentUserResponse

router = APIRouter()


@router.get("/me", response_model=CurrentUserResponse, tags=["identity"])
async def me(user: CurrentUser) -> CurrentUserResponse:
    return CurrentUserResponse(
        emp_code=user.emp_code,
        name=user.name,
        email=user.email,
        role=user.role.value,
        designation=user.designation,
        department=user.department,
        profile=profile_for(user.role),
        reporting_manager_code=user.reporting_manager_code,
    )
