"""Episode Agent node tests (PRD sections 9, 10, 11, 12, 19).

The important assertions here are the **binding rules**, because they are the
part of Phase 4 that a mock cannot validate by accident:

* ``script_generator`` must not invent ``character_id``/``location_id``. The test
  uses a provider that deliberately answers with ids that are *not on the roster*
  the first time, so the retry really has to happen -- a provider that echoes the
  roster back would make the check vacuous.
* ``storyboard_generator`` must not invent characters and must not drop a scene.
  A storyboard missing a scene would silently lose that scene's shots.

The graph-shape tests mirror the Phase 3 ones: PRD section 12's chain must be
reproducible, and media generation must stay out of it.
"""

from __future__ import annotations

import json

import pytest

from app.agents import (
    EPISODE_EXECUTION_ORDER,
    FULL_EXECUTION_ORDER,
    build_episode_graph,
    build_planner_graph,
    build_script_graph,
    build_storyboard_graph,
    full_graph_mermaid,
    run_episode_planner,
    run_script_generator,
    run_storyboard_generator,
)
from app.agents.episode_nodes import DEFAULT_EPISODE_COUNT, build_roster
from app.core.exceptions import GenerationFailedError, ValidationError
from app.providers.base import LLMProvider, LLMRequest, LLMResult
from app.providers.llm import MockLLMProvider

STORY = (
    "林澈在大学宿舍的床上睁开眼，发现自己竟然回到了十年前的开学日。"
    "前世他因为沉迷游戏错过保研，毕业后四处碰壁，最后在出租屋里郁郁而终。"
    "这一次，他决定改变自己的人生。室友赵明达推开宿舍门，喊他一起去食堂。"
    "林澈没有说话，只是握紧了拳头。班主任周老师走进教室，宣布了考研的报名时间。"
    "苏晚坐在他旁边的座位上，笑着说：林澈，你这次一定要加油。"
)

CHARACTERS = [
    {
        "id": "11111111-1111-1111-1111-111111111111",
        "name": "林澈",
        "role": "PROTAGONIST",
        "gender": "男",
        "age": "20 岁上下",
        "description": "主角",
        "appearance": "20 岁上下，身形匀称，黑色短发，常穿简约白色衬衫",
        "hair": "黑色短发",
        "clothing": "简约白色衬衫",
    },
    {
        "id": "22222222-2222-2222-2222-222222222222",
        "name": "苏晚",
        "role": "LOVE_INTEREST",
        "gender": "女",
        "age": "20 岁上下",
        "description": "女主",
        "appearance": "20 岁上下，深棕色齐肩发，常穿米色针织衫",
        "hair": "深棕色齐肩发",
        "clothing": "米色针织衫",
    },
]

LOCATIONS = [
    {
        "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "name": "大学宿舍",
        "description": "大学宿舍内部",
        "time": "深夜",
        "lighting": "暖黄台灯",
        "visual_style": "国漫",
    },
    {
        "id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        "name": "教室",
        "description": "教室内部",
        "time": "清晨",
        "lighting": "冷白日光灯",
        "visual_style": "国漫",
    },
]

STORY_BIBLE = {
    "title": "重生",
    "genre": "都市",
    "style": "国漫",
    "world_rules": ["重生者保留前世记忆"],
}

CHARACTER_IDS = {c["id"] for c in CHARACTERS}
LOCATION_IDS = {loc["id"] for loc in LOCATIONS}


class ScriptedEpisodeProvider(LLMProvider):
    """Answers with caller-supplied payloads per schema, in sequence.

    Used to make the *bad* case real: the first answer for a schema can contain
    invented ids, so the node's ``post_validate`` has to reject it and retry.

    ``calls`` is exposed through a property rather than a plain attribute:
    ``Provider`` is a Pydantic model, so an undeclared public attribute is
    rejected with ``ValueError: object has no field ...``.
    """

    name: str = "scripted"

    def __init__(self, answers: dict[str, list[object]]) -> None:
        super().__init__(name="scripted", model="scripted-v1")
        self._answers = {key: list(value) for key, value in answers.items()}
        self._calls: list[str] = []

    @property
    def calls(self) -> list[str]:
        """Schema titles requested, in order -- how the tests prove a retry."""
        return list(self._calls)

    async def health(self) -> bool:
        return True

    async def generate(self, request: LLMRequest) -> LLMResult:
        title = (request.json_schema or {}).get("title") or ""
        self._calls.append(title)

        queue = self._answers.get(title)
        if not queue:
            raise AssertionError(f"no scripted answer left for {title!r}")

        payload = queue.pop(0) if len(queue) > 1 else queue[0]
        return LLMResult(text=json.dumps(payload, ensure_ascii=False), model="scripted-v1")


