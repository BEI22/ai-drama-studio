"""Episode / Script / Storyboard schemas (PRD sections 9, 10, 11).

These are the Phase 4 contract between the LLM and the database, following the
same rules as ``app/schemas/bible.py``:

1. **Missing required data fails validation** so the node retries. Inventing a
   scene's location would produce a storyboard that cannot be rendered.
2. **Cosmetic variance is coerced, not rejected.** Models answer ``"中景"`` for
   ``shot_size`` or write ``"5秒"`` for a duration; burning a retry on that would
   be wasteful, so those are normalised.
3. **Empty strings become ``None``.**

Where PRD section 10 demands real identifiers -- "台词必须绑定 character_id /
场景必须绑定 location_id / 不允许 AI 随意创建数据库中不存在的人物 ID" -- the id is
validated against the project's actual roster. That check needs the roster, so it
lives in the node (``app/agents/episode_nodes.py``) rather than in the schema;
see ``generate_structured(post_validate=...)``.
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

from app.models.enums import CameraMovement, EpisodeStatus, GenerationStatus, ShotSize, ShotStatus

NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
OptionalText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=4000)]

MAX_EPISODES = 24
MAX_SCENES = 40
MAX_SHOTS_PER_SCENE = 30
MAX_DIALOGUES_PER_SCENE = 60
MAX_SHOT_DURATION = 60
MIN_SHOT_DURATION = 1
DEFAULT_EPISODE_DURATION = 180

# Episode numbering starts at 1 (PRD section 9's example).
MIN_EPISODE_NUMBER = 1


def _blank_to_none(value: Any) -> Any:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return value


_DURATION_RE = re.compile(r"(\d+(?:\.\d+)?)")


def _coerce_duration(value: Any) -> Any:
    """Accept ``5``, ``"5"``, ``"5秒"``, ``"约 5 秒"`` -- anything else is left to fail."""
    if value is None or isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(round(value))
    if isinstance(value, str):
        match = _DURATION_RE.search(value)
        if match:
            return int(round(float(match.group(1))))
    return value


def _coerce_vocab(value: Any, vocabulary: type, aliases: dict[str, str], default: str) -> Any:
    """Map a free-text label onto ``vocabulary``, falling back to ``default``.

    A closed vocabulary is what keeps Phase 5's image prompts predictable, but
    rejecting the whole storyboard because the model wrote "中景" would be worse
    than quietly mapping it. Unknown labels land on the default rather than
    failing -- the consistency checker reports what was coerced.
    """
    if value is None or value == "":
        return default
    if isinstance(value, vocabulary):
        return value
    raw = str(value).strip()
    if raw in aliases:
        return aliases[raw]
    normalized = raw.lower().replace(" ", "_").replace("-", "_")
    if normalized in {member.value for member in vocabulary}:
        return normalized
    if raw.upper() in vocabulary.__members__:
        return vocabulary.__members__[raw.upper()].value
    return default


_SHOT_SIZE_ALIASES: dict[str, str] = {
    "远景": "extreme_wide",
    "大远景": "extreme_wide",
    "大全景": "wide",
    "全景": "wide",
    "中景": "medium",
    "中近景": "medium_close_up",
    "近景": "close_up",
    "特写": "close_up",
    "大特写": "extreme_close_up",
    "wide_shot": "wide",
    "medium_shot": "medium",
    "close": "close_up",
    "closeup": "close_up",
    "medium_close": "medium_close_up",
}

_CAMERA_ALIASES: dict[str, str] = {
    "固定": "static",
    "静止": "static",
    "固定镜头": "static",
    "缓推": "slow_push",
    "慢推": "slow_push",
    "推镜": "push_in",
    "推进": "push_in",
    "拉镜": "pull_out",
    "后拉": "pull_out",
    "左摇": "pan_left",
    "右摇": "pan_right",
    "上摇": "tilt_up",
    "下摇": "tilt_down",
    "跟拍": "tracking",
    "跟随": "tracking",
    "升降": "crane",
    "手持": "handheld",
    "slow_push_in": "slow_push",
    "push": "push_in",
    "pull": "pull_out",
    "pan": "pan_right",
    "dolly": "tracking",
}


# --------------------------------------------------------------------------- #
# Episode (PRD section 9)
# --------------------------------------------------------------------------- #
class EpisodePlan(BaseModel):
    """One episode as proposed by the ``episode_planner`` node."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    episode_number: int = Field(ge=MIN_EPISODE_NUMBER)
    title: NonEmptyStr = Field(max_length=200)
    summary: OptionalText | None = Field(default=None, description="本集梗概")
    duration: int = Field(
        default=DEFAULT_EPISODE_DURATION,
        ge=MIN_SHOT_DURATION,
        le=3600,
        description="目标时长（秒）",
    )

    @field_validator("duration", mode="before")
    @classmethod
    def _coerce_duration(cls, value: Any) -> Any:
        return _coerce_duration(value)

    @field_validator("title", "summary", mode="before")
    @classmethod
    def _blank_to_none(cls, value: Any) -> Any:
        return _blank_to_none(value)


