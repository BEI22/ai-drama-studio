"""Deterministic consistency checking (PRD section 19).

Section 19 asks for visual consistency across Story Bible + Character Bible +
Scene Bible + Style Bible + reference images. This module covers the part that
is **decidable from the data we already hold**, and nothing more:

| Check | Why it is decidable |
|---|---|
| unknown character name in a shot | the Character Bible is the roster |
| shot referencing a scene the script does not have | the script is the list |
| dialogue that is not in the script | the script holds the lines |
| missing / stub ``image_prompt`` | Phase 5 has nothing to render without it |
| character appearance absent from the prompt | Bible ``hair``/``clothing`` are the reference |
| location lighting absent from the prompt | Scene Bible ``lighting`` is the reference |
| total duration far from the planned episode duration | both numbers exist |
| shot longer than a漫剧 shot plausibly runs | a ceiling we can state |

Two things are deliberately **not** claimed here:

* **Nothing is semantic.** Whether a shot's art direction actually *matches* the
  Bible is a judgement call; V1 approximates it with substring evidence and
  labels the result a WARNING, never an ERROR. An LLM-based critic is Phase 4
  follow-up work (docs/TDD.md section 18).
* **No image comparison.** Reference-image similarity needs Phase 5's assets.

Keeping the checker rule-based is a feature, not a shortcut: it is free, runs on
every request without a provider, and cannot hallucinate a clean bill of health.
"""

from __future__ import annotations

import re
from typing import Any

from app.schemas.episode import ConsistencyIssue, ConsistencyReport

# Severity vocabulary. Only ERROR means "this storyboard is not usable".
ERROR = "ERROR"
WARNING = "WARNING"
INFO = "INFO"

# A prompt this short cannot be carrying style + subject + lighting.
MIN_IMAGE_PROMPT_LENGTH = 20

# 漫剧 shots are short; anything past this is a mis-parse of "5-8秒" style text.
MAX_REASONABLE_SHOT_DURATION = 15

# How far the summed shot duration may drift from the planned episode duration
# before it is worth flagging. Storyboards routinely land within ±25%.
DURATION_TOLERANCE = 0.35

_SEGMENT_RE = re.compile(r"[，,、;；/|\s]+")


def _get(obj: Any, name: str, default: Any = None) -> Any:
    """Read ``name`` from a plain dict *or* a Pydantic model.

    Both shapes reach these checks: the agent nodes pass validated Pydantic
    objects, while the service and API pass plain dicts read out of the JSON
    columns. Doing this in one place matters -- the earlier mixed form
    ``getattr(x, "f", None) or (x or {}).get("f")`` silently broke whenever the
    attribute existed but was *empty* (an empty list is falsy, so it fell through
    to ``.get`` on a Pydantic object and raised ``AttributeError``). That only
    fired on a scene with no dialogue, which is why it looked intermittent and
    why the offline mock never reproduced it -- the mock always writes one line
    per scene.
    """
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _scenes_of(document: Any) -> list[Any]:
    """The ``scenes`` list of a script/storyboard, dict or model alike."""
    return list(_get(document, "scenes") or [])


def _segments(value: str | None) -> list[str]:
    """Split a Bible description into comparable fragments."""
    if not value:
        return []
    return [part.strip() for part in _SEGMENT_RE.split(str(value)) if len(part.strip()) >= 2]


def _mentions(haystack: str, value: str | None) -> bool:
    """True when any fragment of ``value`` appears in ``haystack``.

    Substring evidence, not understanding: if the Bible says the character wears
    "简约白色衬衫配深色长裤" and the prompt says "白色衬衫", that counts. The
    looseness is why the resulting issue is a WARNING.
    """
    if not haystack:
        return False
    lowered = haystack.casefold()
    return any(part.casefold() in lowered for part in _segments(value))


# Words that indicate a prompt actually places the subject somewhere, or says
# something about the light. Deliberately generic: the model paraphrases, so a
# specific phrase is not the test -- "is there any place/light language at all"
# is. Clothing and face words are kept out on purpose (a bare "白色T恤" must not
# count as environment), so this check can and does fail.
_CONTEXT_TOKENS = (
    # light
    "光",
    "灯",
    "照明",
    "亮",
    "昏暗",
    "阴影",
    "逆光",
    "色调",
    "阳光",
    "日光",
    "天光",
    # place
    "室内",
    "室外",
    "房间",
    "屋",
    "厅",
    "室",
    "走廊",
    "过道",
    "街",
    "广场",
    "路面",
    "户外",
    "窗外",
    "天花",
    "墙",
    "地面",
    "桌",
    "椅",
    "床",
    "背景",
    "天空",
    "树",
)


def _mentions_context(prompt: str) -> bool:
    """True when the prompt says anything about place or light.

    See docs/TDD.md section 13.21: this is the *weak* claim that can actually be
    settled by text matching, unlike "did the prompt convey the Bible's
    environment", which cannot be settled without understanding paraphrase.
    """
    if not prompt:
        return False
    lowered = prompt.casefold()
    return any(token in lowered for token in _CONTEXT_TOKENS)


