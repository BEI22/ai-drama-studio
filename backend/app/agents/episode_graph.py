"""Episode Agent graph (PRD sections 12, 38 -- Phase 4).

PRD section 12 draws one linear pipeline::

    START -> story_parser -> character_extractor -> location_extractor
          -> episode_planner -> script_generator -> storyboard_generator
          -> consistency_checker -> END

Phases 3 and 4 implement that chain as **three runnable segments**, because the
API contract in PRD section 22 is per-episode and per-step::

    POST /projects/{id}/analyze                  story_parser -> character_extractor
                                                 -> location_extractor      (Phase 3)
    POST /projects/{id}/episodes/plan            episode_planner            (Phase 4)
    POST /episodes/{id}/script/generate          script_generator           (Phase 4)
    POST /episodes/{id}/storyboard/generate      storyboard_generator
                                                 -> consistency_checker     (Phase 4)

Running the whole chain in one request would mean re-parsing the story, re-deep
planning and re-writing every episode each time a single episode's storyboard is
regenerated -- and PRD section 37's "one phase at a time" work still has to leave
Phase 3's endpoint behaving exactly as it did.

:func:`build_full_graph` assembles the *complete* section 12 pipeline in one
graph, which is what :func:`graph_mermaid` renders and what the docs describe.
It is not wired to a synchronous HTTP route: it needs an episode to exist first,
which is exactly why the API is segmented.
"""

from __future__ import annotations

import logging
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.agents.episode_nodes import (
    make_consistency_checker_node,
    make_episode_planner_node,
    make_script_generator_node,
    make_storyboard_generator_node,
)
from app.agents.nodes import (
    make_character_extractor_node,
    make_location_extractor_node,
    make_story_parser_node,
)
from app.agents.state import StoryState
from app.providers.base import LLMProvider
from app.providers.llm.factory import get_llm_provider

logger = logging.getLogger(__name__)

# Phase 4 node names, exported so callers/tests don't hardcode strings.
NODE_EPISODE_PLANNER = "episode_planner"
NODE_SCRIPT_GENERATOR = "script_generator"
NODE_STORYBOARD_GENERATOR = "storyboard_generator"
NODE_CONSISTENCY_CHECKER = "consistency_checker"

EPISODE_EXECUTION_ORDER = (
    NODE_EPISODE_PLANNER,
    NODE_SCRIPT_GENERATOR,
    NODE_STORYBOARD_GENERATOR,
    NODE_CONSISTENCY_CHECKER,
)

# The complete PRD section 12 pipeline, in order.
FULL_EXECUTION_ORDER = (
    "story_parser",
    "character_extractor",
    "location_extractor",
    *EPISODE_EXECUTION_ORDER,
)


def build_episode_graph(provider: LLMProvider | None = None):
    """Compile the four Phase 4 nodes in PRD section 12's order.

    ``episode_planner -> script_generator -> storyboard_generator
    -> consistency_checker``
    """
    active = provider or get_llm_provider()

    graph = StateGraph(StoryState)
    graph.add_node(NODE_EPISODE_PLANNER, make_episode_planner_node(active))
    graph.add_node(NODE_SCRIPT_GENERATOR, make_script_generator_node(active))
    graph.add_node(NODE_STORYBOARD_GENERATOR, make_storyboard_generator_node(active))
    graph.add_node(NODE_CONSISTENCY_CHECKER, make_consistency_checker_node())

    graph.add_edge(START, NODE_EPISODE_PLANNER)
    graph.add_edge(NODE_EPISODE_PLANNER, NODE_SCRIPT_GENERATOR)
    graph.add_edge(NODE_SCRIPT_GENERATOR, NODE_STORYBOARD_GENERATOR)
    graph.add_edge(NODE_STORYBOARD_GENERATOR, NODE_CONSISTENCY_CHECKER)
    graph.add_edge(NODE_CONSISTENCY_CHECKER, END)

    return graph.compile()