class EpisodePlanList(BaseModel):
    """Output of the ``episode_planner`` node."""

    model_config = ConfigDict(extra="ignore")

    episodes: list[EpisodePlan] = Field(default_factory=list, max_length=MAX_EPISODES)

    @model_validator(mode="after")
    def _renumber(self) -> EpisodePlanList:
        """Guarantee 1..N with no gaps or duplicates.

        The database has a unique constraint on ``(project_id, episode_number)``
        and the planner has no way to know what already exists, so the numbering
        is normalised here -- in list order, which is the order the model
        intended -- rather than letting a duplicate surface as an IntegrityError.
        """
        for index, episode in enumerate(self.episodes, start=MIN_EPISODE_NUMBER):
            episode.episode_number = index
        return self

    def __len__(self) -> int:
        return len(self.episodes)


class EpisodeCreate(BaseModel):
    """Manually created episode. ``episode_number`` defaults to the next free one."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    episode_number: int | None = Field(default=None, ge=MIN_EPISODE_NUMBER)
    title: NonEmptyStr = Field(max_length=200)
    summary: OptionalText | None = None
    duration: int = Field(default=DEFAULT_EPISODE_DURATION, ge=MIN_SHOT_DURATION, le=3600)

    @field_validator("duration", mode="before")
    @classmethod
    def _coerce_duration(cls, value: Any) -> Any:
        return _coerce_duration(value)

    @field_validator("summary", mode="before")
    @classmethod
    def _blank_to_none(cls, value: Any) -> Any:
        return _blank_to_none(value)


class EpisodeUpdate(BaseModel):
    """PATCH semantics -- only supplied fields change."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    episode_number: int | None = Field(default=None, ge=MIN_EPISODE_NUMBER)
    title: NonEmptyStr | None = Field(default=None, max_length=200)
    summary: OptionalText | None = None
    duration: int | None = Field(default=None, ge=MIN_SHOT_DURATION, le=3600)
    status: EpisodeStatus | None = None

    @field_validator("duration", mode="before")
    @classmethod
    def _coerce_duration(cls, value: Any) -> Any:
        return _coerce_duration(value)

    @field_validator("summary", mode="before")
    @classmethod
    def _blank_to_none(cls, value: Any) -> Any:
        return _blank_to_none(value)