# --------------------------------------------------------------------------- #
# Script bindings (non-fatal pass)
# --------------------------------------------------------------------------- #
def check_script_bindings(
    script: Any,
    character_ids: dict[str, str],
    location_ids: dict[str, str],
) -> list[ConsistencyIssue]:
    """Report softer script problems the id-binding retry does not cover.

    The retry guarantees every id resolves; these are the consequences that are
    wrong but not worth burning a retry on -- a speaker who is not listed as
    present in the scene, or a scene with no dialogue at all.
    """
    issues: list[ConsistencyIssue] = []

    for scene in _scenes_of(script):
        scene_id = str(_get(scene, "scene_id") or "?")
        present = set(_get(scene, "characters") or [])
        dialogues = _get(scene, "dialogues") or []

        for dialogue in dialogues:
            character_id = _get(dialogue, "character_id")
            if character_id and character_id not in present:
                issues.append(
                    ConsistencyIssue(
                        code="SPEAKER_NOT_IN_SCENE",
                        severity=WARNING,
                        message=(
                            f"{scene_id} 有台词来自未列入本场出场角色的"
                            f"「{character_ids.get(character_id, character_id)}」"
                        ),
                        scene_id=scene_id,
                        field="characters",
                    )
                )

        if not dialogues and present:
            issues.append(
                ConsistencyIssue(
                    code="SCENE_WITHOUT_DIALOGUE",
                    severity=INFO,
                    message=f"{scene_id} 有角色出场但没有任何台词（若为纯动作场面可忽略）",
                    scene_id=scene_id,
                )
            )

    return issues


