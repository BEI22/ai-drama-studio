"""Story Bible / Character Bible / Scene Bible schemas (PRD sections 6, 7, 8).

These are the *contract* between the LLM and the database. PRD section 6 is
explicit: "JSON 必须结构化 / AI 输出不能直接作为数据库自由文本使用 / 后端必须进行
JSON Schema 校验 / 校验失败需要自动修复或重试".

Design rules applied here:

1. **Missing required data fails validation** so the caller can retry. Guessing
   a character's name would silently corrupt the Bible.
2. **Cosmetic variance is coerced, not rejected.** LLMs routinely return
   ``"personality": "冷静"`` instead of ``["冷静"]``, or invent a ``role``. Those
   are normalised (see the validators) rather than burning a retry.
3. **Empty strings become ``None``** so the UI shows "—" instead of a blank.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.models.enums import AnalysisStatus, CharacterRole

# A trimmed, non-empty string. Rejects "" / "   " at the boundary.
NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
OptionalText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=4000)]

MAX_ITEMS = 50
MAX_CHARACTERS = 30
MAX_LOCATIONS = 30


def _blank_to_none(value: Any) -> Any:
    """Treat ``""`` / whitespace-only as absent."""
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return value


_LIST_SEPARATORS = re.compile(r"[、;；,，/|]+")

# Synonyms real LLMs use for the PRD section 6 Story Bible fields.
#
# Verified against a live DeepSeek run: it answered `core_conflict` rather than
# `main_conflict` and `setting`/`time_period` rather than `background`, so the
# canonical names alone were losing content. Ordered most-likely first.
_STORY_BIBLE_ALIASES: dict[str, tuple[str, ...]] = {
    "title": ("story_title", "name", "working_title"),
    "genre": ("category", "type"),
    "logline": ("one_line_summary", "oneliner", "one_liner", "summary_line", "log_line"),
    "background": ("setting", "world_setting", "backdrop", "背景", "背景设定"),
    "main_conflict": (
        "core_conflict",
        "central_conflict",
        "conflict",
        "main_conflicts",
        "核心冲突",
    ),
    "style": ("visual_style", "art_style", "visual_style_hint", "画风", "美术风格"),
    "world_rules": ("rules", "world_setting_rules", "setting_rules", "世界观规则"),
    "timeline": ("plot_timeline", "story_timeline", "key_plot_points", "时间线"),
    "important_objects": ("key_objects", "props", "key_props", "重要道具"),
    "important_events": ("key_events", "major_events", "events", "重要事件"),
}


def _coerce_str_list(value: Any, *, max_items: int = MAX_ITEMS) -> list[str] | None:
    """Accept a list, a single string, or a delimited string.

    Models often emit ``"冷静、果断"`` or ``"a, b, c"`` instead of a JSON array, and
    sometimes mix separators (``"规则一，规则二、规则三"``) -- so this splits on any
    of them rather than picking one.
    """
    if value is None:
        return None

    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        items = _LIST_SEPARATORS.split(raw) if _LIST_SEPARATORS.search(raw) else [raw]
    elif isinstance(value, (list, tuple, set)):
        items = [str(item).strip() for item in value]
    else:
        items = [str(value).strip()]

    cleaned = [item.strip() for item in items if item and item.strip()]
    return cleaned[:max_items] or None


# --------------------------------------------------------------------------- #
# Character Bible (PRD section 7)
# --------------------------------------------------------------------------- #
class CharacterDraft(BaseModel):
    """One character as extracted by the LLM / edited by the user."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    name: NonEmptyStr = Field(max_length=200, description="角色姓名")
    role: CharacterRole = Field(
        default=CharacterRole.SUPPORTING,
        description="PROTAGONIST / ANTAGONIST / SUPPORTING / MENTOR / LOVE_INTEREST / OTHER",
    )
    age: OptionalText | None = None
    gender: OptionalText | None = None

    description: OptionalText | None = Field(default=None, description="一句话角色定位")
    appearance: OptionalText | None = Field(default=None, description="外貌，用于图像 Prompt")
    hair: OptionalText | None = None
    clothing: OptionalText | None = None

    personality: list[str] | None = None

    sort_order: int = 0

    @field_validator("role", mode="before")
    @classmethod
    def _coerce_role(cls, value: Any) -> Any:
        """Map an unknown/invented role onto OTHER instead of failing the run."""
        if value is None or value == "":
            return CharacterRole.SUPPORTING
        if isinstance(value, CharacterRole):
            return value
        raw = str(value).strip().upper().replace(" ", "_").replace("-", "_")
        if raw in CharacterRole.__members__:
            return raw

        aliases = {
            "MAIN": CharacterRole.PROTAGONIST,
            "HERO": CharacterRole.PROTAGONIST,
            "主角": CharacterRole.PROTAGONIST,
            "反派": CharacterRole.ANTAGONIST,
            "VILLAIN": CharacterRole.ANTAGONIST,
            "配角": CharacterRole.SUPPORTING,
            "导师": CharacterRole.MENTOR,
            "恋人": CharacterRole.LOVE_INTEREST,
        }
        return aliases.get(raw, aliases.get(str(value).strip(), CharacterRole.OTHER))

    @field_validator(
        "age", "gender", "description", "appearance", "hair", "clothing", mode="before"
    )
    @classmethod
    def _blank_to_none(cls, value: Any) -> Any:
        return _blank_to_none(value)

    @field_validator("personality", mode="before")
    @classmethod
    def _coerce_personality(cls, value: Any) -> Any:
        return _coerce_str_list(value)

    @field_validator("name")
    @classmethod
    def _name_not_placeholder(cls, value: str) -> str:
        """Reject obvious placeholders so a lazy model output can be retried."""
        placeholders = {"未知", "无", "n/a", "na", "null", "unknown", "角色", "character"}
        if value.strip().lower() in placeholders:
            raise ValueError(f"角色名是占位符：{value!r}")
        return value


