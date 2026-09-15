"""Story / Character / Scene Bible schema tests (PRD sections 6, 7, 8, 30).

The PRD demands structured, schema-validated AI output. These tests pin down the
two halves of that contract:

* genuinely missing data **must** fail, so the caller can retry;
* cosmetic LLM variance **must** be coerced, so a retry is not burned on
  ``"personality": "冷静"`` instead of ``["冷静"]``.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.bible import (
    _STORY_BIBLE_ALIASES,
    CharacterCreate,
    CharacterDraft,
    CharacterExtraction,
    CharacterUpdate,
    LocationDraft,
    LocationExtraction,
    LocationUpdate,
    StoryBibleContent,
)


class TestStoryBibleContent:
    def test_minimal_valid(self) -> None:
        bible = StoryBibleContent.model_validate({"title": "重生"})
        assert bible.title == "重生"
        assert bible.world_rules == []
        assert bible.timeline == []
        assert bible.genre is None

    def test_title_is_required(self) -> None:
        with pytest.raises(ValidationError) as excinfo:
            StoryBibleContent.model_validate({"genre": "都市"})
        assert "title" in str(excinfo.value)

    def test_blank_title_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            StoryBibleContent.model_validate({"title": "   "})

    def test_whitespace_is_stripped(self) -> None:
        bible = StoryBibleContent.model_validate({"title": "  重生  "})
        assert bible.title == "重生"

    def test_empty_string_optional_fields_become_none(self) -> None:
        """The UI should render "—", not an empty string."""
        bible = StoryBibleContent.model_validate({"title": "t", "genre": "", "logline": "   "})
        assert bible.genre is None
        assert bible.logline is None

    def test_list_fields_coerce_comma_separated_string(self) -> None:
        """Models often emit "规则一，规则二" instead of a JSON array."""
        bible = StoryBibleContent.model_validate(
            {"title": "t", "world_rules": "规则一，规则二、规则三"}
        )
        assert bible.world_rules == ["规则一", "规则二", "规则三"]

    def test_list_fields_coerce_single_string(self) -> None:
        bible = StoryBibleContent.model_validate({"title": "t", "timeline": "只有一件事"})
        assert bible.timeline == ["只有一件事"]

    def test_list_fields_none_becomes_empty(self) -> None:
        bible = StoryBibleContent.model_validate({"title": "t", "world_rules": None})
        assert bible.world_rules == []

    def test_empty_list_entries_are_dropped(self) -> None:
        bible = StoryBibleContent.model_validate(
            {"title": "t", "world_rules": ["a", "", "  ", "b"]}
        )
        assert bible.world_rules == ["a", "b"]

    def test_extra_keys_are_ignored(self) -> None:
        """``_meta`` and unknown model chatter must not break validation."""
        bible = StoryBibleContent.model_validate(
            {"title": "t", "_meta": {"provider": "mock"}, "nonsense": 1}
        )
        assert bible.title == "t"


class TestRealModelFieldNormalization:
    """Regression: a live DeepSeek run used different key names than the PRD.

    The original schema was ``extra="ignore"`` with only the canonical names, so
    ``core_conflict`` / ``setting`` and ~30 other fields were silently dropped and
    ``main_conflict`` came back ``None``. The mock never caught it because the
    mock was written to emit exactly the canonical keys.
    """

    # Trimmed but structurally faithful to an actual deepseek-flash response.
    DEEPSEEK_PAYLOAD = {
        "title": "重启开学日",
        "genre": "都市",
        "style": "国漫",
        "visual_style": "国漫，写实校园都市风",
        "logline": "前世因沉迷游戏错过保研的林澈，重生回到十年前大学开学日。",
        "core_conflict": "林澈今生的改变决心与前世惰性、考研压力之间的对抗。",
        "setting": "现代都市中的大学校园，主要场景包括男生宿舍、教室、食堂。",
        "theme": "珍惜时间、自我救赎",
        "protagonist": "林澈",
        "protagonist_arc": "从悔恨与决心，到付诸行动。",
        "antagonist": "林澈自身的惰性与前世惯性。",
        "world_rules": ["林澈保留前世记忆。", "故事基底为现实都市。"],
        "timeline": ["十年前开学日清晨，林澈醒来。"],
        "important_objects": ["大学宿舍的床"],
        "important_events": ["林澈确认重生。"],
    }

    def test_main_conflict_is_recovered_from_core_conflict(self) -> None:
        bible = StoryBibleContent.model_validate(self.DEEPSEEK_PAYLOAD)
        assert bible.main_conflict is not None
        assert "前世惰性" in bible.main_conflict

    def test_background_is_recovered_from_setting(self) -> None:
        bible = StoryBibleContent.model_validate(self.DEEPSEEK_PAYLOAD)
        assert bible.background is not None
        assert "大学校园" in bible.background

    def test_no_field_is_silently_lost(self) -> None:
        """Everything the model sent must be reachable somewhere."""
        bible = StoryBibleContent.model_validate(self.DEEPSEEK_PAYLOAD)

        for field in (
            "title",
            "genre",
            "style",
            "logline",
            "main_conflict",
            "background",
            "world_rules",
            "timeline",
            "important_objects",
            "important_events",
        ):
            assert getattr(bible, field), f"{field} was dropped"

        # The rest must survive in extensions rather than vanish.
        assert bible.extensions.get("theme") == "珍惜时间、自我救赎"
        assert bible.extensions.get("protagonist") == "林澈"
        assert bible.extensions.get("visual_style") == "国漫，写实校园都市风"

    def test_model_invented_fields_are_all_preserved(self) -> None:
        """No key the model sent may vanish -- by name or by value.

        A key survives if it is a real schema field, was swept into
        ``extensions``, or had its value adopted by a canonical field
        (``core_conflict`` -> ``main_conflict``).
        """
        bible = StoryBibleContent.model_validate(self.DEEPSEEK_PAYLOAD)

        # Reverse map: alias -> the canonical field it feeds.
        alias_target = {
            alias: canonical
            for canonical, aliases in _STORY_BIBLE_ALIASES.items()
            for alias in aliases
        }

        dropped = []
        for key in self.DEEPSEEK_PAYLOAD:
            if key in type(bible).model_fields:
                continue
            if key in bible.extensions:
                continue
            target = alias_target.get(key)
            if target and getattr(bible, target):
                continue
            dropped.append(key)

        assert not dropped, f"dropped: {dropped}"

    def test_adopted_alias_value_lands_in_the_canonical_field(self) -> None:
        bible = StoryBibleContent.model_validate(self.DEEPSEEK_PAYLOAD)
        assert bible.main_conflict == self.DEEPSEEK_PAYLOAD["core_conflict"]
        assert bible.background == self.DEEPSEEK_PAYLOAD["setting"]

    def test_canonical_key_wins_over_alias(self) -> None:
        """An explicit canonical value must not be overwritten by a synonym."""
        bible = StoryBibleContent.model_validate(
            {
                "title": "t",
                "main_conflict": "正规键的值",
                "core_conflict": "别名的值",
            }
        )
        assert bible.main_conflict == "正规键的值"
        # The losing alias is still preserved, not discarded.
        assert bible.extensions.get("core_conflict") == "别名的值"

    def test_alias_normalization_avoids_a_retry(self) -> None:
        """A payload with only aliases must validate on the first attempt."""
        bible = StoryBibleContent.model_validate(
            {"story_title": "只有别名", "core_conflict": "冲突", "setting": "背景"}
        )
        assert bible.title == "只有别名"
        assert bible.main_conflict == "冲突"
        assert bible.background == "背景"

    def test_underscore_keys_are_not_swept_into_extensions(self) -> None:
        bible = StoryBibleContent.model_validate({"title": "t", "_meta": {"provider": "x"}})
        assert "_meta" not in bible.extensions

    def test_extensions_defaults_to_empty(self) -> None:
        assert StoryBibleContent.model_validate({"title": "t"}).extensions == {}

    def test_blank_alias_does_not_override(self) -> None:
        """A model that emits ``core_conflict: ""`` must not blank the field."""
        bible = StoryBibleContent.model_validate({"title": "t", "core_conflict": "  "})
        assert bible.main_conflict is None

    def test_list_aliases_are_normalized(self) -> None:
        bible = StoryBibleContent.model_validate(
            {
                "title": "t",
                "key_events": ["事件一", "事件二"],
                "plot_timeline": ["节点一"],
                "props": ["道具一"],
            }
        )
        assert bible.important_events == ["事件一", "事件二"]
        assert bible.timeline == ["节点一"]
        assert bible.important_objects == ["道具一"]


class TestCharacterDraft:
    def test_minimal_valid(self) -> None:
        character = CharacterDraft.model_validate({"name": "林澈"})
        assert character.name == "林澈"
        assert character.role.value == "SUPPORTING"

    def test_name_is_required(self) -> None:
        with pytest.raises(ValidationError):
            CharacterDraft.model_validate({"role": "PROTAGONIST"})

    def test_blank_name_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CharacterDraft.model_validate({"name": "  "})

    @pytest.mark.parametrize(
        "placeholder", ["未知", "无", "N/A", "null", "unknown", "角色", "character"]
    )
    def test_placeholder_names_are_rejected(self, placeholder: str) -> None:
        """A lazy model output should trigger a retry, not a junk character."""
        with pytest.raises(ValidationError):
            CharacterDraft.model_validate({"name": placeholder})

    def test_unknown_role_becomes_other(self) -> None:
        character = CharacterDraft.model_validate({"name": "x", "role": "SUPER_VILLAIN"})
        assert character.role.value == "OTHER"

    def test_role_aliases_are_mapped(self) -> None:
        assert (
            CharacterDraft.model_validate({"name": "x", "role": "主角"}).role.value == "PROTAGONIST"
        )
        assert CharacterDraft.model_validate({"name": "x", "role": "main"}).role.value == (
            "PROTAGONIST"
        )

    def test_role_is_case_and_separator_insensitive(self) -> None:
        character = CharacterDraft.model_validate({"name": "x", "role": "love-interest"})
        assert character.role.value == "LOVE_INTEREST"

    def test_empty_role_defaults_to_supporting(self) -> None:
        assert CharacterDraft.model_validate({"name": "x", "role": ""}).role.value == "SUPPORTING"

    def test_personality_string_is_wrapped(self) -> None:
        character = CharacterDraft.model_validate({"name": "x", "personality": "冷静"})
        assert character.personality == ["冷静"]

    def test_personality_separated_string_is_split(self) -> None:
        character = CharacterDraft.model_validate({"name": "x", "personality": "冷静、果断"})
        assert character.personality == ["冷静", "果断"]


class TestLocations:
    def test_minimal_valid(self) -> None:
        location = LocationDraft.model_validate({"name": "大学宿舍"})
        assert location.name == "大学宿舍"
        assert location.time is None

    def test_name_is_required(self) -> None:
        with pytest.raises(ValidationError):
            LocationDraft.model_validate({"description": "没有名字"})

    def test_blank_optional_fields_become_none(self) -> None:
        location = LocationDraft.model_validate({"name": "x", "time": "", "lighting": "  "})
        assert location.time is None
        assert location.lighting is None


class TestExtractionEnvelopes:
    def test_characters_are_deduped_case_insensitively(self) -> None:
        extraction = CharacterExtraction.model_validate(
            {
                "characters": [
                    {"name": "林澈", "role": "PROTAGONIST"},
                    {"name": "林澈", "role": "SUPPORTING"},
                    {"name": "苏晚"},
                ]
            }
        )
        assert [c.name for c in extraction.characters] == ["林澈", "苏晚"]

    def test_dedupe_preserves_the_first_occurrence(self) -> None:
        extraction = CharacterExtraction.model_validate(
            {"characters": [{"name": "林澈", "role": "PROTAGONIST"}, {"name": "林澈"}]}
        )
        assert extraction.characters[0].role.value == "PROTAGONIST"

    def test_sort_order_is_assigned_from_extraction_order(self) -> None:
        extraction = CharacterExtraction.model_validate(
            {"characters": [{"name": "甲"}, {"name": "乙"}, {"name": "丙"}]}
        )
        assert [c.sort_order for c in extraction.characters] == [0, 1, 2]

    def test_locations_are_deduped(self) -> None:
        extraction = LocationExtraction.model_validate(
            {"locations": [{"name": "教室"}, {"name": "教室"}, {"name": "食堂"}]}
        )
        assert [loc.name for loc in extraction.locations] == ["教室", "食堂"]

    def test_empty_extraction_is_valid(self) -> None:
        """Zero characters is a legitimate (if disappointing) result."""
        assert CharacterExtraction.model_validate({}).characters == []

    def test_too_many_characters_are_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CharacterExtraction.model_validate(
                {"characters": [{"name": f"角色{i}"} for i in range(31)]}
            )


class TestUpdateSchemas:
    def test_character_update_rejects_unknown_fields(self) -> None:
        """extra="forbid" catches client typos instead of silently ignoring them."""
        with pytest.raises(ValidationError):
            CharacterUpdate.model_validate({"nmae": "typo"})

    def test_character_update_allows_partial(self) -> None:
        update = CharacterUpdate.model_validate({"appearance": "黑色短发"})
        assert update.model_dump(exclude_unset=True) == {"appearance": "黑色短发"}

    def test_character_update_coerces_role(self) -> None:
        assert CharacterUpdate.model_validate({"role": "反派"}).role.value == "ANTAGONIST"

    def test_location_update_rejects_unknown_fields(self) -> None:
        with pytest.raises(ValidationError):
            LocationUpdate.model_validate({"nmae": "typo"})

    def test_create_schemas_share_the_draft_validators(self) -> None:
        assert CharacterCreate.model_validate({"name": " 林澈 "}).name == "林澈"
