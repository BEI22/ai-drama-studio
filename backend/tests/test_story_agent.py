"""Story Agent workflow + persistence tests (PRD sections 12, 13, 37).

Covers the graph shape demanded by PRD section 12, the state contract from
section 13, and — most importantly — that a failure is recorded rather than
leaving a half-written Bible behind.
"""

from __future__ import annotations

import re

import pytest

from app.agents import (
    EXECUTION_ORDER,
    build_story_graph,
    graph_mermaid,
    run_story_agent,
)
from app.core.exceptions import GenerationFailedError
from app.models.enums import AnalysisStatus
from app.providers.llm import MockLLMProvider

STORY = (
    "林澈在大学宿舍的床上睁开眼，发现自己竟然回到了十年前的开学日。"
    "前世他因为沉迷游戏错过保研，毕业后四处碰壁，最后在出租屋里郁郁而终。"
    "这一次，他决定改变自己的人生。室友赵明达推开宿舍门，喊他一起去食堂。"
    "林澈没有说话，只是握紧了拳头。班主任周老师走进教室，宣布了考研的报名时间。"
    "苏晚坐在他旁边的座位上，笑着说：林澈，你这次一定要加油。"
)


# --------------------------------------------------------------------------- #
# Graph shape (PRD section 12)
# --------------------------------------------------------------------------- #
class TestGraphShape:
    def test_execution_order_matches_the_prd(self) -> None:
        assert EXECUTION_ORDER == (
            "story_parser",
            "character_extractor",
            "location_extractor",
        )

    def test_graph_compiles_with_an_injected_provider(self) -> None:
        assert build_story_graph(MockLLMProvider()) is not None

    def test_mermaid_renders_the_expected_chain(self) -> None:
        mermaid = graph_mermaid(MockLLMProvider())
        assert "story_parser" in mermaid
        assert "character_extractor" in mermaid
        assert "location_extractor" in mermaid
        # The edges, not just the node names.
        assert "story_parser --> character_extractor" in mermaid
        assert "character_extractor --> location_extractor" in mermaid

    def test_media_generation_is_not_a_graph_node(self) -> None:
        """PRD section 12: image/video/TTS must not run inside this workflow."""
        mermaid = graph_mermaid(MockLLMProvider())
        for forbidden in ("image_generation", "video_generation", "tts_generation", "compose"):
            assert forbidden not in mermaid


# --------------------------------------------------------------------------- #
# Full run
# --------------------------------------------------------------------------- #
class TestRunStoryAgent:
    async def test_produces_a_complete_state(self) -> None:
        state = await run_story_agent(project_id="p1", story_text=STORY, provider=MockLLMProvider())
        assert state["story_bible"]["title"]
        assert state["characters"]
        assert state["locations"]
        assert state["current_step"] == "location_extractor"

    async def test_story_bible_has_the_prd_section_6_shape(self) -> None:
        state = await run_story_agent(project_id="p1", story_text=STORY, provider=MockLLMProvider())
        for field in (
            "title",
            "genre",
            "logline",
            "background",
            "world_rules",
            "main_conflict",
            "timeline",
            "important_objects",
            "important_events",
            "style",
        ):
            assert field in state["story_bible"], field

    async def test_extracts_the_real_characters(self) -> None:
        state = await run_story_agent(project_id="p1", story_text=STORY, provider=MockLLMProvider())
        names = [c["name"] for c in state["characters"]]
        assert "林澈" in names
        assert names[0] == "林澈"
        assert state["characters"][0]["role"] == "PROTAGONIST"

    async def test_extracts_plausible_locations(self) -> None:
        state = await run_story_agent(project_id="p1", story_text=STORY, provider=MockLLMProvider())
        names = [loc["name"] for loc in state["locations"]]
        assert "大学宿舍" in names
        assert "教室" in names
        # No junk fragments.
        assert all(len(name) >= 2 for name in names)

    async def test_every_character_has_an_image_ready_appearance(self) -> None:
        """Phase 5 will feed this straight into a text-to-image prompt."""
        state = await run_story_agent(project_id="p1", story_text=STORY, provider=MockLLMProvider())
        for character in state["characters"]:
            assert character["appearance"]
            assert character["hair"]
            assert character["clothing"]
            assert character["personality"]

    async def test_records_usage_for_every_node(self) -> None:
        """Groundwork for PRD section 26 cost tracking."""
        state = await run_story_agent(project_id="p1", story_text=STORY, provider=MockLLMProvider())
        nodes = [record["node"] for record in state["usage"]]
        assert nodes == list(EXECUTION_ORDER)
        for record in state["usage"]:
            assert record["provider"] == "mock"
            # Versioned, but not pinned to a specific number -- bumping a prompt
            # must not break this test.
            assert re.search(r"_v\d+$", record["prompt_version"]), record["prompt_version"]

    async def test_records_prompt_versions(self) -> None:
        state = await run_story_agent(project_id="p1", story_text=STORY, provider=MockLLMProvider())
        assert set(state["prompt_versions"]) == set(EXECUTION_ORDER)

    async def test_flags_mock_generation(self) -> None:
        state = await run_story_agent(project_id="p1", story_text=STORY, provider=MockLLMProvider())
        assert state["mock_generated"] is True

    async def test_state_carries_no_media_payloads(self) -> None:
        """PRD section 13: only URLs/keys may enter the state, never bytes."""
        state = await run_story_agent(project_id="p1", story_text=STORY, provider=MockLLMProvider())
        serialised = repr(state)
        assert "base64" not in serialised
        assert "data:image" not in serialised

    async def test_project_and_episode_ids_are_preserved(self) -> None:
        state = await run_story_agent(
            project_id="proj-1", story_text=STORY, provider=MockLLMProvider()
        )
        assert state["project_id"] == "proj-1"

    async def test_short_story_still_produces_something(self) -> None:
        """The API gates on length; the agent itself should not crash."""
        state = await run_story_agent(
            project_id="p1", story_text="他站了起来。", provider=MockLLMProvider()
        )
        assert state["story_bible"]["title"]
        assert state["characters"]

    async def test_provider_failure_propagates(self) -> None:
        class Broken(MockLLMProvider):
            async def generate(self, request):  # type: ignore[override]
                from app.core.exceptions import ProviderError

                raise ProviderError("boom")

        with pytest.raises(GenerationFailedError):
            await run_story_agent(project_id="p1", story_text=STORY, provider=Broken())