class CharacterOut(CharacterDraft):
    """Character as persisted (adds identity + audit fields)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    voice_id: str | None = None
    reference_image_url: str | None = None
    created_at: datetime
    updated_at: datetime


class CharacterCreate(CharacterDraft):
    """User-created character; sort_order is assigned by the service."""


class CharacterUpdate(BaseModel):
    """PATCH semantics -- only supplied fields change."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: NonEmptyStr | None = Field(default=None, max_length=200)
    role: CharacterRole | None = None
    age: OptionalText | None = None
    gender: OptionalText | None = None
    description: OptionalText | None = None
    appearance: OptionalText | None = None
    hair: OptionalText | None = None
    clothing: OptionalText | None = None
    personality: list[str] | None = None
    voice_id: OptionalText | None = None
    reference_image_url: OptionalText | None = None
    sort_order: int | None = None

    @field_validator("role", mode="before")
    @classmethod
    def _coerce_role(cls, value: Any) -> Any:
        return CharacterDraft._coerce_role(value) if value is not None else None

    @field_validator(
        "age", "gender", "description", "appearance", "hair", "clothing", mode="before"
    )
    @classmethod
    def _blank_to_none(cls, value: Any) -> Any:
        return _blank_to_none(value)

    @field_validator("personality", mode="before")
    @classmethod
    def _coerce_personality(cls, value: Any) -> Any:
        return _coerce_str_list(value)


