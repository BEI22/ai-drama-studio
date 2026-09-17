"""Prompt Builder -- assemble the final text-to-image prompt (PRD section 19).

Section 19 defines the final prompt as a *composition*:

    System Style + Character Description + Location Description
    + Current Shot + Camera + Emotion + Reference Image

Phase 4 let the storyboard LLM write ``shots.image_prompt`` freely. Measured
against a real storyboard, that produced good prompts that were nonetheless
**inconsistent**: whether a character's wardrobe or the scene's lighting appeared
at all was left to the model's whim (the same class of drift the consistency
checker exists to catch -- see docs/TDD.md section 13.21).

So Phase 5 moves authorship of the final prompt here, where it is deterministic
and testable: the layers are read from the Bibles and the shot row, and the same
inputs always produce byte-identical output. ``shots.image_prompt`` becomes an
*input* (the fallback core, and the source of narrative detail) rather than the
finished article.

All wording lives in ``prompts/image/image_prompt_v1.md`` (PRD section 20); this
module only maps domain objects onto that template's placeholders.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from app.models.enums import CameraMovement, ShotSize
from app.utils.prompts import load_prompt

PROMPT_PATH = "image/image_prompt_v1"
REFERENCE_PROMPT_PATH = "image/reference_v1"

_PLACEHOLDER_RE = re.compile(r"\{([a-z_][a-z0-9_]*)\}")

# Prompt-facing vocabulary for PRD section 11's closed sets. Kept separate from
# the UI labels (frontend/types/api.ts) on purpose: a picture prompt reads better
# with "近景/中景" framing words than with an enum name, and the two audiences can
# diverge. A test asserts this covers every enum member, so adding a value to the
# vocabulary cannot silently leave the prompt without a word for it.
SHOT_SIZE_PROMPT_LABELS: dict[str, str] = {
    ShotSize.EXTREME_WIDE.value: "大远景",
    ShotSize.WIDE.value: "远景",
    ShotSize.MEDIUM.value: "中景",
    ShotSize.MEDIUM_CLOSE_UP.value: "中近景",
    ShotSize.CLOSE_UP.value: "特写",
    ShotSize.EXTREME_CLOSE_UP.value: "大特写",
}

CAMERA_MOVEMENT_PROMPT_LABELS: dict[str, str] = {
    CameraMovement.STATIC.value: "固定机位",
    CameraMovement.SLOW_PUSH.value: "缓慢推近",
    CameraMovement.PUSH_IN.value: "推镜",
    CameraMovement.PULL_OUT.value: "拉镜",
    CameraMovement.PAN_LEFT.value: "向左摇镜",
    CameraMovement.PAN_RIGHT.value: "向右摇镜",
    CameraMovement.TILT_UP.value: "向上摇镜",
    CameraMovement.TILT_DOWN.value: "向下摇镜",
    CameraMovement.TRACKING.value: "跟拍",
    CameraMovement.CRANE.value: "升降镜头",
    CameraMovement.HANDHELD.value: "手持晃动",
}

# Said only when a reference image actually exists. It is a consistency
# instruction, not a URL: the portable /images/generations contract cannot carry
# image conditioning (see providers/image/openai_compatible.py), and pasting a
# URL into a text prompt would be noise the model cannot act on.
REFERENCE_CLAUSE = "与已生成的角色/场景参考图保持一致"


@dataclass(frozen=True)
class BuiltImagePrompt:
    """The assembled prompt plus the audit trail of how it was assembled."""

    prompt: str
    negative_prompt: str | None
    prompt_version: str
    # Which layer contributed what -- recorded on the asset so a bad picture can
    # be traced back to its inputs without re-running the pipeline.
    layers: dict[str, str] = field(default_factory=dict)

    @property
    def core_source(self) -> str:
        return self.layers.get("core_source", "")


def _text(value: object) -> str:
    """Coerce a possibly-None column to a trimmed string."""
    return "" if value is None else str(value).strip()


def _join(parts: Sequence[str], *, sep: str = "，") -> str:
    return sep.join(part for part in (p.strip() for p in parts) if part)


def _assemble(template: str, values: Mapping[str, str]) -> str:
    """Render ``template``, dropping lines whose placeholders are all empty.

    Section 19's layers are individually optional -- a shot may have no dialogue,
    a scene may have no lighting note. Template languages cannot express "skip
    this line", and leaving `人物：` with nothing after it would put a dangling
    half-sentence into the prompt, so empties remove their whole line. Section
    separators (`---`) are dropped too: the loader hands back the raw section,
    presentation is this function's job.
    """
    lines: list[str] = []
    for raw_line in template.splitlines():
        line = raw_line.strip()
        if not line or set(line) <= {"-"}:
            continue
        names = _PLACEHOLDER_RE.findall(line)
        if names and all(not values.get(name, "").strip() for name in names):
            continue
        rendered = line
        for name in names:
            rendered = rendered.replace(f"{{{name}}}", values.get(name, ""))
        # A line can lose all meaning after substitution ("{a}，{b}" with b empty).
        rendered = rendered.strip("，, 、;；")
        if rendered:
            lines.append(rendered)
    return "，".join(lines)


def _character_block(characters: Sequence[Mapping[str, object]]) -> str:
    """PRD section 19's Character Description layer.

    Each character gets name + the visual facts that must not drift between
    shots: appearance, hair, clothing.
    """
    entries: list[str] = []
    for character in characters:
        name = _text(character.get("name"))
        if not name:
            continue
        detail = _join(
            [
                _text(character.get("appearance")),
                _text(character.get("hair")),
                _text(character.get("clothing")),
            ]
        )
        entries.append(f"{name}（{detail}）" if detail else name)
    return _join(entries, sep="；")


def _location_block(location: Mapping[str, object] | None) -> str:
    """PRD section 19's Location Description layer (name + description)."""
    if not location:
        return ""
    name = _text(location.get("name"))
    description = _text(location.get("description"))
    return _join([name, description])


