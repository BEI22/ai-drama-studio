"""Episode Agent nodes (PRD sections 12, 19, 38 -- Phase 4).

    episode_planner -> script_generator -> storyboard_generator -> consistency_checker

Two of these nodes carry a rule that cannot live in the Pydantic schema alone:

* ``script_generator`` must not invent identifiers. PRD section 10: "台词必须绑定
  character_id / 场景必须绑定 location_id / 不允许 AI 随意创建数据库中不存在的人物 ID".
  The check compares the output against the project's real roster, so it runs as
  ``post_validate`` -- a violation feeds the offending ids back to the model and
  retries, the same mechanism used for schema errors.
* ``storyboard_generator`` must not invent characters *or* drop scenes: shots
  reference characters by name (PRD section 11) and each script scene needs a
  storyboard section, otherwise a scene would silently lose its shots.

``consistency_checker`` is deliberately **rule-based, not LLM-based** in V1. It is
deterministic, free, and cannot hallucinate a clean bill of health; the semantic
checks PRD section 19 ultimately wants are listed in docs/TDD.md as Phase 4
follow-ups rather than pretended here.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.agents.consistency import ERROR, WARNING, check_script_bindings, check_storyboard
from app.agents.state import StoryState
from app.agents.structured import generate_structured
from app.core.config import settings
from app.core.exceptions import ValidationError
from app.providers.base import LLMProvider, LLMRequest
from app.schemas.episode import EpisodePlanList, ScriptContent, StoryboardContent
from app.utils.prompts import load_prompt

logger = logging.getLogger(__name__)

EPISODE_PLANNER_PROMPT = "episode/episode_planner_v1"
SCRIPT_GENERATOR_PROMPT = "script/script_generator_v1"
STORYBOARD_GENERATOR_PROMPT = "storyboard/storyboard_generator_v1"

DEFAULT_EPISODE_COUNT = 6


def _usage_record(node: str, provider: LLMProvider, prompt_version: str, result) -> dict[str, Any]:
    return {
        "node": node,
        "provider": provider.name,
        "model": result.model or provider.model or "",
        "prompt_version": prompt_version,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "estimated_cost": result.estimated_cost,
    }


def build_roster(characters: list[dict], locations: list[dict]) -> dict[str, list[dict]]:
    """Trim the Bibles down to what a prompt needs, ids included.

    Only the fields that affect the writing/visuals are sent: sending the whole
    row would waste tokens and give the model columns (``voice_id``,
    ``reference_image_url``) it must not reason about.
    """
    return {
        "characters": [
            {
                "id": str(character.get("id") or ""),
                "name": character.get("name"),
                "role": character.get("role"),
                "gender": character.get("gender"),
                "age": character.get("age"),
                "description": character.get("description"),
                "appearance": character.get("appearance"),
                "hair": character.get("hair"),
                "clothing": character.get("clothing"),
            }
            for character in characters
        ],
        "locations": [
            {
                "id": str(location.get("id") or ""),
                "name": location.get("name"),
                "description": location.get("description"),
                "time": location.get("time"),
                "lighting": location.get("lighting"),
                "visual_style": location.get("visual_style"),
            }
            for location in locations
        ],
    }


def _ids(items: list[dict]) -> dict[str, str]:
    """``{id: name}`` for the entities that have an id."""
    return {str(item["id"]): str(item.get("name") or "") for item in items if item.get("id")}


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


# --------------------------------------------------------------------------- #
# Node 1 -- Episode Planner
# --------------------------------------------------------------------------- #
def make_episode_planner_node(provider: LLMProvider):
    """Split the story into an episode outline (PRD section 9)."""

    async def episode_planner(state: StoryState) -> dict[str, Any]:
        story = state.get("story", {})
        characters = state.get("characters") or []
        locations = state.get("locations") or []
        desired = int(story.get("episode_count") or DEFAULT_EPISODE_COUNT)

        prompt = load_prompt(EPISODE_PLANNER_PROMPT)
        system, user = prompt.render(
            story_text=(story.get("story_text") or "").strip(),
            story_bible_json=_dump(state.get("story_bible") or {}),
            characters_json=_dump(build_roster(characters, locations)["characters"]),
            locations_json=_dump(build_roster(characters, locations)["locations"]),
            genre=story.get("genre") or "（未指定）",
            style=story.get("style") or "（未指定）",
            episode_count=desired,
        )

        plan, result = await generate_structured(
            provider,
            LLMRequest(
                prompt=user,
                system=system,
                prompt_version=prompt.version,
                temperature=settings.llm_temperature,
            ),
            EpisodePlanList,
        )

        if not plan.episodes:
            raise ValidationError("分集大纲为空，无法继续")

        logger.info("episode_planner produced %d episodes", len(plan.episodes))
        return {
            "episode_plan": plan.model_dump(),
            "current_step": "episode_planner",
            "usage": [
                *state.get("usage", []),
                _usage_record("episode_planner", provider, prompt.version, result),
            ],
            "prompt_versions": {
                **state.get("prompt_versions", {}),
                "episode_planner": prompt.version,
            },
        }

    return episode_planner


# --------------------------------------------------------------------------- #
# Node 2 -- Script Generator
# --------------------------------------------------------------------------- #
def make_script_generator_node(provider: LLMProvider):
    """Write one episode's script, bound to real character/location ids."""

    async def script_generator(state: StoryState) -> dict[str, Any]:
        story = state.get("story", {})
        characters = state.get("characters") or []
        locations = state.get("locations") or []
        roster = build_roster(characters, locations)

        character_ids = _ids(roster["characters"])
        location_ids = _ids(roster["locations"])
        if not character_ids or not location_ids:
            # Two different situations, and the user-visible fix differs, so say
            # which one it is. The agent's own node output carries no id -- ids
            # only exist once the Bible has been persisted -- so a caller that
            # passes raw workflow state here gets the second message rather than
            # a confusing "please analyze the story" when it already did.
            if not characters or not locations:
                raise ValidationError("剧本生成需要已解析的人物与场景，请先解析故事")
            raise ValidationError(
                "人物或场景缺少 id，无法绑定到剧本（请先完成故事解析并落库）",
                details={
                    "characters_missing_id": not character_ids,
                    "locations_missing_id": not location_ids,
                },
            )

        prompt = load_prompt(SCRIPT_GENERATOR_PROMPT)
        system, user = prompt.render(
            episode_json=_dump(state.get("episode_plan") or {}),
            story_bible_json=_dump(state.get("story_bible") or {}),
            roster_json=_dump(roster),
            genre=story.get("genre") or "（未指定）",
            style=story.get("style") or "（未指定）",
        )

        def reject_unknown_ids(script: ScriptContent) -> None:
            """PRD section 10: no invented ids, in scenes or in dialogue."""
            unknown_locations: list[str] = []
            unknown_characters: list[str] = []

            for scene in script.scenes:
                if scene.location_id not in location_ids:
                    unknown_locations.append(f"{scene.scene_id}:{scene.location_id}")
                for character_id in scene.characters:
                    if character_id not in character_ids:
                        unknown_characters.append(f"{scene.scene_id}:{character_id}")
                for dialogue in scene.dialogues:
                    if dialogue.character_id not in character_ids:
                        unknown_characters.append(f"{scene.scene_id}:{dialogue.character_id}")

            problems: list[str] = []
            if unknown_locations:
                problems.append(
                    "以下 location_id 不在场景名单中："
                    + "、".join(unknown_locations[:10])
                    + "\n可用的 location_id：\n"
                    + "\n".join(f"  {key} = {name}" for key, name in location_ids.items())
                )
            if unknown_characters:
                problems.append(
                    "以下 character_id 不在角色名单中："
                    + "、".join(unknown_characters[:10])
                    + "\n可用的 character_id：\n"
                    + "\n".join(f"  {key} = {name}" for key, name in character_ids.items())
                )
            if problems:
                raise ValueError("\n".join(problems))

        script, result = await generate_structured(
            provider,
            LLMRequest(
                prompt=user,
                system=system,
                prompt_version=prompt.version,
                temperature=settings.llm_temperature,
            ),
            ScriptContent,
            post_validate=reject_unknown_ids,
        )

        # A second, non-fatal pass: the retry above guarantees ids resolve, this
        # records the softer problems (orphan characters, dialogue for someone
        # who is not in the scene) for the UI instead of discarding them.
        binding_issues = check_script_bindings(script, character_ids, location_ids)

        logger.info(
            "script_generator wrote %d scenes for episode %s",
            len(script.scenes),
            state.get("episode_id"),
        )
        return {
            "script": script.model_dump(),
            "consistency": {
                "issues": [issue.model_dump() for issue in binding_issues],
                "stage": "script",
            },
            "current_step": "script_generator",
            "usage": [
                *state.get("usage", []),
                _usage_record("script_generator", provider, prompt.version, result),
            ],
            "prompt_versions": {
                **state.get("prompt_versions", {}),
                "script_generator": prompt.version,
            },
        }

    return script_generator


