"""Story Agent graph (PRD section 12).

    START -> story_parser -> character_extractor -> location_extractor -> END

Media generation is deliberately **not** part of this graph. PRD section 12:
screenplay/storyboard work is an LLM workflow, while image/video/TTS are
long-running asynchronous jobs that must not sit inside a synchronous HTTP
request. Phases 5-8 run those through Celery.

The graph is built with an injected provider so it can be compiled against a
stub in tests and against the configured provider in production.
"""

from __future__ import annotations

import logging

from langgraph.graph import END, START, StateGraph

from app.agents.nodes import (
    make_character_extractor_node,
    make_location_extractor_node,
    make_story_parser_node,
)
from app.agents.state import StoryState
from app.providers.base import LLMProvider
from app.providers.llm.factory import get_llm_provider

logger = logging.getLogger(__name__)

# Node names, exported so callers/tests don't hardcode strings.
NODE_STORY_PARSER = "story_parser"
NODE_CHARACTER_EXTRACTOR = "character_extractor"
NODE_LOCATION_EXTRACTOR = "location_extractor"

EXECUTION_ORDER = (NODE_STORY_PARSER, NODE_CHARACTER_EXTRACTOR, NODE_LOCATION_EXTRACTOR)


def build_story_graph(provider: LLMProvider | None = None):
    """Compile the Phase 3 storytelling graph."""
    active_provider = provider or get_llm_provider()

    graph = StateGraph(StoryState)
    graph.add_node(NODE_STORY_PARSER, make_story_parser_node(active_provider))
    graph.add_node(NODE_CHARACTER_EXTRACTOR, make_character_extractor_node(active_provider))
    graph.add_node(NODE_LOCATION_EXTRACTOR, make_location_extractor_node(active_provider))

    graph.add_edge(START, NODE_STORY_PARSER)
    graph.add_edge(NODE_STORY_PARSER, NODE_CHARACTER_EXTRACTOR)
    graph.add_edge(NODE_CHARACTER_EXTRACTOR, NODE_LOCATION_EXTRACTOR)
    graph.add_edge(NODE_LOCATION_EXTRACTOR, END)

    return graph.compile()


async def run_story_agent(
    *,
    project_id: str,
    story_text: str,
    genre: str | None = None,
    style: str | None = None,
    project_name: str | None = None,
    provider: LLMProvider | None = None,
) -> StoryState:
    """Run the graph once and return the final state.

    Errors propagate: a failed node aborts the run, and the caller
    (:class:`app.services.agent_service.AgentService`) records the failure on the
    project so the UI can show it and offer a retry.
    """
    active_provider = provider or get_llm_provider()

    initial: StoryState = {
        "project_id": project_id,
        "story": {
            "story_text": story_text,
            "genre": genre,
            "style": style,
            "project_name": project_name,
        },
        "errors": [],
        "usage": [],
        "prompt_versions": {},
        "mock_generated": active_provider.name == "mock",
    }

    final = await build_story_graph(active_provider).ainvoke(initial)
    logger.info(
        "story agent finished for project %s (step=%s, characters=%d, locations=%d)",
        project_id,
        final.get("current_step"),
        len(final.get("characters") or []),
        len(final.get("locations") or []),
    )
    return final


def graph_mermaid(provider: LLMProvider | None = None) -> str:
    """Mermaid rendering of the compiled graph (handy in docs and /docs)."""
    return build_story_graph(provider or get_llm_provider()).get_graph().draw_mermaid()


__all__ = [
    "EXECUTION_ORDER",
    "NODE_CHARACTER_EXTRACTOR",
    "NODE_LOCATION_EXTRACTOR",
    "NODE_STORY_PARSER",
    "build_story_graph",
    "graph_mermaid",
    "run_story_agent",
]