class EpisodeOut(BaseModel):
    """Episode as returned by the API.

    ``shot_count`` and the ``has_*`` flags are derived so the UI can render a
    list without fetching every script and storyboard.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    episode_number: int
    title: str | None = None
    summary: str | None = None
    duration: int
    status: EpisodeStatus

    script_status: GenerationStatus = GenerationStatus.NOT_GENERATED
    storyboard_status: GenerationStatus = GenerationStatus.NOT_GENERATED
    generation_error: str | None = None
    script_generated_at: datetime | None = None
    storyboard_generated_at: datetime | None = None

    has_script: bool = False
    has_storyboard: bool = False
    shot_count: int = 0

    created_at: datetime
    updated_at: datetime


# --------------------------------------------------------------------------- #
# Script (PRD section 10)
# --------------------------------------------------------------------------- #
class DialogueDraft(BaseModel):
    """One line of dialogue, bound to a real character (PRD section 10)."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    character_id: NonEmptyStr = Field(description="必须是 Character Bible 中已存在的角色 id")
    text: NonEmptyStr = Field(max_length=2000)
    emotion: OptionalText | None = Field(default=None, description="情绪，如 迟疑 / 愤怒")

    @field_validator("emotion", mode="before")
    @classmethod
    def _blank_to_none(cls, value: Any) -> Any:
        return _blank_to_none(value)


class ScriptScene(BaseModel):
    """One scene (PRD section 10)."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    scene_id: NonEmptyStr = Field(max_length=64, description="场景编号，如 S1")
    location_id: NonEmptyStr = Field(description="必须是 Scene Bible 中已存在的场景 id")
    time: OptionalText | None = Field(default=None, description="如 清晨 / 深夜")
    description: OptionalText | None = Field(default=None, description="本场戏的内容")
    characters: list[str] = Field(default_factory=list, description="出场角色 id 列表")
    dialogues: list[DialogueDraft] = Field(default_factory=list)

    @field_validator("time", "description", mode="before")
    @classmethod
    def _blank_to_none(cls, value: Any) -> Any:
        return _blank_to_none(value)

    @field_validator("characters", mode="before")
    @classmethod
    def _coerce_characters(cls, value: Any) -> Any:
        if value is None:
            return []
        if isinstance(value, str):
            raw = value.strip()
            return [raw] if raw else []
        if isinstance(value, (list, tuple, set)):
            return [str(item).strip() for item in value if str(item).strip()]
        return []

    @model_validator(mode="after")
    def _cap_dialogues(self) -> ScriptScene:
        self.dialogues = self.dialogues[:MAX_DIALOGUES_PER_SCENE]
        return self


class ScriptContent(BaseModel):
    """The whole script of one episode (PRD section 10)."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    title: OptionalText | None = None
    summary: OptionalText | None = None
    scenes: list[ScriptScene] = Field(default_factory=list, max_length=MAX_SCENES)

    @field_validator("title", "summary", mode="before")
    @classmethod
    def _blank_to_none(cls, value: Any) -> Any:
        return _blank_to_none(value)

    @model_validator(mode="after")
    def _renumber_scenes(self) -> ScriptContent:
        """Give every scene a stable, unique ``S<n>`` label in list order.

        Shots are keyed by ``scene_id``, so a duplicated or missing label would
        make the storyboard ambiguous. Models occasionally reuse "S1" for every
        scene; normalising here keeps that from reaching the database.
        """
        for index, scene in enumerate(self.scenes, start=1):
            scene.scene_id = f"S{index}"
        return self


class ScriptResponse(BaseModel):
    episode_id: uuid.UUID
    script_status: GenerationStatus
    has_script: bool = False
    script: ScriptContent | None = None
    meta: dict[str, Any] | None = None


