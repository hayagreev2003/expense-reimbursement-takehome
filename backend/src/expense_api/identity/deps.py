"""Identity for a request.

Authentication proper is out of scope for this build and is stated as such in docs/NOTE.md.
What is *not* out of scope is authorisation: an employee must not see another employee's claim,
and only the person a step is routed to may decide it. So the caller names themselves with an
`X-Emp-Code` header and every route resolves that into an Employee row before doing anything.
Swapping the header for a signed session changes this module and nothing else.

Two profiles, derived from the employee master's `role` column rather than stored separately:

- **employee** - submits claims, uploads bills, sees only their own trips.
- **admin** - every approver role plus Finance. Sees the queue routed to them, and acts on it.

Derived, because a second source of truth for "is this person an approver" is a second thing to
keep in step with the reporting line, and the approval matrix already reads the role column.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from expense_api.db.database import get_async_session
from expense_api.db.models import Employee, Role

Profile = Literal["employee", "admin"]

# Everything that is not a plain employee acts on other people's claims.
ADMIN_ROLES: frozenset[Role] = frozenset(
    {
        Role.REPORTING_MANAGER,
        Role.HEAD_OF_DEPARTMENT,
        Role.HEAD_OF_DIVISION,
        Role.MD,
        Role.FINANCE,
    }
)


def profile_for(role: Role) -> Profile:
    return "admin" if role in ADMIN_ROLES else "employee"


async def get_current_employee(
    session: Annotated[AsyncSession, Depends(get_async_session)],
    x_emp_code: Annotated[str | None, Header(alias="X-Emp-Code")] = None,
) -> Employee:
    if not x_emp_code:
        raise HTTPException(
            status_code=401,
            detail={"code": "not_signed_in", "message": "Choose a profile to continue."},
        )

    employee = (
        await session.execute(select(Employee).where(Employee.emp_code == x_emp_code.strip()))
    ).scalar_one_or_none()

    if employee is None:
        raise HTTPException(
            status_code=401,
            detail={"code": "unknown_profile", "message": "That profile is not in the directory."},
        )
    return employee


CurrentUser = Annotated[Employee, Depends(get_current_employee)]


async def require_admin(user: CurrentUser) -> Employee:
    """Approver-side routes. A plain employee gets 403 here rather than 404.

    The 404-not-403 rule protects *resources* whose existence is itself information. A profile
    boundary is not one: the caller already knows which profile they are.
    """
    if profile_for(user.role) != "admin":
        raise HTTPException(
            status_code=403,
            detail={
                "code": "not_an_approver",
                "message": "This area is for approvers and Finance.",
            },
        )
    return user


AdminUser = Annotated[Employee, Depends(require_admin)]
