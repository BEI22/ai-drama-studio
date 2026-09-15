"""LangGraph agents / LLM workflow (PRD sections 12, 13).

The PRD's section 12 pipeline is one chain::

    START -> story_parser -> character_extractor -> location_extractor
          -> episode_planner -> script_generator -> storyboard_generator
          -> consistency_checker -> END

Phase 3 implements the first three nodes (``story_graph``); Phase 4 adds the
remaining four (``episode_graph``). They are compiled as separate graphs because
PRD section 22's API is per-step and per-episode -- see
``app/agents/episode_graph.py`` for why, and for :func:`full_graph_mermaid`, which
renders the complete chain for docs.

Media generation (image/video/TTS) is deliberately **not** a graph node: PRD
section 12 keeps it in long-running Celery tasks instead of a synchronous request.
"""

from app.agents.episode_graph import (
    EPISODE_EXECUTION_ORDER,
    FULL_EXECUTION_ORDER,
    NODE_CONSISTENCY_CHECKER,
    NODE_EPISODE_PLANNER,
    NODE_SCRIPT_GENERATOR,
    NODE_STORYBOARD_GENERATOR,
    build_episode_graph,
    build_full_graph,
    build_planner_graph,
    build_script_graph,
    build_storyboard_graph,
    run_episode_planner,
    run_script_generator,
    run_storyboard_generator,
)
from app.agents.episode_graph import graph_mermaid as full_graph_mermaid
from app.agents.state import StoryInput, StoryState, UsageRecord, WorkflowError
from app.agents.story_graph import (
    EXECUTION_ORDER,
    NODE_CHARACTER_EXTRACTOR,
    NODE_LOCATION_EXTRACTOR,
    NODE_STORY_PARSER,
    build_story_graph,
    graph_mermaid,
    run_story_agent,
)
from app.agents.structured import extract_json, generate_structured

__all__ = [
    "EPISODE_EXECUTION_ORDER",
    "EXECUTION_ORDER",
    "FULL_EXECUTION_ORDER",
    "NODE_CHARACTER_EXTRACTOR",
    "NODE_CONSISTENCY_CHECKER",
    "NODE_EPISODE_PLANNER",
    "NODE_LOCATION_EXTRACTOR",
    "NODE_SCRIPT_GENERATOR",
    "NODE_STORYBOARD_GENERATOR",
    "NODE_STORY_PARSER",
    "StoryInput",
    "StoryState",
    "UsageRecord",
    "WorkflowError",
    "build_episode_graph",
    "build_full_graph",
    "build_planner_graph",
    "build_script_graph",
    "build_story_graph",
    "build_storyboard_graph",
    "extract_json",
    "full_graph_mermaid",
    "generate_structured",
    "graph_mermaid",
    "run_episode_planner",
    "run_script_generator",
    "run_story_agent",
    "run_storyboard_generator",
]