class ScriptUpdate(BaseModel):
    """PATCH the script document.

    ``scenes`` replaces the whole list when supplied -- scenes are an ordered,
    internally-referenced structure, so a per-element patch would be ambiguous
    about ordering and about which dialogue ids survive.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    title: OptionalText | None = None
    summary: OptionalText | None = None
    scenes: list[ScriptScene] | None = None

    @field_validator("title", "summary", mode="before")
    @classmethod
    def _blank_to_none(cls, value: Any) -> Any:
        return _blank_to_none(value)


# --------------------------------------------------------------------------- #
# Storyboard (PRD section 11)
# --------------------------------------------------------------------------- #
class ShotDraft(BaseModel):
    """One shot as produced by the ``storyboard_generator`` node.

    PRD section 11's field list, with the two closed vocabularies coerced onto
    their enums and durations normalised.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    shot_number: int = Field(ge=1)
    duration: int = Field(default=5, ge=MIN_SHOT_DURATION, le=MAX_SHOT_DURATION)
    shot_size: ShotSize = Field(default=ShotSize.MEDIUM)
    camera_movement: CameraMovement = Field(default=CameraMovement.STATIC)

    characters: list[str] = Field(
        default_factory=list, description="出场角色名（须在 Character Bible 中）"
    )
    action: OptionalText | None = None
    expression: OptionalText | None = Field(default=None, description="表情 / 情绪")
    dialogue: OptionalText | None = None
    visual_description: OptionalText | None = None
    image_prompt: OptionalText | None = Field(default=None, description="文生图提示词")
    video_prompt: OptionalText | None = Field(default=None, description="图生视频提示词")

    @field_validator("duration", mode="before")
    @classmethod
    def _coerce_duration(cls, value: Any) -> Any:
        return _coerce_duration(value)

    @field_validator("shot_size", mode="before")
    @classmethod
    def _coerce_shot_size(cls, value: Any) -> Any:
        return _coerce_vocab(value, ShotSize, _SHOT_SIZE_ALIASES, ShotSize.MEDIUM.value)

    @field_validator("camera_movement", mode="before")
    @classmethod
    def _coerce_camera(cls, value: Any) -> Any:
        return _coerce_vocab(value, CameraMovement, _CAMERA_ALIASES, CameraMovement.STATIC.value)

    @field_validator(
        "action",
        "expression",
        "dialogue",
        "visual_description",
        "image_prompt",
        "video_prompt",
        mode="before",
    )
    @classmethod
    def _blank_to_none(cls, value: Any) -> Any:
        return _blank_to_none(value)

    @field_validator("characters", mode="before")
    @classmethod
    def _coerce_characters(cls, value: Any) -> Any:
        return ScriptScene._coerce_characters(value)


class SceneStoryboard(BaseModel):
    """One scene's shots -- exactly PRD section 11's object shape."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    scene_id: NonEmptyStr = Field(max_length=64)
    shots: list[ShotDraft] = Field(default_factory=list, max_length=MAX_SHOTS_PER_SCENE)

    @model_validator(mode="after")
    def _renumber_shots(self) -> SceneStoryboard:
        """Number shots 1..n within the scene, as section 11 specifies."""
        for index, shot in enumerate(self.shots, start=1):
            shot.shot_number = index
        return self


class StoryboardContent(BaseModel):
    """The whole storyboard of one episode.

    PRD section 11 defines a *single-scene* object (``scene_id`` + ``shots``).
    An episode has several scenes, so this wraps one :class:`SceneStoryboard`
    per scene, preserving section 11's unit verbatim inside ``scenes``.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    scenes: list[SceneStoryboard] = Field(default_factory=list, max_length=MAX_SCENES)

    @property
    def shot_count(self) -> int:
        return sum(len(scene.shots) for scene in self.scenes)