def _reference_clause(*, characters, location) -> str:
    has_reference = any(_text(c.get("reference_image_url")) for c in characters) or bool(
        location and _text(location.get("reference_image_url"))
    )
    return REFERENCE_CLAUSE if has_reference else ""


def build_reference_prompt(
    *,
    project_style: str | None,
    bible_style: str | None,
    kind: str,
    name: str,
    detail: str,
    palette: str | None = None,
) -> BuiltImagePrompt:
    """Assemble a Character/Location reference-sheet prompt (Phase 5).

    A reference sheet is not a storyboard frame: it is a reusable visual anchor,
    so the template pins a plain background, a front view and no action. It lives
    here rather than in the image service because assembling prompt text from a
    prompt file is this module's whole job.
    """
    template = load_prompt(REFERENCE_PROMPT_PATH)
    values = {
        "style": _join([_text(project_style), _text(bible_style)], sep=" "),
        "kind": kind,
        "name": name,
        "detail": detail,
        "palette": _text(palette),
    }
    system = _assemble(template.system, values)
    body = _assemble(template.user_template, values)
    return BuiltImagePrompt(
        prompt=_join([system, body]),
        negative_prompt=template.render_negative(**values) or None,
        prompt_version=template.version,
        layers=values,
    )


def build_image_prompt(
    *,
    project_style: str | None,
    bible_style: str | None,
    characters: Sequence[Mapping[str, object]] = (),
    location: Mapping[str, object] | None = None,
    shot: Mapping[str, object],
) -> BuiltImagePrompt:
    """Assemble the final image prompt for one shot.

    ``characters`` must already be the ones present in this shot, and
    ``location`` the shot's scene location -- resolving ids to rows is the
    caller's job (see ``app/services/image_service.py``), so this function stays
    pure and needs no database.
    """
    template = load_prompt(PROMPT_PATH)

    style = _join([_text(project_style), _text(bible_style)], sep=" ")
    shot_size = _text(shot.get("shot_size"))
    camera = _text(shot.get("camera_movement"))
    framing = SHOT_SIZE_PROMPT_LABELS.get(shot_size, shot_size)

    # Core: the frame's content. ``visual_description`` is preferred because the
    # storyboard prompt defines it as "这一格画面" (this frame), which is exactly
    # what an image model needs; ``action`` and the LLM's finished
    # ``image_prompt`` are progressively weaker fallbacks (older rows may have
    # neither). ``core_source`` always names the layer that actually won, so a
    # surprising picture can be traced to its input without re-running anything.
    description = _text(shot.get("visual_description"))
    action = _text(shot.get("action"))
    fallback = _text(shot.get("image_prompt"))

    if description:
        core, core_source = description, "visual_description"
        if action and action not in description:
            core = _join([core, action])
    elif action:
        core, core_source = action, "action"
    elif fallback:
        core, core_source = fallback, "image_prompt"
    else:
        core, core_source = "", "none"

    values = {
        "style": style,
        "characters": _character_block(characters),
        "location": _location_block(location),
        "lighting": _text(location.get("lighting")) if location else "",
        "framing": framing,
        "core": core,
        "camera": CAMERA_MOVEMENT_PROMPT_LABELS.get(camera, camera),
        "emotion": _text(shot.get("expression")),
        "reference": _reference_clause(characters=characters, location=location),
    }

    # The system section goes through the same line-based assembly as the body:
    # it carries a placeholder too (the style anchor), and a raw section comes
    # back with the file's trailing "---" separator stuck to it -- which would
    # otherwise land inside the finished prompt.
    system = _assemble(template.system, values)
    body = _assemble(template.user_template, values)
    prompt = _join([system, body])

    return BuiltImagePrompt(
        prompt=prompt,
        negative_prompt=template.render_negative(**values) or None,
        prompt_version=template.version,
        layers={**values, "core_source": core_source},
    )