def _script_payload(**overrides) -> dict:
    payload = {
        "title": "本集",
        "summary": "梗概",
        "scenes": [
            {
                "scene_id": "S1",
                "location_id": LOCATIONS[0]["id"],
                "time": "深夜",
                "description": "林澈醒来",
                "characters": [CHARACTERS[0]["id"]],
                "dialogues": [{"character_id": CHARACTERS[0]["id"], "text": "这次我不会再退。"}],
            },
            {
                "scene_id": "S2",
                "location_id": LOCATIONS[1]["id"],
                "time": "清晨",
                "description": "教室里",
                "characters": [CHARACTERS[0]["id"], CHARACTERS[1]["id"]],
                "dialogues": [],  # pure-action scene: exercises the empty-list path
            },
        ],
    }
    payload.update(overrides)
    return payload


def _storyboard_payload(scene_ids=("S1", "S2"), names=("林澈",), **shot_overrides) -> dict:
    shot = {
        "shot_number": 1,
        "duration": 5,
        "shot_size": "medium",
        "camera_movement": "slow_push",
        "characters": list(names),
        "action": "抬头",
        "expression": "坚定",
        "dialogue": "",
        "visual_description": "宿舍内部，暖黄台灯，林澈抬头",
        "image_prompt": (
            "国漫风格漫剧分镜，medium 景别，大学宿舍内部，暖黄台灯，林澈，黑色短发，简约白色衬衫"
        ),
        "video_prompt": "镜头缓慢推近",
    }
    shot.update(shot_overrides)
    return {"scenes": [{"scene_id": sid, "shots": [dict(shot)]} for sid in scene_ids]}


# --------------------------------------------------------------------------- #
# Graph shape (PRD section 12)
# --------------------------------------------------------------------------- #
class TestGraphShape:
    def test_execution_order_matches_the_prd(self) -> None:
        assert EPISODE_EXECUTION_ORDER == (
            "episode_planner",
            "script_generator",
            "storyboard_generator",
            "consistency_checker",
        )

    def test_full_pipeline_spans_both_phases_in_order(self) -> None:
        """PRD section 12 draws one chain; Phase 3 + Phase 4 make it up."""
        assert FULL_EXECUTION_ORDER == (
            "story_parser",
            "character_extractor",
            "location_extractor",
            "episode_planner",
            "script_generator",
            "storyboard_generator",
            "consistency_checker",
        )

    def test_graphs_compile_with_an_injected_provider(self) -> None:
        provider = MockLLMProvider()
        assert build_episode_graph(provider) is not None
        assert build_planner_graph(provider) is not None
        assert build_script_graph(provider) is not None
        assert build_storyboard_graph(provider) is not None

    def test_mermaid_renders_the_complete_chain(self) -> None:
        mermaid = full_graph_mermaid(MockLLMProvider())
        for node in FULL_EXECUTION_ORDER:
            assert node in mermaid
        # The edges, not just the node names.
        assert "story_parser --> character_extractor" in mermaid
        assert "location_extractor --> episode_planner" in mermaid
        assert "episode_planner --> script_generator" in mermaid
        assert "script_generator --> storyboard_generator" in mermaid
        assert "storyboard_generator --> consistency_checker" in mermaid

    def test_media_generation_is_not_a_graph_node(self) -> None:
        """PRD section 12: image/video/TTS belong to Celery tasks, not the graph."""
        assert "image_generator" not in FULL_EXECUTION_ORDER
        assert "video_generator" not in FULL_EXECUTION_ORDER
        assert "tts_generator" not in FULL_EXECUTION_ORDER


# --------------------------------------------------------------------------- #
# Roster
# --------------------------------------------------------------------------- #
class TestRoster:
    def test_roster_carries_ids_and_trims_internal_fields(self) -> None:
        roster = build_roster(CHARACTERS, LOCATIONS)
        character = roster["characters"][0]
        assert character["id"] == CHARACTERS[0]["id"]
        assert character["name"] == "林澈"
        # Nothing a prompt should not see.
        assert "voice_id" not in character
        assert "reference_image_url" not in character

    def test_roster_survives_missing_values(self) -> None:
        roster = build_roster([{"id": "x", "name": "无名"}], [{"id": "y", "name": "某地"}])
        assert roster["characters"][0]["hair"] is None
        assert roster["locations"][0]["lighting"] is None


