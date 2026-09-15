"""LLM provider + structured-output tests (PRD sections 16, 20, 37 items 6-11).

Two things matter here and are both covered directly:

1. **Provider decoupling** -- selection is driven purely by configuration and the
   agents only ever see the ``LLMProvider`` interface.
2. **Validation + retry** -- malformed model output must be retried with the
   concrete error fed back, and must eventually fail loudly rather than persist
   garbage.
"""

from __future__ import annotations

import json

import pytest

from app.agents.structured import extract_json, generate_structured
from app.core.config import Settings
from app.core.exceptions import (
    GenerationFailedError,
    ProviderError,
    UnsupportedError,
)
from app.providers.base import LLMProvider, LLMRequest, LLMResult
from app.providers.llm import (
    MockLLMProvider,
    OpenAICompatibleLLMProvider,
    build_llm_provider,
)
from app.providers.llm.openai_compatible import is_healthy_status
from app.schemas.bible import CharacterExtraction, StoryBibleContent
from app.utils.prompts import PROMPTS_DIR, clear_cache, load_prompt, prompt_version


# --------------------------------------------------------------------------- #
# Test doubles
# --------------------------------------------------------------------------- #
class ScriptedProvider(LLMProvider):
    """Returns a preset sequence of responses, recording the prompts it saw.

    State lives in underscore-prefixed attributes because ``LLMProvider`` is a
    Pydantic model and rejects arbitrary public fields.
    """

    name: str = "scripted"

    def __init__(self, responses: list[str], *, fail_times: int = 0) -> None:
        super().__init__(name="scripted", model="scripted-v1")
        self._responses = responses
        self._fail_times = fail_times
        self._prompts: list[str] = []
        self._schemas: list[dict | None] = []

    @property
    def prompts(self) -> list[str]:
        return self._prompts

    @property
    def schemas(self) -> list[dict | None]:
        return self._schemas

    async def health(self) -> bool:
        return True

    async def generate(self, request: LLMRequest) -> LLMResult:
        self._prompts.append(request.prompt)
        self._schemas.append(request.json_schema)
        if len(self._prompts) <= self._fail_times:
            from app.core.exceptions import ProviderError

            raise ProviderError("scripted transport failure")
        index = min(len(self._prompts) - 1, len(self._responses) - 1)
        return LLMResult(text=self._responses[index], model="scripted-v1")


# --------------------------------------------------------------------------- #
# Provider selection (PRD section 16)
# --------------------------------------------------------------------------- #
class TestProviderSelection:
    def test_suite_is_hermetic(self) -> None:
        """Guard: the suite must never depend on the developer's .env.

        ``Settings`` reads the repository ``.env``, so wiring a real vendor there
        (e.g. DeepSeek) leaked into the tests and made them call that API. With a
        real key present they hung on network I/O; without one they failed. This
        asserts the pinning in ``conftest`` holds, so the failure mode can't
        quietly return.
        """
        from app.core.config import settings as test_settings

        assert test_settings.llm_provider == "mock"
        assert test_settings.llm_api_key == ""
        # Unroutable, so an accidental real call fails fast instead of hanging.
        assert test_settings.llm_base_url == "http://127.0.0.1:9/v1"

    def test_default_is_mock(self) -> None:
        provider = build_llm_provider(Settings())
        assert isinstance(provider, MockLLMProvider)
        assert provider.name == "mock"

    def test_openai_requires_an_api_key(self) -> None:
        """Fail at selection time, not on the first user request."""
        with pytest.raises(UnsupportedError, match="LLM_API_KEY"):
            build_llm_provider(Settings(llm_provider="openai"))

    def test_openai_builds_with_a_key(self) -> None:
        provider = build_llm_provider(
            Settings(llm_provider="openai", llm_api_key="sk-test", llm_model="deepseek-chat")
        )
        assert isinstance(provider, OpenAICompatibleLLMProvider)
        assert provider.model == "deepseek-chat"

    def test_unknown_provider_is_rejected(self) -> None:
        with pytest.raises(UnsupportedError, match="未知的 LLM_PROVIDER"):
            build_llm_provider(Settings(llm_provider="skynet"))

    def test_provider_name_is_case_insensitive(self) -> None:
        assert isinstance(build_llm_provider(Settings(llm_provider="MOCK")), MockLLMProvider)

    def test_singleton_is_cached_and_resettable(self) -> None:
        from app.providers.llm import get_llm_provider, reset_llm_provider

        first = get_llm_provider()
        assert get_llm_provider() is first, "expected the same cached instance"

        reset_llm_provider()
        assert get_llm_provider() is not first, "expected a rebuilt instance"

    def test_agents_depend_only_on_the_interface(self) -> None:
        """No business module may import a vendor SDK."""
        assert isinstance(MockLLMProvider(), LLMProvider)
        assert isinstance(
            OpenAICompatibleLLMProvider(api_key="k", base_url="http://x", model="m"),
            LLMProvider,
        )


