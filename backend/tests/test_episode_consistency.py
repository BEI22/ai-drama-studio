"""Consistency checker tests (PRD section 19).

The first class is a **regression suite for a real production 500**: the checker
used ``getattr(obj, "f", None) or obj.get("f")`` to accept both Pydantic models
and plain dicts. That breaks whenever the attribute exists but is *empty* -- an
empty list is falsy, so evaluation fell through to ``.get`` on a Pydantic object
and raised ``AttributeError``. It only fired on a scene with no dialogue, so it
looked intermittent, and the offline mock never reproduced it because the mock
always writes exactly one line per scene.

Two lessons are encoded below and in docs/TDD.md:

1. Every rule is asserted against **both** input shapes, and their results must
   be identical -- the parity check is what makes the shape handling testable.
2. The checker must be *quiet on a clean input*. A checker that reports issues
   unconditionally passes every "it found something" test while being useless.
"""

from __future__ import annotations

from app.agents.consistency import (
    check_script_bindings,
    check_storyboard,
)
from app.schemas.episode import ScriptContent, StoryboardContent

CHARACTERS = [
    {
        "id": "C1",
        "name": "林澈",
        "appearance": "20 岁上下，身形匀称，黑色短发，常穿简约白色衬衫",
        "hair": "黑色短发",
        "clothing": "简约白色衬衫",
    },
    {
        "id": "C2",
        "name": "苏晚",
        "appearance": "20 岁上下，深棕色齐肩发，常穿米色针织衫",
        "hair": "深棕色齐肩发",
        "clothing": "米色针织衫",
    },
]
LOCATIONS = [
    {"id": "L1", "name": "宿舍", "description": "大学宿舍内部", "lighting": "暖黄台灯"},
    {"id": "L2", "name": "操场", "description": "空旷的操场跑道", "lighting": "冷白路灯"},
]
CHARACTER_IDS = {c["id"]: c["name"] for c in CHARACTERS}
LOCATION_IDS = {loc["id"]: loc["name"] for loc in LOCATIONS}


def _script_payload(**overrides) -> dict:
    payload = {
        "scenes": [
            {
                "scene_id": "S1",
                "location_id": "L1",
                "characters": ["C1"],
                "dialogues": [{"character_id": "C1", "text": "这次我不会再退。"}],
            }
        ]
    }
    payload.update(overrides)
    return payload


def _storyboard_payload(scene_id: str = "S1", **shot_overrides) -> dict:
    shot = {
        "shot_number": 1,
        "duration": 5,
        "shot_size": "medium",
        "camera_movement": "slow_push",
        "characters": ["林澈"],
        "dialogue": "这次我不会再退。",
        "visual_description": "宿舍里，林澈抬头看向窗外",
        "image_prompt": (
            "国漫风格漫剧分镜，medium 景别，大学宿舍内部，暖黄台灯，林澈，"
            "黑色短发，简约白色衬衫，画面氛围沉静"
        ),
        "video_prompt": "镜头缓慢推近",
    }
    shot.update(shot_overrides)
    return {"scenes": [{"scene_id": scene_id, "shots": [shot]}]}