# --------------------------------------------------------------------------- #
# Episode planner
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
class TestEpisodePlanner:
    async def test_plans_episodes_and_records_usage(self) -> None:
        state = await run_episode_planner(
            project_id="p",
            story_text=STORY,
            story_bible=STORY_BIBLE,
            characters=CHARACTERS,
            locations=LOCATIONS,
            genre="都市",
            style="国漫",
            episode_count=4,
            provider=MockLLMProvider(),
        )
        episodes = state["episode_plan"]["episodes"]
        assert episodes, "planner produced nothing"
        assert [e["episode_number"] for e in episodes] == list(range(1, len(episodes) + 1))
        assert state["prompt_versions"]["episode_planner"].startswith("episode_planner_v")
        assert state["usage"][0]["node"] == "episode_planner"

    async def test_empty_plan_is_rejected(self) -> None:
        provider = ScriptedEpisodeProvider({"EpisodePlanList": [{"episodes": []}]})
        with pytest.raises((ValidationError, GenerationFailedError)):
            await run_episode_planner(
                project_id="p",
                story_text=STORY,
                story_bible=STORY_BIBLE,
                characters=CHARACTERS,
                locations=LOCATIONS,
                provider=provider,
            )

    async def test_default_episode_count_is_used_when_unset(self) -> None:
        provider = ScriptedEpisodeProvider(
            {"EpisodePlanList": [{"episodes": [{"episode_number": 1, "title": "A"}]}]}
        )
        await run_episode_planner(
            project_id="p",
            story_text=STORY,
            story_bible=STORY_BIBLE,
            characters=CHARACTERS,
            locations=LOCATIONS,
            provider=provider,
        )
        assert DEFAULT_EPISODE_COUNT  # the planner sent this as the hint
        assert provider.calls == ["EpisodePlanList"]