def build_planner_graph(provider: LLMProvider | None = None):
    """``episode_planner`` alone -- the project-level planning endpoint."""
    active = provider or get_llm_provider()

    graph = StateGraph(StoryState)
    graph.add_node(NODE_EPISODE_PLANNER, make_episode_planner_node(active))
    graph.add_edge(START, NODE_EPISODE_PLANNER)
    graph.add_edge(NODE_EPISODE_PLANNER, END)
    return graph.compile()


def build_script_graph(provider: LLMProvider | None = None):
    """``script_generator`` alone -- the per-episode script endpoint."""
    active = provider or get_llm_provider()

    graph = StateGraph(StoryState)
    graph.add_node(NODE_SCRIPT_GENERATOR, make_script_generator_node(active))
    graph.add_edge(START, NODE_SCRIPT_GENERATOR)
    graph.add_edge(NODE_SCRIPT_GENERATOR, END)
    return graph.compile()


def build_storyboard_graph(provider: LLMProvider | None = None):
    """``storyboard_generator -> consistency_checker`` -- the storyboard endpoint."""
    active = provider or get_llm_provider()

    graph = StateGraph(StoryState)
    graph.add_node(NODE_STORYBOARD_GENERATOR, make_storyboard_generator_node(active))
    graph.add_node(NODE_CONSISTENCY_CHECKER, make_consistency_checker_node())
    graph.add_edge(START, NODE_STORYBOARD_GENERATOR)
    graph.add_edge(NODE_STORYBOARD_GENERATOR, NODE_CONSISTENCY_CHECKER)
    graph.add_edge(NODE_CONSISTENCY_CHECKER, END)
    return graph.compile()


def build_full_graph(provider: LLMProvider | None = None):
    """The complete PRD section 12 pipeline as one graph (docs / inspection).

    Spans Phases 3 and 4: the three story nodes plus the four episode nodes.
    """
    active = provider or get_llm_provider()

    graph = StateGraph(StoryState)
    graph.add_node("story_parser", make_story_parser_node(active))
    graph.add_node("character_extractor", make_character_extractor_node(active))
    graph.add_node("location_extractor", make_location_extractor_node(active))
    graph.add_node(NODE_EPISODE_PLANNER, make_episode_planner_node(active))
    graph.add_node(NODE_SCRIPT_GENERATOR, make_script_generator_node(active))
    graph.add_node(NODE_STORYBOARD_GENERATOR, make_storyboard_generator_node(active))
    graph.add_node(NODE_CONSISTENCY_CHECKER, make_consistency_checker_node())

    graph.add_edge(START, "story_parser")
    graph.add_edge("story_parser", "character_extractor")
    graph.add_edge("character_extractor", "location_extractor")
    graph.add_edge("location_extractor", NODE_EPISODE_PLANNER)
    graph.add_edge(NODE_EPISODE_PLANNER, NODE_SCRIPT_GENERATOR)
    graph.add_edge(NODE_SCRIPT_GENERATOR, NODE_STORYBOARD_GENERATOR)
    graph.add_edge(NODE_STORYBOARD_GENERATOR, NODE_CONSISTENCY_CHECKER)
    graph.add_edge(NODE_CONSISTENCY_CHECKER, END)

    return graph.compile()


def _initial_state(
    *,
    project_id: str,
    story_text: str,
    genre: str | None,
    style: str | None,
    project_name: str | None,
    episode_id: str | None = None,
    story_bible: dict[str, Any] | None = None,
    characters: list[dict[str, Any]] | None = None,
    locations: list[dict[str, Any]] | None = None,
    episode_plan: dict[str, Any] | None = None,
    script: dict[str, Any] | None = None,
    episode_count: int | None = None,
    provider: LLMProvider | None = None,
) -> StoryState:
    state: StoryState = {
        "project_id": project_id,
        "story": {
            "story_text": story_text,
            "genre": genre,
            "style": style,
            "project_name": project_name,
            "episode_count": episode_count,
        },
        "errors": [],
        "usage": [],
        "prompt_versions": {},
        "mock_generated": bool(provider and provider.name == "mock"),
    }
    if episode_id:
        state["episode_id"] = episode_id
    if story_bible:
        state["story_bible"] = story_bible
    if characters:
        state["characters"] = characters
    if locations:
        state["locations"] = locations
    if episode_plan:
        state["episode_plan"] = episode_plan
    if script:
        state["script"] = script
    return state