# =========================================================================== #
# Regression: the AttributeError 500
# =========================================================================== #
class TestSceneContextEvidence:
    """`SCENE_CONTEXT_MISSING` replaced two checks that cried wolf.

    The old `LOCATION_NOT_IN_PROMPT` / `LIGHTING_NOT_IN_PROMPT` required a
    *verbatim* fragment of the Bible's `description` / `lighting` to appear in
    the prompt. Measured against a real 54-shot storyboard that fired on 52 and
    41 shots respectively -- prompts that plainly do describe the room and its
    light, just in the model's own words:

        Bible : 礼堂顶部大灯明亮，舞台聚光灯打在主席台上，座位区光线均匀偏暖
        prompt: ...顶部大灯明亮，座位区暖光均匀...

    93 false positives on a consistent storyboard is worse than no check: nobody
    reads the panel, and a real problem hides in the noise. The replacement asks
    the question text matching can actually settle: does the prompt mention place
    or light *at all*?
    """

    def test_paraphrased_lighting_is_not_flagged(self):
        """The exact real-world case: same meaning, different wording."""
        report = check_storyboard(
            _storyboard_payload(
                image_prompt=(
                    "国漫风格漫剧分镜，medium 景别，大学宿舍，"
                    "18岁东亚男性大学生林澈，黑色短发略带蓬松碎发，"
                    "简约白色衬衫，顶部大灯明亮，座位区暖光均匀，氛围沉静"
                )
            ),
            script=ScriptContent.model_validate(_script_payload()),
            characters=CHARACTERS,
            locations=LOCATIONS,
        )

        codes = {issue.code for issue in report.issues}
        assert "SCENE_CONTEXT_MISSING" not in codes

    def test_prompt_with_no_place_or_light_is_flagged(self):
        """The defect the check exists for: subject only, no setting.

        Nothing about a room, a surface or the light -- Phase 5 would render the
        subject against a void. This is the assertion that proves the check can
        fail; without it, the check above proves nothing.
        """
        report = check_storyboard(
            _storyboard_payload(
                image_prompt=(
                    "国漫风格漫剧分镜，close_up 特写，18岁东亚男性大学生林澈，"
                    "黑色短发，简约白色衬衫，面无表情"
                )
            ),
            script=ScriptContent.model_validate(_script_payload()),
            characters=CHARACTERS,
            locations=LOCATIONS,
        )

        codes = {issue.code for issue in report.issues}
        assert "SCENE_CONTEXT_MISSING" in codes

    def test_clothing_words_alone_do_not_count_as_context(self):
        """A wardrobe description is not an environment.

        Guards the vocabulary against drifting so wide that the check can never
        fire (`白色` / `衬衫` must not satisfy it).
        """
        report = check_storyboard(
            _storyboard_payload(
                image_prompt="consistency 测试，林澈，黑色短发，简约白色衬衫，米色针织衫"
            ),
            script=ScriptContent.model_validate(_script_payload()),
            characters=CHARACTERS,
            locations=LOCATIONS,
        )

        codes = {issue.code for issue in report.issues}
        assert "SCENE_CONTEXT_MISSING" in codes


class TestConsistencyShapeParity:
    """The checker must accept Pydantic models *and* dicts, identically.

    The agent nodes hand over validated models; the service and API hand over
    dicts read from the JSON columns. Both paths must work, and must agree.
    """

    def test_script_with_empty_dialogue_scene_does_not_raise_on_a_model(self):
        """The exact shape that produced a 500 in production.

        Scene S2 has no dialogue. The old accessor computed
        ``getattr(scene, "dialogues", None) or scene.get("dialogues")`` -- ``[]``
        is falsy, so it called ``.get`` on a ``ScriptScene`` and raised
        ``AttributeError: 'ScriptScene' object has no attribute 'get'``.
        """
        script = ScriptContent.model_validate(
            {
                "scenes": [
                    {
                        "scene_id": "S1",
                        "location_id": "L1",
                        "characters": ["C1"],
                        "dialogues": [{"character_id": "C1", "text": "一句话"}],
                    },
                    {  # pure-action scene: no dialogue at all
                        "scene_id": "S2",
                        "location_id": "L2",
                        "characters": ["C1"],
                        "dialogues": [],
                    },
                ]
            }
        )

        issues = check_script_bindings(script, CHARACTER_IDS, LOCATION_IDS)

        assert [issue.code for issue in issues] == ["SCENE_WITHOUT_DIALOGUE"]
        assert issues[0].scene_id == "S2"

    def test_storyboard_with_empty_character_list_does_not_raise_on_a_model(self):
        """The same class of bug, reached through the storyboard path."""
        storyboard = StoryboardContent.model_validate(
            {
                "scenes": [
                    {
                        "scene_id": "S1",
                        "shots": [{"shot_number": 1, "characters": [], "duration": 4}],
                    }
                ]
            }
        )

        report = check_storyboard(
            storyboard,
            script=ScriptContent.model_validate(_script_payload()),
            characters=CHARACTERS,
            locations=LOCATIONS,
        )

        assert report.checked_shots == 1
        assert "UNKNOWN_CHARACTER" not in {issue.code for issue in report.issues}

    def test_script_results_are_identical_for_model_and_dict(self):
        script = ScriptContent.model_validate(_script_payload())
        as_model = check_script_bindings(script, CHARACTER_IDS, LOCATION_IDS)
        as_dict = check_script_bindings(script.model_dump(), CHARACTER_IDS, LOCATION_IDS)

        assert [(i.code, i.severity, i.scene_id) for i in as_model] == [
            (i.code, i.severity, i.scene_id) for i in as_dict
        ]

    def test_storyboard_results_are_identical_for_model_and_dict(self):
        script = ScriptContent.model_validate(_script_payload())
        storyboard = StoryboardContent.model_validate(_storyboard_payload())

        as_model = check_storyboard(
            storyboard, script=script, characters=CHARACTERS, locations=LOCATIONS, style="国漫"
        )
        as_dict = check_storyboard(
            storyboard.model_dump(),
            script=script.model_dump(),
            characters=CHARACTERS,
            locations=LOCATIONS,
            style="国漫",
        )

        assert as_model.checked_shots == as_dict.checked_shots
        assert [i.code for i in as_model.issues] == [i.code for i in as_dict.issues]

    def test_empty_documents_are_safe(self):
        """No script / no storyboard must not explode or invent issues."""
        assert check_script_bindings({}, CHARACTER_IDS, LOCATION_IDS) == []
        report = check_storyboard({}, script={}, characters=[], locations=[])
        assert report.checked_shots == 0
        assert report.issues == []


