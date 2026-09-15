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


class GenerationStatus(StrEnum):
    """Run state of a per-episode generation step.

    Mirrors :class:`AnalysisStatus` on the project: script and storyboard each
    get their own state so the UI can say "剧本已生成 / 分镜失败" without inferring
    it from whether a JSON column happens to be null, and so a failure keeps a
    readable error for a retry.
    """

    NOT_GENERATED = "NOT_GENERATED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
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


class CharacterRole(StrEnum):
    """Character Bible ``role`` (PRD section 7).

    A closed vocabulary keeps the UI badges meaningful; the extraction schema
    coerces anything the LLM invents into ``OTHER`` rather than failing
    validation (see ``app/schemas/bible.py``).
    """

    PROTAGONIST = "PROTAGONIST"
    ANTAGONIST = "ANTAGONIST"
    SUPPORTING = "SUPPORTING"
    MENTOR = "MENTOR"
    LOVE_INTEREST = "LOVE_INTEREST"
    OTHER = "OTHER"


class AnalysisStatus(StrEnum):
    """Lifecycle of the Story Agent run (PRD section 37)."""

    NOT_ANALYZED = "NOT_ANALYZED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class ShotStatus(StrEnum):
    """Lifecycle of one storyboard shot (PRD section 17 ``shots.status``).

    ``READY`` means the storyboard row is complete and its prompts are usable;
    the media states belong to Phases 5-7, which set them as assets arrive.
    """

    DRAFT = "DRAFT"
    READY = "READY"
    GENERATING = "GENERATING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ShotSize(StrEnum):
    """Camera framing vocabulary (PRD section 11, ``shot_size``).

    A closed vocabulary is what makes the later image prompts predictable --
    a free-text field would let the model invent "中景偏近" and the pipeline
    would have no idea how to use it.
    """

    EXTREME_WIDE = "extreme_wide"
    WIDE = "wide"
    MEDIUM = "medium"
    MEDIUM_CLOSE_UP = "medium_close_up"
    CLOSE_UP = "close_up"
    EXTREME_CLOSE_UP = "extreme_close_up"


class CameraMovement(StrEnum):
    """Camera movement vocabulary (PRD section 11, ``camera_movement``)."""

    STATIC = "static"
    SLOW_PUSH = "slow_push"
    PUSH_IN = "push_in"
    PULL_OUT = "pull_out"
    PAN_LEFT = "pan_left"
    PAN_RIGHT = "pan_right"
    TILT_UP = "tilt_up"
    TILT_DOWN = "tilt_down"
    TRACKING = "tracking"
    CRANE = "crane"
    HANDHELD = "handheld"