async def run_episode_planner(
    *,
    project_id: str,
    story_text: str,
    story_bible: dict[str, Any],
    characters: list[dict[str, Any]],
    locations: list[dict[str, Any]],
    genre: str | None = None,
    style: str | None = None,
    episode_count: int | None = None,
    provider: LLMProvider | None = None,
) -> StoryState:
    """Run the planner alone: story -> episode outline."""
    active = provider or get_llm_provider()
    initial = _initial_state(
        project_id=project_id,
        story_text=story_text,
        genre=genre,
        style=style,
        project_name=None,
        story_bible=story_bible,
        characters=characters,
        locations=locations,
        episode_count=episode_count,
        provider=active,
    )

    graph = build_planner_graph(active)
    final = await graph.ainvoke(initial)
    logger.info(
        "episode planner finished for project %s (%d episodes)",
        project_id,
        len((final.get("episode_plan") or {}).get("episodes") or []),
    )
    return final


async def run_script_generator(
    *,
    project_id: str,
    episode_id: str,
    episode_plan: dict[str, Any],
    story_bible: dict[str, Any],
    characters: list[dict[str, Any]],
    locations: list[dict[str, Any]],
    story_text: str = "",
    genre: str | None = None,
    style: str | None = None,
    provider: LLMProvider | None = None,
) -> StoryState:
    """Run the script generator for one episode."""
    active = provider or get_llm_provider()
    initial = _initial_state(
        project_id=project_id,
        story_text=story_text,
        genre=genre,
        style=style,
        project_name=None,
        episode_id=episode_id,
        story_bible=story_bible,
        characters=characters,
        locations=locations,
        episode_plan=episode_plan,
        provider=active,
    )
    final = await build_script_graph(active).ainvoke(initial)
    logger.info(
        "script generator finished for episode %s (%d scenes)",
        episode_id,
        len((final.get("script") or {}).get("scenes") or []),
    )
    return final


async def run_storyboard_generator(
    *,
    project_id: str,
    episode_id: str,
    script: dict[str, Any],
    story_bible: dict[str, Any],
    characters: list[dict[str, Any]],
    locations: list[dict[str, Any]],
    episode_plan: dict[str, Any] | None = None,
    story_text: str = "",
    genre: str | None = None,
    style: str | None = None,
    provider: LLMProvider | None = None,
) -> StoryState:
    """Run the storyboard generator + consistency checker for one episode."""
    active = provider or get_llm_provider()
    initial = _initial_state(
        project_id=project_id,
        story_text=story_text,
        genre=genre,
        style=style,
        project_name=None,
        episode_id=episode_id,
        story_bible=story_bible,
        characters=characters,
        locations=locations,
        episode_plan=episode_plan,
        script=script,
        provider=active,
    )
    final = await build_storyboard_graph(active).ainvoke(initial)
    logger.info(
        "storyboard generator finished for episode %s (%d scenes)",
        episode_id,
        len((final.get("storyboard") or {}).get("scenes") or []),
    )
    return final


def graph_mermaid(provider: LLMProvider | None = None) -> str:
    """Mermaid rendering of the complete PRD section 12 pipeline."""
    return build_full_graph(provider or get_llm_provider()).get_graph().draw_mermaid()


__all__ = [
    "EPISODE_EXECUTION_ORDER",
    "FULL_EXECUTION_ORDER",
    "NODE_CONSISTENCY_CHECKER",
    "NODE_EPISODE_PLANNER",
    "NODE_SCRIPT_GENERATOR",
    "NODE_STORYBOARD_GENERATOR",
    "build_episode_graph",
    "build_full_graph",
    "build_planner_graph",
    "build_script_graph",
    "build_storyboard_graph",
    "graph_mermaid",
    "run_episode_planner",
    "run_script_generator",
    "run_storyboard_generator",
]