# --------------------------------------------------------------------------- #
# Storyboard audit
# --------------------------------------------------------------------------- #
def check_storyboard(
    storyboard: Any,
    *,
    script: Any,
    characters: list[dict],
    locations: list[dict],
    episode_duration: int | None = None,
    style: str | None = None,
) -> ConsistencyReport:
    """Audit a storyboard against the Bibles. Returns a report, never raises."""
    scenes = _scenes_of(storyboard)

    character_names = {
        str(character.get("name") or "").casefold(): character
        for character in characters
        if character.get("name")
    }
    location_by_id = {
        str(location.get("id")): location for location in locations if location.get("id")
    }
    script_scene_list = _scenes_of(script)
    script_scenes = {
        str(_get(scene, "scene_id")): scene
        for scene in script_scene_list
        if _get(scene, "scene_id")
    }

    issues: list[ConsistencyIssue] = []
    checked_shots = 0
    total_duration = 0

    for scene in scenes:
        scene_id = str(_get(scene, "scene_id") or "?")
        shots = _get(scene, "shots") or []

        if not shots:
            issues.append(
                ConsistencyIssue(
                    code="SCENE_WITHOUT_SHOTS",
                    severity=WARNING,
                    message=f"{scene_id} 没有任何镜头",
                    scene_id=scene_id,
                )
            )
            continue

        if scene_id not in script_scenes:
            issues.append(
                ConsistencyIssue(
                    code="SCENE_NOT_IN_SCRIPT",
                    severity=ERROR,
                    message=f"{scene_id} 不在剧本中，其镜头无法对应任何剧情",
                    scene_id=scene_id,
                )
            )

        # Location/lighting context for this scene, when the script says where it is.
        script_scene = script_scenes.get(scene_id) or {}
        location = location_by_id.get(str(_get(script_scene, "location_id") or ""))
        location_lighting = (location or {}).get("lighting")
        location_description = (location or {}).get("description")

        dialogue_pool = " ".join(
            str(_get(line, "text") or "") for line in (_get(script_scene, "dialogues") or [])
        )

        for shot in shots:
            checked_shots += 1
            number = _get(shot, "shot_number")
            duration = _get(shot, "duration") or 0
            total_duration += int(duration or 0)
            image_prompt = str(_get(shot, "image_prompt") or "")
            video_prompt = str(_get(shot, "video_prompt") or "")
            visual = str(_get(shot, "visual_description") or "")
            dialogue = _get(shot, "dialogue")

            def add(
                code: str,
                severity: str,
                message: str,
                field: str | None = None,
                *,
                _scene_id: str = scene_id,
                _number: int | None = number if isinstance(number, int) else None,
            ) -> None:
                """Record one issue for this shot.

                ``_scene_id`` / ``_number`` are bound as default arguments rather
                than closed over: a closure would read the loop variables at call
                time, which ruff flags (B023) and which would silently attribute
                issues to the wrong shot the moment anything deferred the call.
                """
                issues.append(
                    ConsistencyIssue(
                        code=code,
                        severity=severity,
                        message=f"{_scene_id} 镜{_number}：{message}",
                        scene_id=_scene_id,
                        shot_number=_number,
                        field=field,
                    )
                )

            # --- characters -------------------------------------------------
            for name in _get(shot, "characters") or []:
                key = str(name).casefold()
                if key not in character_names:
                    add(
                        "UNKNOWN_CHARACTER",
                        ERROR,
                        f"角色「{name}」不在 Character Bible 中（分镜不得引入新角色）",
                        "characters",
                    )
                    continue

                character = character_names[key]
                # Appearance evidence, not judgement: at least one of the Bible's
                # hair/clothing fragments should survive into the prompt, or the
                # character will drift between shots.
                if image_prompt:
                    has_hair = _mentions(image_prompt, character.get("hair"))
                    has_clothing = _mentions(image_prompt, character.get("clothing"))
                    has_appearance = _mentions(image_prompt, character.get("appearance"))
                    if not (has_hair or has_clothing or has_appearance):
                        add(
                            "APPEARANCE_NOT_IN_PROMPT",
                            WARNING,
                            f"「{name}」的外貌特征未出现在 image_prompt 中，跨镜头可能变脸/换装",
                            "image_prompt",
                        )

            # --- prompts ----------------------------------------------------
            if len(image_prompt.strip()) < MIN_IMAGE_PROMPT_LENGTH:
                add(
                    "IMAGE_PROMPT_MISSING",
                    WARNING,
                    "缺少可用的 image_prompt（Phase 5 无法据此绘图）",
                    "image_prompt",
                )
            if not video_prompt.strip():
                add(
                    "VIDEO_PROMPT_MISSING",
                    INFO,
                    "缺少 video_prompt，Phase 6 将退回用 image_prompt 驱动",
                    "video_prompt",
                )
            if not visual.strip():
                add(
                    "VISUAL_DESCRIPTION_MISSING",
                    WARNING,
                    "缺少 visual_description",
                    "visual_description",
                )

            # --- environment + style ---------------------------------------
            if image_prompt:
                # Weak evidence, on purpose. The Bible's `description`/`lighting`
                # are free prose and the model paraphrases them freely, so
                # demanding OUR wording proves nothing: measured on a real
                # 54-shot storyboard, a verbatim requirement fired on 52/54
                # shots whose prompts plainly do describe the room and its light
                # (see docs/TDD.md section 13.21). What IS checkable is the
                # stronger defect: a prompt that says nothing about place or
                # light at all will render a subject on an empty background.
                if (location_description or location_lighting) and not _mentions_context(
                    image_prompt
                ):
                    add(
                        "SCENE_CONTEXT_MISSING",
                        INFO,
                        "image_prompt 未描述任何环境或光线，Phase 5 可能画出没有背景的画面",
                        "image_prompt",
                    )
                if (
                    style
                    and style.strip()
                    and style.strip().casefold() not in image_prompt.casefold()
                ):
                    add(
                        "STYLE_NOT_IN_PROMPT",
                        WARNING,
                        f"全局画风「{style}」未出现在 image_prompt 中",
                        "image_prompt",
                    )

            # --- dialogue ---------------------------------------------------
            if dialogue and str(dialogue).strip() and dialogue_pool:
                # Compare loosely: models re-punctuate when copying a line across.
                needle = re.sub(r"\s+", "", str(dialogue))
                haystack = re.sub(r"\s+", "", dialogue_pool)
                if needle not in haystack and haystack not in needle:
                    add(
                        "DIALOGUE_NOT_IN_SCRIPT",
                        WARNING,
                        "该镜头台词与剧本不一致（分镜台词应照抄剧本）",
                        "dialogue",
                    )

            # --- duration ---------------------------------------------------
            if int(duration or 0) > MAX_REASONABLE_SHOT_DURATION:
                add(
                    "SHOT_TOO_LONG",
                    WARNING,
                    f"单镜头 {duration} 秒偏长，漫剧镜头通常在 2-8 秒",
                    "duration",
                )
            if int(duration or 0) <= 0:
                add("SHOT_DURATION_INVALID", ERROR, "镜头时长必须大于 0", "duration")

    # Episode-level duration check.
    if episode_duration and total_duration:
        drift = abs(total_duration - episode_duration) / episode_duration
        if drift > DURATION_TOLERANCE:
            issues.append(
                ConsistencyIssue(
                    code="EPISODE_DURATION_MISMATCH",
                    severity=WARNING,
                    message=(
                        f"分镜总时长 {total_duration} 秒与计划时长 {episode_duration} 秒"
                        f"相差 {drift:.0%}"
                    ),
                    field="duration",
                )
            )

    return ConsistencyReport(
        issues=issues,
        checked_shots=checked_shots,
        checked_scenes=len(scenes),
    )


__all__ = [
    "DURATION_TOLERANCE",
    "ERROR",
    "INFO",
    "MAX_REASONABLE_SHOT_DURATION",
    "MIN_IMAGE_PROMPT_LENGTH",
    "WARNING",
    "check_script_bindings",
    "check_storyboard",
]
