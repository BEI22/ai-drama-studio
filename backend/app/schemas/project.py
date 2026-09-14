"""Project + Story schemas (PRD sections 5.1, 5.2, 5.3, 17, 22)."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import EpisodeStatus, ProjectStatus

NAME_MAX = 200
STORY_TEXT_MAX = 200_000
DESCRIPTION_MAX = 2_000


class StorySource(StrEnum):
    """PRD section 5.2 -- 故事来源."""

    SYNOPSIS = "SYNOPSIS"  # 故事梗概
    NOVEL = "NOVEL"  # 小说文本
    SCRIPT = "SCRIPT"  # 剧本


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=NAME_MAX)
    genre: str | None = Field(default=None, max_length=100)
    style: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX)

    # Optional: the story may also be supplied later via POST /projects/{id}/story
    story_source: StorySource | None = None
    story_text: str | None = Field(default=None, max_length=STORY_TEXT_MAX)

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("项目名称不能为空")
        return value.strip()

    @model_validator(mode="after")
    def _story_text_requires_source(self) -> ProjectCreate:
        """A non-empty 故事文本 must declare where it came from (PRD 5.2)."""
        if self.story_text and self.story_text.strip() and self.story_source is None:
            raise ValueError("提供故事文本时必须指定故事来源 story_source")
        if self.story_text is not None and not self.story_text.strip():
            self.story_text = None
        return self


class ProjectUpdate(BaseModel):
    """PATCH semantics: only the supplied fields change."""

    name: str | None = Field(default=None, min_length=1, max_length=NAME_MAX)
    genre: str | None = Field(default=None, max_length=100)
    style: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX)
    status: ProjectStatus | None = None

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("项目名称不能为空")
        return value.strip() if value else value


class StoryUpsert(BaseModel):
    """``POST /projects/{id}/story`` payload."""

    story_source: StorySource
    story_text: str = Field(min_length=1, max_length=STORY_TEXT_MAX)

    @field_validator("story_text")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("故事文本不能为空")
        return value


class EpisodeSummary(BaseModel):
    id: uuid.UUID
    episode_number: int
    title: str | None
    summary: str | None
    duration: int
    status: EpisodeStatus

    model_config = ConfigDict(from_attributes=True)


class ProjectOut(BaseModel):
    """Project summary used by list + dashboard cards (PRD section 5.1)."""

    id: uuid.UUID
    name: str
    genre: str | None
    style: str | None
    description: str | None
    status: ProjectStatus
    story_source: StorySource | None
    has_story: bool
    episode_count: int
    created_at: datetime
    updated_at: datetime


class ProjectDetailOut(ProjectOut):
    """Project detail (PRD section 5.3)."""

    story_text: str | None
    story_bible_json: dict | None
    episodes: list[EpisodeSummary] = Field(default_factory=list)


class ProjectListOut(BaseModel):
    items: list[ProjectOut]
    total: int
    page: int
    page_size: int