# =========================================================================== #
# Storyboard rules
# =========================================================================== #
class TestStoryboardChecks:
    def test_clean_storyboard_reports_nothing(self):
        """The most important test here: a good storyboard must be silent.

        Every "it detects X" test below would pass against a checker that flagged
        everything, so this is what keeps them honest.
        """
        report = check_storyboard(
            _storyboard_payload(),
            script=_script_payload(),
            characters=CHARACTERS,
            locations=LOCATIONS,
            episode_duration=5,
            style="国漫",
        )
        assert report.issues == [], [i.model_dump() for i in report.issues]
        assert report.checked_shots == 1
        assert report.checked_scenes == 1
        assert report.ok

    def test_unknown_character_is_an_error(self):
        report = check_storyboard(
            _storyboard_payload(characters=["凭空出现的路人"]),
            script=_script_payload(),
            characters=CHARACTERS,
            locations=LOCATIONS,
        )
        codes = {issue.code for issue in report.issues}
        assert "UNKNOWN_CHARACTER" in codes
        assert not report.ok, "an invented character must make the storyboard unusable"

    def test_scene_missing_from_script_is_an_error(self):
        report = check_storyboard(
            _storyboard_payload(scene_id="S9"),
            script=_script_payload(),
            characters=CHARACTERS,
            locations=LOCATIONS,
        )
        assert "SCENE_NOT_IN_SCRIPT" in {issue.code for issue in report.issues}
        assert not report.ok

    def test_scene_without_shots_is_a_warning(self):
        report = check_storyboard(
            {"scenes": [{"scene_id": "S1", "shots": []}]},
            script=_script_payload(),
            characters=CHARACTERS,
            locations=LOCATIONS,
        )
        issues = {issue.code: issue.severity for issue in report.issues}
        assert issues.get("SCENE_WITHOUT_SHOTS") == "WARNING"
        assert report.ok, "an empty scene is incomplete, not unusable"

    def test_missing_image_prompt_is_flagged(self):
        report = check_storyboard(
            _storyboard_payload(image_prompt=""),
            script=_script_payload(),
            characters=CHARACTERS,
            locations=LOCATIONS,
        )
        assert "IMAGE_PROMPT_MISSING" in {issue.code for issue in report.issues}

    def test_missing_visual_description_is_flagged(self):
        report = check_storyboard(
            _storyboard_payload(visual_description=None),
            script=_script_payload(),
            characters=CHARACTERS,
            locations=LOCATIONS,
        )
        assert "VISUAL_DESCRIPTION_MISSING" in {issue.code for issue in report.issues}

    def test_appearance_drift_is_warned(self):
        """A character in the prompt with no Bible appearance evidence.

        Warning, not error: this is substring evidence, not understanding.
        """
        report = check_storyboard(
            _storyboard_payload(image_prompt="国漫风格，一个年轻人在宿舍里坐着，暖黄台灯"),
            script=_script_payload(),
            characters=CHARACTERS,
            locations=LOCATIONS,
            style="国漫",
        )
        issues = {issue.code: issue.severity for issue in report.issues}
        assert issues.get("APPEARANCE_NOT_IN_PROMPT") == "WARNING"

    def test_missing_global_style_is_warned(self):
        report = check_storyboard(
            _storyboard_payload(
                image_prompt="medium 景别，大学宿舍内部，暖黄台灯，林澈黑色短发白衬衫"
            ),
            script=_script_payload(),
            characters=CHARACTERS,
            locations=LOCATIONS,
            style="国漫",
        )
        assert "STYLE_NOT_IN_PROMPT" in {issue.code for issue in report.issues}

    def test_overlong_shot_is_warned(self):
        report = check_storyboard(
            _storyboard_payload(duration=30),
            script=_script_payload(),
            characters=CHARACTERS,
            locations=LOCATIONS,
        )
        assert "SHOT_TOO_LONG" in {issue.code for issue in report.issues}

    def test_non_positive_duration_is_an_error(self):
        report = check_storyboard(
            _storyboard_payload(duration=0),
            script=_script_payload(),
            characters=CHARACTERS,
            locations=LOCATIONS,
        )
        assert "SHOT_DURATION_INVALID" in {issue.code for issue in report.issues}
        assert not report.ok

    def test_dialogue_not_matching_the_script_is_warned(self):
        report = check_storyboard(
            _storyboard_payload(dialogue="这句台词剧本里根本没有"),
            script=_script_payload(),
            characters=CHARACTERS,
            locations=LOCATIONS,
        )
        assert "DIALOGUE_NOT_IN_SCRIPT" in {issue.code for issue in report.issues}

    def test_episode_duration_drift_is_warned(self):
        report = check_storyboard(
            _storyboard_payload(duration=5),
            script=_script_payload(),
            characters=CHARACTERS,
            locations=LOCATIONS,
            episode_duration=180,
        )
        assert "EPISODE_DURATION_MISMATCH" in {issue.code for issue in report.issues}

    def test_missing_video_prompt_is_only_info(self):
        report = check_storyboard(
            _storyboard_payload(video_prompt=None),
            script=_script_payload(),
            characters=CHARACTERS,
            locations=LOCATIONS,
        )
        issues = {issue.code: issue.severity for issue in report.issues}
        assert issues.get("VIDEO_PROMPT_MISSING") == "INFO"
        assert report.ok