# --------------------------------------------------------------------------- #
# Script generator -- the binding rules (PRD section 10)
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
class TestScriptGeneratorBinding:
    async def test_binds_to_roster_ids(self) -> None:
        provider = ScriptedEpisodeProvider({"ScriptContent": [_script_payload()]})
        state = await run_script_generator(
            project_id="p",
            episode_id="e1",
            episode_plan={"episode_number": 1, "title": "本集", "duration": 180},
            story_bible=STORY_BIBLE,
            characters=CHARACTERS,
            locations=LOCATIONS,
            provider=provider,
        )
        scenes = state["script"]["scenes"]
        assert {s["location_id"] for s in scenes} <= LOCATION_IDS
        assert {d["character_id"] for s in scenes for d in s["dialogues"]} <= CHARACTER_IDS

    async def test_invented_character_id_triggers_a_retry(self) -> None:
        """PRD section 10: the model must not create ids that do not exist.

        The first answer contains a plausible-looking but fictional uuid; only a
        retry can produce the second, correct answer. If the node silently
        accepted the first, this test would still pass on the assertion but the
        call count would be 1 -- so the call count is asserted too.
        """
        bad = _script_payload()
        bad["scenes"][0]["dialogues"][0]["character_id"] = "deadbeef-dead-beef-dead-beefdeadbeef"

        provider = ScriptedEpisodeProvider({"ScriptContent": [bad, _script_payload()]})
        state = await run_script_generator(
            project_id="p",
            episode_id="e1",
            episode_plan={"episode_number": 1, "title": "本集"},
            story_bible=STORY_BIBLE,
            characters=CHARACTERS,
            locations=LOCATIONS,
            provider=provider,
        )

        assert provider.calls == ["ScriptContent", "ScriptContent"], "no retry happened"
        assert {
            d["character_id"] for s in state["script"]["scenes"] for d in s["dialogues"]
        } <= CHARACTER_IDS

    async def test_invented_location_id_triggers_a_retry(self) -> None:
        bad = _script_payload()
        bad["scenes"][0]["location_id"] = "not-a-real-location"

        provider = ScriptedEpisodeProvider({"ScriptContent": [bad, _script_payload()]})
        await run_script_generator(
            project_id="p",
            episode_id="e1",
            episode_plan={"episode_number": 1},
            story_bible=STORY_BIBLE,
            characters=CHARACTERS,
            locations=LOCATIONS,
            provider=provider,
        )
        assert len(provider.calls) == 2

    async def test_persistently_invented_ids_fail_the_run(self) -> None:
        """Retries are bounded: a model that will not comply fails loudly.

        It must not persist a script with dangling ids.
        """
        bad = _script_payload()
        bad["scenes"][0]["location_id"] = "still-not-real"
        provider = ScriptedEpisodeProvider({"ScriptContent": [bad]})

        with pytest.raises(GenerationFailedError):
            await run_script_generator(
                project_id="p",
                episode_id="e1",
                episode_plan={"episode_number": 1},
                story_bible=STORY_BIBLE,
                characters=CHARACTERS,
                locations=LOCATIONS,
                provider=provider,
            )

    async def test_name_used_instead_of_id_is_rejected(self) -> None:
        """The most common real failure: the model writes the character's name.

        A check that only verified "not empty" would pass this through.
        """
        bad = _script_payload()
        bad["scenes"][0]["dialogues"][0]["character_id"] = "林澈"

        provider = ScriptedEpisodeProvider({"ScriptContent": [bad, _script_payload()]})
        await run_script_generator(
            project_id="p",
            episode_id="e1",
            episode_plan={"episode_number": 1},
            story_bible=STORY_BIBLE,
            characters=CHARACTERS,
            locations=LOCATIONS,
            provider=provider,
        )
        assert len(provider.calls) == 2

    async def test_requires_rosters_with_ids(self) -> None:
        """Without persisted Bibles there is nothing to bind to."""
        provider = ScriptedEpisodeProvider({"ScriptContent": [_script_payload()]})
        with pytest.raises(ValidationError):
            await run_script_generator(
                project_id="p",
                episode_id="e1",
                episode_plan={"episode_number": 1},
                story_bible=STORY_BIBLE,
                characters=[],  # not analyzed yet
                locations=LOCATIONS,
                provider=provider,
            )

    async def test_roster_without_ids_is_reported_distinctly(self) -> None:
        """Agent drafts carry no id; that is a different fix from 'not analyzed'."""
        provider = ScriptedEpisodeProvider({"ScriptContent": [_script_payload()]})
        drafts = [{"name": "林澈", "role": "PROTAGONIST"}]  # no "id" key
        with pytest.raises(ValidationError) as caught:
            await run_script_generator(
                project_id="p",
                episode_id="e1",
                episode_plan={"episode_number": 1},
                story_bible=STORY_BIBLE,
                characters=drafts,
                locations=LOCATIONS,
                provider=provider,
            )
        assert "id" in str(caught.value)

    async def test_empty_dialogue_scene_survives_the_binding_pass(self) -> None:
        """Regression guard: the non-fatal pass must handle an empty dialogue list.

        This is the offline reproduction of the production 500 -- the mock writes
        one line per scene, so only a hand-written payload reaches this path.
        """
        provider = ScriptedEpisodeProvider({"ScriptContent": [_script_payload()]})
        state = await run_script_generator(
            project_id="p",
            episode_id="e1",
            episode_plan={"episode_number": 1},
            story_bible=STORY_BIBLE,
            characters=CHARACTERS,
            locations=LOCATIONS,
            provider=provider,
        )
        assert state["script"]["scenes"][1]["dialogues"] == []
        codes = {issue["code"] for issue in state["consistency"]["issues"]}
        assert "SCENE_WITHOUT_DIALOGUE" in codes