# --------------------------------------------------------------------------- #
# Scene / Location Bible (PRD section 8)
# --------------------------------------------------------------------------- #
class LocationDraft(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    name: NonEmptyStr = Field(max_length=200, description="场景名称")
    description: OptionalText | None = None
    time: OptionalText | None = Field(default=None, description="时间，如 清晨 / 深夜")
    lighting: OptionalText | None = None
    visual_style: OptionalText | None = None

    sort_order: int = 0

    @field_validator("description", "time", "lighting", "visual_style", mode="before")
    @classmethod
    def _blank_to_none(cls, value: Any) -> Any:
        return _blank_to_none(value)


class LocationOut(LocationDraft):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    reference_image_url: str | None = None
    created_at: datetime
    updated_at: datetime


class LocationCreate(LocationDraft):
    """User-created location; sort_order is assigned by the service."""


class LocationUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: NonEmptyStr | None = Field(default=None, max_length=200)
    description: OptionalText | None = None
    time: OptionalText | None = None
    lighting: OptionalText | None = None
    visual_style: OptionalText | None = None
    reference_image_url: OptionalText | None = None
    sort_order: int | None = None

    @field_validator("description", "time", "lighting", "visual_style", mode="before")
    @classmethod
    def _blank_to_none(cls, value: Any) -> Any:
        return _blank_to_none(value)


# --------------------------------------------------------------------------- #
# Story Bible (PRD section 6)
# --------------------------------------------------------------------------- #
class StoryBibleContent(BaseModel):
    """The world/setting half of the Story Bible.

    PRD section 6 also lists ``characters`` and ``locations`` inside this JSON.
    We deliberately keep them *out* of the stored document: they are rows in
    their own tables and the API response nests them in, so there is exactly one
    source of truth. Documented in docs/TDD.md section 17.

    Real models invent their own key names (DeepSeek answers ``core_conflict``
    where the PRD says ``main_conflict``). Those synonyms are normalised in
    :meth:`_normalize_keys` and anything still unrecognised is preserved in
    ``extensions`` rather than dropped -- silently discarding a model's output
    would lose genuinely useful story data.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    title: NonEmptyStr = Field(max_length=200)
    genre: OptionalText | None = None
    logline: OptionalText | None = Field(default=None, description="一句话故事线")
    background: OptionalText | None = Field(default=None, description="背景设定")
    main_conflict: OptionalText | None = Field(default=None, description="核心冲突")
    style: OptionalText | None = Field(default=None, description="画风 / 基调")

    world_rules: list[str] = Field(default_factory=list, description="世界观规则")
    timeline: list[str] = Field(default_factory=list, description="时间线关键节点")
    important_objects: list[str] = Field(default_factory=list)
    important_events: list[str] = Field(default_factory=list)

    # Non-PRD fields a capable model adds on its own (视觉风格、主题、人物弧光…).
    # Kept so Phase 4+ can use them and so no model output is thrown away.
    extensions: dict[str, Any] = Field(default_factory=dict, exclude=False)

    @model_validator(mode="before")
    @classmethod
    def _normalize_keys(cls, data: Any) -> Any:
        """Fold model-invented key names onto the canonical PRD ones.

        Runs before field validation so an alias satisfies the field instead of
        triggering a pointless retry, and so nothing is lost: an alias whose value
        was actually adopted is consumed, while an alias that lost to a real
        canonical value is preserved in ``extensions``.
        """
        if not isinstance(data, dict):
            return data

        normalized = dict(data)
        consumed: set[str] = set()
        field_names = set(cls.model_fields)

        for canonical, aliases in _STORY_BIBLE_ALIASES.items():
            if normalized.get(canonical) not in (None, "", [], {}):
                continue  # canonical key already carries a real value
            for alias in aliases:
                value = normalized.get(alias)
                if value not in (None, "", [], {}):
                    normalized[canonical] = value
                    consumed.add(alias)
                    break

        # Drop consumed aliases so they don't also show up in extensions, then
        # keep everything else unrecognised rather than discarding model output.
        for alias in consumed:
            normalized.pop(alias, None)

        extras = dict(normalized.get("extensions") or {})
        for key, value in normalized.items():
            if key in field_names or key in {"extensions", "_meta"}:
                continue
            if value not in (None, "", [], {}):
                extras[key] = value

        normalized["extensions"] = extras
        return normalized

    @field_validator("genre", "logline", "background", "main_conflict", "style", mode="before")
    @classmethod
    def _blank_to_none(cls, value: Any) -> Any:
        return _blank_to_none(value)

    @field_validator(
        "world_rules", "timeline", "important_objects", "important_events", mode="before"
    )
    @classmethod
    def _coerce_list(cls, value: Any) -> Any:
        return _coerce_str_list(value) or []


class StoryBibleResponse(BaseModel):
    """Story Bible as returned by ``GET /projects/{id}/bible``.

    The world/setting content is nested under ``story_bible`` rather than
    flattened into this object, so "not analyzed yet" is representable
    (``story_bible: null``) instead of forcing empty placeholder strings.
    """

    project_id: uuid.UUID
    analysis_status: AnalysisStatus
    analysis_error: str | None = None
    analyzed_at: datetime | None = None
    story_bible: StoryBibleContent | None = None
    characters: list[CharacterOut] = Field(default_factory=list)
    locations: list[LocationOut] = Field(default_factory=list)
    # Provenance: provider/model/prompt versions/usage of the run that produced
    # this Bible. Named ``meta`` in the API; stored as ``_meta`` in the JSON
    # column (leading underscore to mark it as not part of the Bible itself).
    meta: dict[str, Any] | None = None


# --------------------------------------------------------------------------- #
# LangGraph node output envelopes
# --------------------------------------------------------------------------- #
class CharacterExtraction(BaseModel):
    """Output of the ``character_extractor`` node."""

    model_config = ConfigDict(extra="ignore")

    characters: list[CharacterDraft] = Field(default_factory=list, max_length=MAX_CHARACTERS)

    @model_validator(mode="after")
    def _dedupe_by_name(self) -> CharacterExtraction:
        seen: dict[str, CharacterDraft] = {}
        for index, character in enumerate(self.characters):
            key = character.name.casefold()
            if key not in seen:
                character.sort_order = index
                seen[key] = character
        self.characters = list(seen.values())
        return self


class LocationExtraction(BaseModel):
    """Output of the ``location_extractor`` node."""

    model_config = ConfigDict(extra="ignore")

    locations: list[LocationDraft] = Field(default_factory=list, max_length=MAX_LOCATIONS)

    @model_validator(mode="after")
    def _dedupe_by_name(self) -> LocationExtraction:
        seen: dict[str, LocationDraft] = {}
        for index, location in enumerate(self.locations):
            key = location.name.casefold()
            if key not in seen:
                location.sort_order = index
                seen[key] = location
        self.locations = list(seen.values())
        return self


__all__ = [
    "CharacterCreate",
    "CharacterDraft",
    "CharacterExtraction",
    "CharacterOut",
    "CharacterUpdate",
    "LocationCreate",
    "LocationDraft",
    "LocationExtraction",
    "LocationOut",
    "LocationUpdate",
    "StoryBibleContent",
    "StoryBibleResponse",
]
