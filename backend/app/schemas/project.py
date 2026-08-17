"""Project request/response schemas."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from app.models.enums import Browser


class ProjectBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    base_url: HttpUrl
    description: str | None = None
    default_browsers: list[Browser] = Field(default_factory=lambda: [Browser.CHROMIUM])
    settings: dict[str, Any] = Field(default_factory=dict)

    @field_validator("default_browsers")
    @classmethod
    def at_least_one_browser(cls, value: list[Browser]) -> list[Browser]:
        if not value:
            raise ValueError("Pick at least one browser")
        return list(dict.fromkeys(value))  # de-duplicate, keep order


class ProjectCreate(ProjectBase):
    pass


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    base_url: HttpUrl | None = None
    description: str | None = None
    default_browsers: list[Browser] | None = None
    settings: dict[str, Any] | None = None


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    base_url: str
    description: str | None
    default_browsers: list[str]
    settings: dict[str, Any]
    owner_id: int
    created_at: datetime
    updated_at: datetime


class SampleFileRead(BaseModel):
    """One file a test can upload, instead of a generated placeholder."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    content_type: str
    size: int