# =========================================================================== #
# Script binding rules (non-fatal pass)
# =========================================================================== #
class TestScriptBindings:
    def test_clean_script_reports_nothing(self):
        script = ScriptContent.model_validate(_script_payload())
        assert check_script_bindings(script, CHARACTER_IDS, LOCATION_IDS) == []

    def test_speaker_not_listed_in_the_scene_is_warned(self):
        script = ScriptContent.model_validate(
            {
                "scenes": [
                    {
                        "scene_id": "S1",
                        "location_id": "L1",
                        "characters": ["C1"],
                        "dialogues": [{"character_id": "C2", "text": "我也有话说"}],
                    }
                ]
            }
        )
        issues = check_script_bindings(script, CHARACTER_IDS, LOCATION_IDS)
        assert [issue.code for issue in issues] == ["SPEAKER_NOT_IN_SCENE"]
        assert issues[0].severity == "WARNING"

    def test_scene_without_dialogue_is_info_when_characters_present(self):
        script = ScriptContent.model_validate(
            {
                "scenes": [
                    {
                        "scene_id": "S1",
                        "location_id": "L1",
                        "characters": ["C1"],
                        "dialogues": [],
                    }
                ]
            }
        )
        issues = check_script_bindings(script, CHARACTER_IDS, LOCATION_IDS)
        assert [issue.code for issue in issues] == ["SCENE_WITHOUT_DIALOGUE"]
        assert issues[0].severity == "INFO"

    def test_scene_with_no_characters_and_no_dialogue_is_silent(self):
        """An empty scene is not a dialogue problem -- reporting it would be noise."""
        script = ScriptContent.model_validate(
            {"scenes": [{"scene_id": "S1", "location_id": "L1", "characters": [], "dialogues": []}]}
        )
        assert check_script_bindings(script, CHARACTER_IDS, LOCATION_IDS) == []