# --------------------------------------------------------------------------- #
# Node 3 -- Storyboard Generator
# --------------------------------------------------------------------------- #
def make_storyboard_generator_node(provider: LLMProvider):
    """Turn the script into shots (PRD section 11)."""

    async def storyboard_generator(state: StoryState) -> dict[str, Any]:
        story = state.get("story", {})
        script_payload = state.get("script") or {}
        script_scenes = script_payload.get("scenes") or []
        if not script_scenes:
            raise ValidationError("分镜生成需要剧本，请先生成剧本")

        roster = build_roster(state.get("characters") or [], state.get("locations") or [])
        character_names = {
            str(character.get("name") or "").casefold()
            for character in roster["characters"]
            if character.get("name")
        }
        expected_scene_ids = {str(scene.get("scene_id")) for scene in script_scenes}

        prompt = load_prompt(STORYBOARD_GENERATOR_PROMPT)
        system, user = prompt.render(
            script_json=_dump(script_payload),
            story_bible_json=_dump(state.get("story_bible") or {}),
            roster_json=_dump(roster),
            locations_json=_dump(roster["locations"]),
            genre=story.get("genre") or "（未指定）",
            style=story.get("style") or "（未指定）",
        )

        def reject_unknown_content(storyboard: StoryboardContent) -> None:
            """No invented characters, and no scene may lose its storyboard."""
            unknown_characters: list[str] = []
            for scene in storyboard.scenes:
                for shot in scene.shots:
                    for name in shot.characters:
                        if name.casefold() not in character_names:
                            unknown_characters.append(
                                f"{scene.scene_id} 镜{shot.shot_number}:{name}"
                            )

            produced = {scene.scene_id for scene in storyboard.scenes}
            missing = sorted(expected_scene_ids - produced)
            extra = sorted(produced - expected_scene_ids)

            problems: list[str] = []
            if unknown_characters:
                problems.append(
                    "以下角色名不在角色名单中："
                    + "、".join(unknown_characters[:10])
                    + "\n可用的角色姓名："
                    + "、".join(sorted(character_names))
                )
            if missing:
                problems.append(
                    "以下场景缺少分镜（scenes[].scene_id 必须与剧本一一对应）："
                    + "、".join(missing)
                )
            if extra:
                problems.append("以下 scene_id 在剧本中不存在，必须删除：" + "、".join(extra))
            if problems:
                raise ValueError("\n".join(problems))

        storyboard, result = await generate_structured(
            provider,
            LLMRequest(
                prompt=user,
                system=system,
                prompt_version=prompt.version,
                temperature=settings.llm_temperature,
            ),
            StoryboardContent,
            post_validate=reject_unknown_content,
        )

        logger.info(
            "storyboard_generator wrote %d scenes / %d shots for episode %s",
            len(storyboard.scenes),
            storyboard.shot_count,
            state.get("episode_id"),
        )
        return {
            "storyboard": storyboard.model_dump(),
            "current_step": "storyboard_generator",
            "usage": [
                *state.get("usage", []),
                _usage_record("storyboard_generator", provider, prompt.version, result),
            ],
            "prompt_versions": {
                **state.get("prompt_versions", {}),
                "storyboard_generator": prompt.version,
            },
        }

    return storyboard_generator