class TestProviderHealthStatus:
    """Regression: ``status < 500`` reported a rejected API key as healthy."""

    @pytest.mark.parametrize("status", [200, 201, 204, 299])
    def test_success_is_healthy(self, status: int) -> None:
        assert is_healthy_status(status) is True

    @pytest.mark.parametrize("status", [401, 403])
    def test_auth_failure_is_unhealthy(self, status: int) -> None:
        """A bad key makes the provider useless, so it must not read as green."""
        assert is_healthy_status(status) is False

    @pytest.mark.parametrize("status", [404, 405, 501])
    def test_missing_models_route_still_counts_as_reachable(self, status: int) -> None:
        """Not every compatible endpoint implements GET /models."""
        assert is_healthy_status(status) is True

    @pytest.mark.parametrize("status", [429, 500, 502, 503])
    def test_server_and_throttle_faults_are_unhealthy(self, status: int) -> None:
        assert is_healthy_status(status) is False

    async def test_health_is_false_without_a_key(self) -> None:
        provider = OpenAICompatibleLLMProvider(api_key="", base_url="http://x", model="m")
        assert await provider.health() is False


# --------------------------------------------------------------------------- #
# JSON extraction
# --------------------------------------------------------------------------- #
class TestExtractJson:
    def test_bare_object(self) -> None:
        assert extract_json('{"a": 1}') == {"a": 1}

    def test_fenced_object(self) -> None:
        assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}

    def test_untagged_fence(self) -> None:
        assert extract_json('```\n{"a": 1}\n```') == {"a": 1}

    def test_object_buried_in_prose(self) -> None:
        text = '当然，这是结果：\n{"a": 1}\n希望有帮助！'
        assert extract_json(text) == {"a": 1}

    def test_trailing_commentary_after_object(self) -> None:
        assert extract_json('{"a": 1}\n\n以上是分析结果。') == {"a": 1}

    def test_array(self) -> None:
        assert extract_json("[1, 2]") == [1, 2]

    def test_empty_input_raises(self) -> None:
        with pytest.raises(ValueError, match="为空"):
            extract_json("")

    def test_unparseable_input_raises(self) -> None:
        with pytest.raises(ValueError, match="无法从 LLM 输出中解析"):
            extract_json("这本书讲了一个很好的故事。")

    def test_nested_object_is_preserved(self) -> None:
        payload = {"characters": [{"name": "林澈", "personality": ["冷静"]}]}
        assert extract_json(json.dumps(payload, ensure_ascii=False)) == payload


# --------------------------------------------------------------------------- #
# Validation + retry (PRD section 6, 37 item 11)
# --------------------------------------------------------------------------- #
class TestGenerateStructured:
    async def test_first_attempt_success(self) -> None:
        provider = ScriptedProvider(['{"title": "重生"}'])
        model, result = await generate_structured(
            provider, LLMRequest(prompt="p"), StoryBibleContent
        )
        assert model.title == "重生"
        assert result.text
        assert len(provider.prompts) == 1

    async def test_schema_is_always_advertised_to_the_provider(self) -> None:
        provider = ScriptedProvider(['{"title": "t"}'])
        await generate_structured(provider, LLMRequest(prompt="p"), StoryBibleContent)
        schema = provider.schemas[0]
        assert schema is not None and schema["title"] == "StoryBibleContent"

    async def test_malformed_then_valid_retries(self) -> None:
        provider = ScriptedProvider(["这不是 JSON", '{"title": "重生"}'])
        model, _ = await generate_structured(
            provider, LLMRequest(prompt="原始提示"), StoryBibleContent
        )
        assert model.title == "重生"
        assert len(provider.prompts) == 2

    async def test_retry_prompt_contains_the_validation_error(self) -> None:
        """Blindly resending the same prompt rarely helps; the error is the point."""
        provider = ScriptedProvider(["{}", '{"title": "t"}'])
        await generate_structured(provider, LLMRequest(prompt="原始提示"), StoryBibleContent)

        retry_prompt = provider.prompts[1]
        assert retry_prompt.startswith("原始提示")
        assert "上一次输出无法通过校验" in retry_prompt
        assert "title" in retry_prompt  # the missing field is named

    async def test_retry_prompt_includes_the_json_schema(self) -> None:
        provider = ScriptedProvider(["{}", '{"title": "t"}'])
        await generate_structured(provider, LLMRequest(prompt="p"), StoryBibleContent)
        assert "json" in provider.prompts[1].lower()

    async def test_persistent_failure_raises_generation_failed(self) -> None:
        provider = ScriptedProvider(["{}", "{}", "{}"])
        with pytest.raises(GenerationFailedError) as excinfo:
            await generate_structured(
                provider, LLMRequest(prompt="p"), StoryBibleContent, max_retries=3
            )
        assert excinfo.value.details["attempts"] == 3
        assert len(provider.prompts) == 3

    async def test_transport_errors_are_retried_too(self) -> None:
        provider = ScriptedProvider(['{"title": "重生"}'], fail_times=2)
        model, _ = await generate_structured(
            provider, LLMRequest(prompt="p"), StoryBibleContent, max_retries=3
        )
        assert model.title == "重生"
        assert len(provider.prompts) == 3

    async def test_transport_error_alone_raises_generation_failed(self) -> None:
        provider = ScriptedProvider(['{"title": "t"}'], fail_times=5)
        with pytest.raises(GenerationFailedError):
            await generate_structured(
                provider, LLMRequest(prompt="p"), StoryBibleContent, max_retries=2
            )

    async def test_max_retries_is_respected(self) -> None:
        provider = ScriptedProvider(["x"])
        with pytest.raises(GenerationFailedError):
            await generate_structured(
                provider, LLMRequest(prompt="p"), StoryBibleContent, max_retries=1
            )
        assert len(provider.prompts) == 1

    async def test_fenced_json_is_accepted(self) -> None:
        provider = ScriptedProvider(['```json\n{"title": "fenced"}\n```'])
        model, _ = await generate_structured(provider, LLMRequest(prompt="p"), StoryBibleContent)
        assert model.title == "fenced"

    async def test_coercion_avoids_a_pointless_retry(self) -> None:
        """Cosmetic variance should not cost an extra model call."""
        provider = ScriptedProvider(['{"characters": [{"name": "林澈", "personality": "冷静"}]}'])
        model, _ = await generate_structured(provider, LLMRequest(prompt="p"), CharacterExtraction)
        assert len(provider.prompts) == 1
        assert model.characters[0].personality == ["冷静"]