class ShotOut(BaseModel):
    """Shot as persisted."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    episode_id: uuid.UUID
    scene_id: str
    shot_number: int
    sequence: int
    duration: int
    shot_size: ShotSize
    camera_movement: CameraMovement
    characters: list[str] = Field(default_factory=list, alias="characters_json")
    action: str | None = None
    expression: str | None = None
    dialogue: str | None = None
    visual_description: str | None = None
    image_prompt: str | None = None
    video_prompt: str | None = None
    status: ShotStatus
    created_at: datetime
    updated_at: datetime

    @field_validator("characters", mode="before")
    @classmethod
    def _none_to_list(cls, value: Any) -> Any:
        return value or []


class ShotUpdate(BaseModel):
    """PATCH one shot -- the user hand-editing a storyboard row.

    The two camera vocabularies are validated **strictly** here, unlike in
    :class:`ShotDraft`. The difference is who is typing:

    * ``ShotDraft`` receives model output, so an unrecognised label is coerced
      onto the default rather than burning a retry -- a slightly wrong framing
      beats failing the whole storyboard.
    * ``ShotUpdate`` receives a human's edit, where silently turning "超宽幅" into
      ``medium`` would show the user something they did not choose. Same
      reasoning as pinning the user's genre/style hint (see docs/TDD.md): user
      input is never rewritten, it is accepted or rejected.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    duration: int | None = Field(default=None, ge=MIN_SHOT_DURATION, le=MAX_SHOT_DURATION)
    shot_size: ShotSize | None = None
    camera_movement: CameraMovement | None = None
    characters: list[str] | None = None
    action: OptionalText | None = None
    expression: OptionalText | None = None
    dialogue: OptionalText | None = None
    visual_description: OptionalText | None = None
    image_prompt: OptionalText | None = None
    video_prompt: OptionalText | None = None
    status: ShotStatus | None = None

    @field_validator("duration", mode="before")
    @classmethod
    def _coerce_duration(cls, value: Any) -> Any:
        return _coerce_duration(value)

    @field_validator(
        "action",
        "expression",
        "dialogue",
        "visual_description",
        "image_prompt",
        "video_prompt",
        mode="before",
    )
    @classmethod
    def _blank_to_none(cls, value: Any) -> Any:
        return _blank_to_none(value)


class StoryboardResponse(BaseModel):
    episode_id: uuid.UUID
    storyboard_status: GenerationStatus
    has_storyboard: bool = False
    storyboard: StoryboardContent | None = None
    shots: list[ShotOut] = Field(default_factory=list)
    consistency: ConsistencyReport | None = None
    meta: dict[str, Any] | None = None


class StoryboardUpdate(BaseModel):
    """PATCH the storyboard document (whole-scene replacement, like the script)."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    scenes: list[SceneStoryboard] | None = None


# --------------------------------------------------------------------------- #
# Consistency checker (PRD section 19)
# --------------------------------------------------------------------------- #
class ConsistencyIssue(BaseModel):
    """One problem found in a generated script/storyboard."""

    model_config = ConfigDict(str_strip_whitespace=True)

    code: str = Field(description="机器可读的问题码，如 UNKNOWN_CHARACTER")
    severity: str = Field(description="ERROR / WARNING / INFO")
    message: str
    scene_id: str | None = None
    shot_number: int | None = None
    field: str | None = None


class ConsistencyReport(BaseModel):
    """Result of the ``consistency_checker`` node.

    PRD section 19 lists the inputs that must agree: Story Bible + Character
    Bible + Scene Bible + Style Bible + reference images. V1 checks the parts
    that are decidable from the data itself (see
    ``app/services/consistency.py`` for exactly which, and why the rest is
    deferred).
    """

    issues: list[ConsistencyIssue] = Field(default_factory=list)
    checked_shots: int = 0
    checked_scenes: int = 0

    @property
    def errors(self) -> list[ConsistencyIssue]:
        return [issue for issue in self.issues if issue.severity == "ERROR"]

    @property
    def warnings(self) -> list[ConsistencyIssue]:
        return [issue for issue in self.issues if issue.severity == "WARNING"]

    @property
    def ok(self) -> bool:
        return not self.errors


StoryboardResponse.model_rebuild()

__all__ = [
    "DEFAULT_EPISODE_DURATION",
    "MAX_SHOTS_PER_SCENE",
    "ConsistencyIssue",
    "ConsistencyReport",
    "DialogueDraft",
    "EpisodeCreate",
    "EpisodeOut",
    "EpisodePlan",
    "EpisodePlanList",
    "EpisodeUpdate",
    "SceneStoryboard",
    "ScriptContent",
    "ScriptResponse",
    "ScriptScene",
    "ScriptUpdate",
    "ShotDraft",
    "ShotOut",
    "ShotUpdate",
    "StoryboardContent",
    "StoryboardResponse",
    "StoryboardUpdate",
]