# --------------------------------------------------------------------------- #
# Persistence (PRD section 37 items 12-13)
# --------------------------------------------------------------------------- #
class TestAgentServicePersistence:
    @pytest.fixture
    def project(self, db):
        from app.core.security import hash_password
        from app.models.project import Project
        from app.models.user import User

        user = User(email="writer@example.com", password_hash=hash_password("storytime2026"))
        db.add(user)
        db.flush()
        project = Project(user_id=user.id, name="重生", story_text=STORY)
        db.add(project)
        db.commit()
        db.refresh(project)
        return project

    async def test_analysis_persists_everything(self, db, project) -> None:
        from app.repositories.character import CharacterRepository
        from app.repositories.location import LocationRepository
        from app.services.agent_service import AgentService

        await AgentService(db, provider=MockLLMProvider()).analyze(project)

        assert project.analysis_status == AnalysisStatus.SUCCEEDED.value
        assert project.story_bible_json["title"]
        assert project.analyzed_at is not None
        assert CharacterRepository(db).count_for_project(project.id) >= 3
        assert LocationRepository(db).count_for_project(project.id) >= 3

    async def test_bible_records_its_provenance(self, db, project) -> None:
        from app.services.agent_service import AgentService

        await AgentService(db, provider=MockLLMProvider()).analyze(project)

        meta = project.story_bible_json["_meta"]
        assert meta["provider"] == "mock"
        assert meta["mock"] is True
        assert meta["prompt_versions"]["story_parser"] == "story_parser_v2"
        assert len(meta["usage"]) == 3

    async def test_characters_keep_their_extraction_order(self, db, project) -> None:
        from app.repositories.character import CharacterRepository
        from app.services.agent_service import AgentService

        await AgentService(db, provider=MockLLMProvider()).analyze(project)
        rows = CharacterRepository(db).list_for_project(project.id)
        assert [row.sort_order for row in rows] == sorted(row.sort_order for row in rows)
        assert rows[0].name == "林澈"

    async def test_second_run_without_replace_is_refused(self, db, project) -> None:
        """Guards against silently doubling the cast."""
        from app.core.exceptions import ConflictError
        from app.services.agent_service import AgentService

        service = AgentService(db, provider=MockLLMProvider())
        await service.analyze(project)

        with pytest.raises(ConflictError, match="replace=true"):
            await service.analyze(project)

    async def test_second_run_with_replace_does_not_duplicate(self, db, project) -> None:
        from app.repositories.character import CharacterRepository
        from app.services.agent_service import AgentService

        service = AgentService(db, provider=MockLLMProvider())
        await service.analyze(project)
        first = CharacterRepository(db).count_for_project(project.id)

        await service.analyze(project, replace=True)
        assert CharacterRepository(db).count_for_project(project.id) == first

    async def test_short_story_is_rejected(self, db, project) -> None:
        from app.core.exceptions import ValidationError
        from app.services.agent_service import AgentService

        project.story_text = "太短"
        db.commit()

        with pytest.raises(ValidationError, match="过短"):
            await AgentService(db, provider=MockLLMProvider()).analyze(project)

    async def test_invalidated_analysis_can_be_re_run_without_replace(self, db, project) -> None:
        """Regression: the conflict guard used to key off row count.

        Saving a new story resets the status to NOT_ANALYZED but leaves the old
        cast in place, so a row-count guard wrongly refused the next run with
        "already analyzed, pass replace=true". The guard must follow the status.
        """
        from app.services.agent_service import AgentService

        service = AgentService(db, provider=MockLLMProvider())
        await service.analyze(project)

        # Simulate the API's story-write invalidating the analysis.
        project.analysis_status = AnalysisStatus.NOT_ANALYZED.value
        db.commit()

        # Must not raise, even though character rows still exist.
        await service.analyze(project)
        assert project.analysis_status == AnalysisStatus.SUCCEEDED.value

    async def test_invalidated_re_run_drops_the_stale_cast(self, db, project) -> None:
        """A changed story must not leave characters from the old one behind."""
        from app.repositories.character import CharacterRepository
        from app.services.agent_service import AgentService

        service = AgentService(db, provider=MockLLMProvider())
        await service.analyze(project)

        stale = service.characters.create(project_id=project.id, name="旧故事的幽灵", role="OTHER")
        db.commit()
        stale_id = stale.id

        project.analysis_status = AnalysisStatus.NOT_ANALYZED.value
        db.commit()
        await service.analyze(project)

        assert CharacterRepository(db).get(stale_id) is None

    async def test_failed_analysis_can_be_retried_without_replace(self, db, project) -> None:
        from app.services.agent_service import AgentService

        project.analysis_status = AnalysisStatus.FAILED.value
        project.analysis_error = "previous run blew up"
        db.commit()

        await AgentService(db, provider=MockLLMProvider()).analyze(project)
        assert project.analysis_status == AnalysisStatus.SUCCEEDED.value
        assert project.analysis_error is None

    async def test_missing_story_is_rejected(self, db, project) -> None:
        from app.core.exceptions import ValidationError
        from app.services.agent_service import AgentService

        project.story_text = None
        db.commit()

        with pytest.raises(ValidationError):
            await AgentService(db, provider=MockLLMProvider()).analyze(project)

    async def test_unsaved_story_text_can_be_analyzed(self, db, project) -> None:
        """``POST /analyze {story_text}`` previews without touching the project."""
        from app.services.agent_service import AgentService

        project.story_text = None
        db.commit()

        await AgentService(db, provider=MockLLMProvider()).analyze(project, story_text=STORY)
        assert project.story_bible_json["title"]
        assert project.story_text is None

    async def test_failure_is_recorded_and_nothing_is_written(self, db, project) -> None:
        from app.repositories.character import CharacterRepository
        from app.services.agent_service import AgentService

        class Broken(MockLLMProvider):
            async def generate(self, request):  # type: ignore[override]
                from app.core.exceptions import ProviderError

                raise ProviderError("provider exploded")

        with pytest.raises(GenerationFailedError):
            await AgentService(db, provider=Broken()).analyze(project)

        db.refresh(project)
        assert project.analysis_status == AnalysisStatus.FAILED.value
        assert "provider exploded" in (project.analysis_error or "")
        assert project.story_bible_json is None
        assert CharacterRepository(db).count_for_project(project.id) == 0

    async def test_status_reports_counts(self, db, project) -> None:
        from app.services.agent_service import AgentService

        service = AgentService(db, provider=MockLLMProvider())
        before = service.status(project)
        assert before["analysis_status"] == AnalysisStatus.NOT_ANALYZED.value
        assert before["characters"] == 0
        assert before["provider"] == "mock"

        await service.analyze(project)
        after = service.status(project)
        assert after["analysis_status"] == AnalysisStatus.SUCCEEDED.value
        assert after["characters"] >= 3

    async def test_hand_edits_survive_reanalysis(self, db, project) -> None:
        """A user who fixed an appearance shouldn't lose it when re-running.

        ``replace=True`` upserts by name instead of wiping the cast, so the row
        (and its id) survives.
        """
        from app.repositories.character import CharacterRepository
        from app.services.agent_service import AgentService

        service = AgentService(db, provider=MockLLMProvider())
        await service.analyze(project)

        rows = CharacterRepository(db).list_for_project(project.id)
        hero = rows[0]
        hero_id = hero.id
        hero.appearance = "用户手改过的外貌描述"
        db.commit()

        await service.analyze(project, replace=True)
        db.refresh(hero)
        assert hero.appearance == "用户手改过的外貌描述"
        assert hero.id == hero_id

    async def test_replace_removes_rows_the_agent_no_longer_produces(self, db, project) -> None:
        from app.repositories.character import CharacterRepository
        from app.services.agent_service import AgentService

        service = AgentService(db, provider=MockLLMProvider())
        await service.analyze(project)

        # A character the agent will not find in the shorter story.
        stale = service.characters.create(project_id=project.id, name="幽灵角色", role="OTHER")
        db.commit()
        stale_id = stale.id

        await service.analyze(project, replace=True)

        assert CharacterRepository(db).get(stale_id) is None
        assert CharacterRepository(db).get_by_name(project.id, "林澈") is not None