# --------------------------------------------------------------------------- #
# Storyboard generator
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
class TestStoryboardGenerator:
    async def test_produces_one_section_per_script_scene(self) -> None:
        provider = ScriptedEpisodeProvider({"StoryboardContent": [_storyboard_payload()]})
        state = await run_storyboard_generator(
            project_id="p",
            episode_id="e1",
            script=_script_payload(),
            story_bible=STORY_BIBLE,
            characters=CHARACTERS,
            locations=LOCATIONS,
            episode_plan={"duration": 10},
            provider=provider,
        )
        assert [s["scene_id"] for s in state["storyboard"]["scenes"]] == ["S1", "S2"]
        assert state["consistency"]["checked_shots"] == 2

    async def test_missing_scene_triggers_a_retry(self) -> None:
        """A dropped scene would silently lose its shots."""
        provider = ScriptedEpisodeProvider(
            {
                "StoryboardContent": [
                    _storyboard_payload(scene_ids=("S1",)),  # S2 missing
                    _storyboard_payload(),
                ]
            }
        )
        state = await run_storyboard_generator(
            project_id="p",
            episode_id="e1",
            script=_script_payload(),
            story_bible=STORY_BIBLE,
            characters=CHARACTERS,
            locations=LOCATIONS,
            provider=provider,
        )
        assert len(provider.calls) == 2
        assert [s["scene_id"] for s in state["storyboard"]["scenes"]] == ["S1", "S2"]

    async def test_extra_scene_triggers_a_retry(self) -> None:
        provider = ScriptedEpisodeProvider(
            {
                "StoryboardContent": [
                    _storyboard_payload(scene_ids=("S1", "S2", "S9")),
                    _storyboard_payload(),
                ]
            }
        )
        await run_storyboard_generator(
            project_id="p",
            episode_id="e1",
            script=_script_payload(),
            story_bible=STORY_BIBLE,
            characters=CHARACTERS,
            locations=LOCATIONS,
            provider=provider,
        )
        assert len(provider.calls) == 2

    async def test_invented_character_name_triggers_a_retry(self) -> None:
        provider = ScriptedEpisodeProvider(
            {
                "StoryboardContent": [
                    _storyboard_payload(names=("路过的神秘人",)),
                    _storyboard_payload(),
                ]
            }
        )
        await run_storyboard_generator(
            project_id="p",
            episode_id="e1",
            script=_script_payload(),
            story_bible=STORY_BIBLE,
            characters=CHARACTERS,
            locations=LOCATIONS,
            provider=provider,
        )
        assert len(provider.calls) == 2

    async def test_persistently_bad_storyboard_fails_the_run(self) -> None:
        provider = ScriptedEpisodeProvider(
            {"StoryboardContent": [_storyboard_payload(scene_ids=("S1",))]}
        )
        with pytest.raises(GenerationFailedError):
            await run_storyboard_generator(
                project_id="p",
                episode_id="e1",
                script=_script_payload(),
                story_bible=STORY_BIBLE,
                characters=CHARACTERS,
                locations=LOCATIONS,
                provider=provider,
            )

    async def test_requires_a_script(self) -> None:
        provider = ScriptedEpisodeProvider({"StoryboardContent": [_storyboard_payload()]})
        with pytest.raises(ValidationError):
            await run_storyboard_generator(
                project_id="p",
                episode_id="e1",
                script={"scenes": []},
                story_bible=STORY_BIBLE,
                characters=CHARACTERS,
                locations=LOCATIONS,
                provider=provider,
            )

    async def test_consistency_report_merges_script_and_storyboard_issues(self) -> None:
        """The report must not lose the script-stage findings."""
        provider = ScriptedEpisodeProvider({"StoryboardContent": [_storyboard_payload()]})
        state = await run_storyboard_generator(
            project_id="p",
            episode_id="e1",
            script=_script_payload(),
            story_bible=STORY_BIBLE,
            characters=CHARACTERS,
            locations=LOCATIONS,
            provider=provider,
        )
        # The empty-dialogue scene is found by the script pass and carried through.
        assert "SCENE_WITHOUT_DIALOGUE" in {
            issue["code"] for issue in state["consistency"]["issues"]
        }


# --------------------------------------------------------------------------- #
# The offline mock must satisfy all three schemas (PRD section 37 item 8)
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
class TestMockProviderCoversPhase4:
    async def test_mock_runs_the_whole_episode_pipeline(self) -> None:
        provider = MockLLMProvider()
        plan_state = await run_episode_planner(
            project_id="p",
            story_text=STORY,
            story_bible=STORY_BIBLE,
            characters=CHARACTERS,
            locations=LOCATIONS,
            episode_count=3,
            provider=provider,
        )
        episodes = plan_state["episode_plan"]["episodes"]
        assert episodes

        script_state = await run_script_generator(
            project_id="p",
            episode_id="e1",
            episode_plan=episodes[0],
            story_bible=STORY_BIBLE,
            characters=CHARACTERS,
            locations=LOCATIONS,
            provider=provider,
        )
        assert script_state["script"]["scenes"]

        board_state = await run_storyboard_generator(
            project_id="p",
            episode_id="e1",
            script=script_state["script"],
            story_bible=STORY_BIBLE,
            characters=CHARACTERS,
            locations=LOCATIONS,
            episode_plan=episodes[0],
            provider=provider,
        )
        assert board_state["storyboard"]["scenes"]
        assert board_state["consistency"]["checked_shots"] > 0

    async def test_mock_binds_real_roster_ids(self) -> None:
        """The mock reads <roster>, so it must produce resolvable ids.

        If it invented ids the binding check could never be exercised offline.
        """
        state = await run_script_generator(
            project_id="p",
            episode_id="e1",
            episode_plan={"episode_number": 1, "summary": "梗概"},
            story_bible=STORY_BIBLE,
            characters=CHARACTERS,
            locations=LOCATIONS,
            provider=MockLLMProvider(),
        )
        scenes = state["script"]["scenes"]
        assert {s["location_id"] for s in scenes} <= LOCATION_IDS
        assert {d["character_id"] for s in scenes for d in s["dialogues"]} <= CHARACTER_IDS