# --------------------------------------------------------------------------- #
# Node 4 -- Consistency Checker
# --------------------------------------------------------------------------- #
def make_consistency_checker_node():
    """Audit the storyboard against the Bibles (PRD section 19).

    Deterministic on purpose -- see the module docstring.
    """

    async def consistency_checker(state: StoryState) -> dict[str, Any]:
        storyboard = state.get("storyboard") or {}
        script = state.get("script") or {}
        characters = state.get("characters") or []
        locations = state.get("locations") or []

        report = check_storyboard(
            storyboard,
            script=script,
            characters=characters,
            locations=locations,
            episode_duration=int((state.get("episode_plan") or {}).get("duration") or 0) or None,
            style=(state.get("story") or {}).get("style"),
        )

        # Re-audit the script here as well, rather than relying on whatever the
        # script node happened to leave in the state: this node also runs on the
        # storyboard-only graph, where no script pass has happened. Without this
        # the report would silently differ depending on which endpoint ran.
        script_issues = check_script_bindings(
            script,
            _ids(build_roster(characters, locations)["characters"]),
            _ids(build_roster(characters, locations)["locations"]),
        )

        # ``previous`` only holds findings from earlier nodes in *this* run, and is
        # deduplicated against a freshly computed pass so a script+storyboard run
        # does not report the same issue twice.
        previous = state.get("consistency") or {}
        merged: list[dict] = []
        seen: set[tuple[str, str | None, int | None, str]] = set()

        for issue in [
            *[i.model_dump() for i in script_issues],
            *(previous.get("issues") or []),
            *[i.model_dump() for i in report.issues],
        ]:
            key = (
                str(issue.get("code")),
                issue.get("scene_id"),
                issue.get("shot_number"),
                str(issue.get("message")),
            )
            if key in seen:
                continue
            seen.add(key)
            merged.append(issue)

        errors = [i for i in merged if i.get("severity") == ERROR]
        warnings = [i for i in merged if i.get("severity") == WARNING]

        logger.info(
            "consistency_checker audited %d shots: %d errors, %d warnings",
            report.checked_shots,
            len(errors),
            len(warnings),
        )
        return {
            "current_step": "consistency_checker",
            "consistency": {
                "issues": merged,
                "checked_shots": report.checked_shots,
                "checked_scenes": report.checked_scenes,
                "ok": not errors,
            },
        }

    return consistency_checker


__all__ = [
    "DEFAULT_EPISODE_COUNT",
    "EPISODE_PLANNER_PROMPT",
    "SCRIPT_GENERATOR_PROMPT",
    "STORYBOARD_GENERATOR_PROMPT",
    "build_roster",
    "make_consistency_checker_node",
    "make_episode_planner_node",
    "make_script_generator_node",
    "make_storyboard_generator_node",
]