# --------------------------------------------------------------------------- #
# Mock provider (PRD section 37 item 8)
# --------------------------------------------------------------------------- #
STORY = (
    "林澈在大学宿舍的床上睁开眼，发现自己竟然回到了十年前的开学日。"
    "前世他因为沉迷游戏错过保研，毕业后四处碰壁，最后在出租屋里郁郁而终。"
    "这一次，他决定改变自己的人生。室友赵明达推开宿舍门，喊他一起去食堂。"
    "林澈没有说话，只是握紧了拳头。班主任周老师走进教室，宣布了考研的报名时间。"
    "苏晚坐在他旁边的座位上，笑着说：林澈，你这次一定要加油。"
)


class TestMockProvider:
    async def test_is_deterministic_across_instances(self) -> None:
        """Same input must produce byte-identical output, or tests are flaky."""
        request = LLMRequest(
            prompt=f"<story>{STORY}</story>",
            json_schema=StoryBibleContent.model_json_schema(),
        )
        first = await MockLLMProvider().generate(request)
        second = await MockLLMProvider().generate(request)
        assert first.text == second.text

    async def test_health_is_true_without_network(self) -> None:
        assert await MockLLMProvider().health() is True

    async def test_fail_times_then_succeed(self) -> None:
        provider = MockLLMProvider(fail_times=2)
        request = LLMRequest(
            prompt="<story>x</story>", json_schema={"title": "CharacterExtraction"}
        )
        for _ in range(2):
            with pytest.raises(ProviderError):
                await provider.generate(request)
        assert await provider.generate(request)

    async def test_unknown_schema_is_an_error(self) -> None:
        from app.core.exceptions import ProviderError

        with pytest.raises(ProviderError, match="不支持"):
            await MockLLMProvider().generate(
                LLMRequest(prompt="x", json_schema={"title": "SomethingElse"})
            )

    async def test_call_count_is_tracked(self) -> None:
        provider = MockLLMProvider()
        request = LLMRequest(
            prompt="<story>x</story>", json_schema={"title": "CharacterExtraction"}
        )
        await provider.generate(request)
        await provider.generate(request)
        assert provider.calls == 2

    async def test_reports_zero_cost(self) -> None:
        """Mock usage must never inflate the cost ledger (PRD section 26)."""
        result = await MockLLMProvider().generate(
            LLMRequest(prompt="<story>x</story>", json_schema={"title": "CharacterExtraction"})
        )
        assert result.estimated_cost == 0.0

    async def test_output_is_marked_as_mock(self) -> None:
        result = await MockLLMProvider().generate(
            LLMRequest(prompt="<story>x</story>", json_schema={"title": "CharacterExtraction"})
        )
        assert json.loads(result.text)["_mock"] is True


