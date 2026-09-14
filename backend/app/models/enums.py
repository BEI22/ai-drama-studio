"""Enumerated values from the PRD (sections 9, 17, 18, 21).

Stored as plain strings (``sa.String``) instead of native PostgreSQL enums so
that adding a new value in a later phase never requires an ``ALTER TYPE``
migration. Validation happens in the Python layer.
"""

from __future__ import annotations

from enum import StrEnum


class ProjectStatus(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"
    FAILED = "FAILED"


class EpisodeStatus(StrEnum):
    """PRD section 9."""

    DRAFT = "DRAFT"
    PLANNING = "PLANNING"
    SCRIPTING = "SCRIPTING"
    STORYBOARDING = "STORYBOARDING"
    GENERATING = "GENERATING"
    COMPOSING = "COMPOSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class AssetType(StrEnum):
    """PRD section 17."""

    IMAGE = "IMAGE"
    VIDEO = "VIDEO"
    AUDIO = "AUDIO"
    BGM = "BGM"
    SFX = "SFX"
    SUBTITLE = "SUBTITLE"
    FINAL_VIDEO = "FINAL_VIDEO"


class TaskType(StrEnum):
    """PRD section 17/21 -- one row per async generation task."""

    STORY_ANALYSIS = "STORY_ANALYSIS"
    SCRIPT = "SCRIPT"
    STORYBOARD = "STORYBOARD"
    IMAGE = "IMAGE"
    VIDEO = "VIDEO"
    TTS = "TTS"
    SUBTITLE = "SUBTITLE"
    COMPOSE = "COMPOSE"


class TaskStatus(StrEnum):
    """PRD section 21."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    RETRY = "RETRY"


class MemoryType(StrEnum):
    """PRD section 18 -- RAG long-term memory."""

    CHARACTER = "CHARACTER"
    EVENT = "EVENT"
    RELATIONSHIP = "RELATIONSHIP"
    LOCATION = "LOCATION"
    PLOT = "PLOT"
    WORLD_RULE = "WORLD_RULE"
    DIALOGUE = "DIALOGUE"
