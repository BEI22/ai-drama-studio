"""Episode / Script / Storyboard schema tests (PRD sections 9, 10, 11).

These cover the coercion layer, which is where LLM output either becomes usable
data or burns a retry. Two groups matter most:

* **Structural invariants** -- episode numbering and scene/shot numbering are
  normalised, because the database has unique constraints on them and the
  storyboard keys shots by ``scene_id``. A model that reuses "S1" for every scene
  must not be able to violate either.
* **Closed vocabularies** -- ``shot_size`` / ``camera_movement`` must land on
  their enums. Phase 5's image prompts switch on these values, so a free-text
  value would break rendering silently.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models.enums import CameraMovement, ShotSize
from app.schemas.episode import (
    EpisodePlanList,
    SceneStoryboard,
    ScriptContent,
    ScriptScene,
    ShotDraft,
    StoryboardContent,
)


# --------------------------------------------------------------------- episodes
class TestEpisodePlan:
    def test_renumbers_gapped_and_duplicate_numbers(self):
        """The DB has a unique (project_id, episode_number) constraint.

        The planner cannot know what already exists, so numbering is
        normalised to 1..N in list order rather than surfacing an IntegrityError.
        """
        plan = EpisodePlanList.model_validate(
            {
                "episodes": [
                    {"episode_number": 7, "title": "第一"},
                    {"episode_number": 7, "title": "第二"},
                    {"episode_number": 99, "title": "第三"},
                ]
            }
        )
        assert [e.episode_number for e in plan.episodes] == [1, 2, 3]
        assert [e.title for e in plan.episodes] == ["第一", "第二", "第三"]

    def test_coerces_duration_text(self):
        plan = EpisodePlanList.model_validate(
            {
                "episodes": [
                    {"episode_number": 1, "title": "A", "duration": "约 5 秒"},
                    {"episode_number": 2, "title": "B", "duration": 240.6},
                    {"episode_number": 3, "title": "C"},
                ]
            }
        )
        assert [e.duration for e in plan.episodes] == [5, 241, 180]

    def test_blank_summary_becomes_none(self):
        plan = EpisodePlanList.model_validate(
            {"episodes": [{"episode_number": 1, "title": "A", "summary": "   "}]}
        )
        assert plan.episodes[0].summary is None

    def test_len_helper_and_defaults(self):
        plan = EpisodePlanList.model_validate({"episodes": []})
        assert len(plan) == 0
        plan = EpisodePlanList.model_validate({"episodes": [{"episode_number": 1, "title": "A"}]})
        assert len(plan) == 1


# ----------------------------------------------------------------------- script
class TestScriptContent:
    def test_scene_ids_are_normalised_to_s1_sn(self):
        """Shots are keyed by ``scene_id``, so duplicates must not survive.

        Models routinely emit "S1" for every scene; the storyboard would then be
        ambiguous about which scene a shot belongs to.
        """
        script = ScriptContent.model_validate(
            {
                "scenes": [
                    {"scene_id": "S1", "location_id": "L1"},
                    {"scene_id": "S1", "location_id": "L2"},
                    {"scene_id": "sc-whatever", "location_id": "L1"},
                ]
            }
        )
        assert [s.scene_id for s in script.scenes] == ["S1", "S2", "S3"]

    def test_dialogue_requires_a_character_id(self):
        """PRD section 10: a line must bind to a character, not float free."""
        with pytest.raises(ValidationError):
            ScriptScene.model_validate(
                {"scene_id": "S1", "location_id": "L1", "dialogues": [{"text": "喂"}]}
            )

    def test_blank_optional_text_becomes_none(self):
        scene = ScriptScene.model_validate(
            {"scene_id": "S1", "location_id": "L1", "time": "  ", "description": ""}
        )
        assert scene.time is None
        assert scene.description is None

    def test_characters_accepts_a_bare_string(self):
        today = ScriptScene.model_validate(
            {"scene_id": "S1", "location_id": "L1", "characters": "C1"}
        )
        assert today.characters == ["C1"]

    def test_empty_dialogue_list_is_valid(self):
        """A pure-action scene is legitimate and must not fail validation.

        This shape is what exposed the mixed dict/model accessor bug in
        ``app/agents/consistency.py`` -- see TestConsistencyShapeParity.
        """
        script = ScriptContent.model_validate(
            {"scenes": [{"scene_id": "S1", "location_id": "L1", "dialogues": []}]}
        )
        assert script.scenes[0].dialogues == []


# ------------------------------------------------------------------- storyboard
class TestShotDraft:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("中景", ShotSize.MEDIUM),
            ("特写", ShotSize.CLOSE_UP),
            ("近景", ShotSize.CLOSE_UP),
            ("大特写", ShotSize.EXTREME_CLOSE_UP),
            ("全景", ShotSize.WIDE),
            ("wide_shot", ShotSize.WIDE),
            ("closeup", ShotSize.CLOSE_UP),
            (None, ShotSize.MEDIUM),
            ("莫名其妙", ShotSize.MEDIUM),  # unknown -> default, not a failure
        ],
    )
    def test_shot_size_vocabulary(self, raw, expected):
        assert ShotDraft.model_validate({"shot_number": 1, "shot_size": raw}).shot_size == expected

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("固定", CameraMovement.STATIC),
            ("缓推", CameraMovement.SLOW_PUSH),
            ("推镜", CameraMovement.PUSH_IN),
            ("跟拍", CameraMovement.TRACKING),
            ("手持", CameraMovement.HANDHELD),
            ("slow_push", CameraMovement.SLOW_PUSH),
            (None, CameraMovement.STATIC),
            ("胡编的运镜", CameraMovement.STATIC),
        ],
    )
    def test_camera_movement_vocabulary(self, raw, expected):
        shot = ShotDraft.model_validate({"shot_number": 1, "camera_movement": raw})
        assert shot.camera_movement == expected

    def test_duration_text_is_coerced(self):
        assert ShotDraft.model_validate({"shot_number": 1, "duration": "5秒"}).duration == 5

    def test_shot_number_must_be_positive(self):
        with pytest.raises(ValidationError):
            ShotDraft.model_validate({"shot_number": 0})

    def test_blank_prompts_become_none(self):
        shot = ShotDraft.model_validate(
            {"shot_number": 1, "image_prompt": "   ", "dialogue": "", "expression": ""}
        )
        assert shot.image_prompt is None
        assert shot.dialogue is None
        assert shot.expression is None


class TestSceneStoryboard:
    def test_shot_numbers_restart_at_one_in_every_scene(self):
        """PRD section 11 numbers shots within a scene.

        If this ever renumbered globally, the ``(episode_id, scene_id,
        shot_number)`` unique constraint would still hold, but the UI would show
        scenes starting at shot 12.
        """
        board = SceneStoryboard.model_validate(
            {"scene_id": "S1", "shots": [{"shot_number": 9}, {"shot_number": 4}]}
        )
        assert [shot.shot_number for shot in board.shots] == [1, 2]

    def test_storyboard_content_shot_count(self):
        board = StoryboardContent.model_validate(
            {
                "scenes": [
                    {"scene_id": "S1", "shots": [{"shot_number": 1}, {"shot_number": 2}]},
                    {"scene_id": "S2", "shots": [{"shot_number": 1}]},
                ]
            }
        )
        assert board.shot_count == 3
        assert [s.scene_id for s in board.scenes] == ["S1", "S2"]

    def test_empty_storyboard_is_representable(self):
        assert StoryboardContent.model_validate({"scenes": []}).shot_count == 0