class TestHeuristics:
    """The deterministic rules behind the mock -- pinned so regressions show up."""

    def test_surname_anchoring_rejects_verbs(self) -> None:
        from app.providers.llm import heuristics as h

        names = h.extract_names("林澈没有说话，苏晚笑着说好的。")
        assert "澈没有" not in names
        assert "笑着" not in names

    def test_common_words_are_not_names(self) -> None:
        """宿舍门 / 游戏错 / 班主任 start with surname characters but are words."""
        from app.providers.llm import heuristics as h

        text = "他沉迷游戏错过保研。室友赵明达推开宿舍门。班主任周老师走进教室。"
        names = h.extract_names(text)
        assert "游戏错" not in names
        assert "宿舍门" not in names
        assert "赵明达" in names

    def test_protagonist_ranks_first_by_mentions(self) -> None:
        from app.providers.llm import heuristics as h

        names = h.extract_names(STORY)
        assert names[0] == "林澈"

    def test_real_characters_are_found(self) -> None:
        from app.providers.llm import heuristics as h

        names = h.extract_names(STORY)
        assert {"林澈", "赵明达", "苏晚"} <= set(names)

    def test_locations_prefer_the_compound(self) -> None:
        from app.providers.llm import heuristics as h

        locations = h.extract_locations("林澈在大学宿舍的床上睁开眼。")
        assert locations == ["大学宿舍"]

    def test_locations_do_not_duplicate_by_containment(self) -> None:
        from app.providers.llm import heuristics as h

        locations = h.extract_locations(STORY)
        assert "宿舍" not in locations
        assert "大学宿舍" in locations

    def test_regression_story_is_detected(self) -> None:
        from app.providers.llm import heuristics as h

        assert h.infer_genre(STORY) == "都市重生"

    def test_explicit_hint_wins_over_inference(self) -> None:
        from app.providers.llm import heuristics as h

        assert h.infer_genre("随便一段文本", "武侠") == "武侠"

    def test_time_and_lighting_are_matched(self) -> None:
        from app.providers.llm import heuristics as h

        assert h.match_time("清晨，他走向教室") == "清晨"
        assert h.match_lighting("月光洒在桌面上") == "清冷月光"


# --------------------------------------------------------------------------- #
# Prompts (PRD section 20)
# --------------------------------------------------------------------------- #
class TestPrompts:
    def test_prompts_live_outside_python(self) -> None:
        assert PROMPTS_DIR.exists()
        assert (PROMPTS_DIR / "story").exists()

    def test_prompts_are_versioned(self) -> None:
        for name in (
            "story/story_parser_v1",
            "story/story_parser_v2",
            "story/character_extractor_v1",
            "story/location_extractor_v1",
        ):
            assert prompt_version(name).endswith(("_v1", "_v2"))

    def test_v2_story_parser_pins_the_canonical_key_names(self) -> None:
        """v2 exists because a live model invented its own key names.

        The prompt must therefore name the exact keys it expects.
        """
        prompt = load_prompt("story/story_parser_v2")
        text = f"{prompt.system}\n{prompt.user_template}"
        for key in (
            "title",
            "genre",
            "logline",
            "background",
            "main_conflict",
            "style",
            "world_rules",
            "timeline",
            "important_objects",
            "important_events",
        ):
            assert key in text, f"v2 prompt never mentions {key}"

    def test_v2_keeps_the_same_placeholders_as_v1(self) -> None:
        """A version bump must not silently change the call signature."""
        v1 = load_prompt("story/story_parser_v1")
        v2 = load_prompt("story/story_parser_v2")
        assert set(v2.placeholders) == set(v1.placeholders)
        assert v1.version != v2.version

    def test_load_splits_system_and_user(self) -> None:
        prompt = load_prompt("story/story_parser_v1")
        assert prompt.system
        assert "{story_text}" in prompt.user_template

    def test_render_substitutes_placeholders(self) -> None:
        prompt = load_prompt("story/story_parser_v1")
        system, user = prompt.render(story_text="一个故事", genre="都市", style="国漫")
        assert system
        assert "一个故事" in user
        assert "{story_text}" not in user

    def test_missing_placeholder_raises(self) -> None:
        """A prompt typo must fail loudly rather than send `{story_text}` to the LLM."""
        prompt = load_prompt("story/story_parser_v1")
        with pytest.raises(KeyError):
            prompt.render(story_text="x")

    def test_unknown_prompt_raises_not_found(self) -> None:
        from app.core.exceptions import NotFoundError

        with pytest.raises(NotFoundError):
            load_prompt("story/does_not_exist")

    def test_cache_can_be_cleared(self) -> None:
        first = load_prompt("story/story_parser_v1")
        clear_cache()
        assert load_prompt("story/story_parser_v1").version == first.version
