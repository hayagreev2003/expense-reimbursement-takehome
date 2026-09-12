"""Schemas for the demo reset."""

from pydantic import BaseModel, ConfigDict, Field


class ResetDemoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    deleted_rows: int = Field(description="Rows removed across every transactional table.")
    deleted_uploads: int = Field(description="Employee-uploaded files removed from disk.")
    employees: int = Field(description="Employees present after the re-seed.")
    policy_versions: int = Field(description="Policy versions present after the re-seed.")
    trq_id: str = Field(description="The anchor trip the demo starts from.")
