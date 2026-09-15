"""Story Agent nodes (PRD sections 12 and 37).

    START -> story_parser -> character_extractor -> location_extractor -> END

Each node is a factory closing over an injected :class:`LLMProvider`, so tests
can pass a stub without touching global settings. Every node goes through
``generate_structured``, which means nothing reaches the database without passing
Pydantic validation.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.agents.state import StoryState
from app.agents.structured import generate_structured
from app.core.config import settings
from app.providers.base import LLMProvider, LLMRequest
from app.schemas.bible import (
    CharacterExtraction,
    LocationExtraction,
    StoryBibleContent,
)
from app.utils.prompts import load_prompt

logger = logging.getLogger(__name__)

STORY_PARSER_PROMPT = "story/story_parser_v2"
CHARACTER_EXTRACTOR_PROMPT = "story/character_extractor_v1"
LOCATION_EXTRACTOR_PROMPT = "story/location_extractor_v1"


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


# --------------------------------------------------------------------------- #
# Node 1 -- Story Parser
# --------------------------------------------------------------------------- #
def make_story_parser_node(provider: LLMProvider):
    """Build the Story Bible (PRD section 6) from the raw story text."""

    async def story_parser(state: StoryState) -> dict[str, Any]:
        story = state.get("story", {})
        story_text = (story.get("story_text") or "").strip()

        prompt = load_prompt(STORY_PARSER_PROMPT)
        system, user = prompt.render(
            story_text=story_text,
            genre=story.get("genre") or "（未指定）",
            style=story.get("style") or "（未指定）",
        )

        bible, result = await generate_structured(
            provider,
            LLMRequest(
                prompt=user,
                system=system,
                prompt_version=prompt.version,
                temperature=settings.llm_temperature,
            ),
            StoryBibleContent,
        )

        logger.info("story_parser produced bible for project %s", state.get("project_id"))
        return {
            "story_bible": bible.model_dump(),
            "current_step": "story_parser",
            "usage": [
                *state.get("usage", []),
                _usage_record("story_parser", provider, prompt.version, result),
            ],
            "prompt_versions": {**state.get("prompt_versions", {}), "story_parser": prompt.version},
        }

    return story_parser


# --------------------------------------------------------------------------- #
# Node 2 -- Character Extractor
# --------------------------------------------------------------------------- #
def make_character_extractor_node(provider: LLMProvider):
    """Extract the Character Bible (PRD section 7)."""

    async def character_extractor(state: StoryState) -> dict[str, Any]:
        story = state.get("story", {})
        prompt = load_prompt(CHARACTER_EXTRACTOR_PROMPT)
        system, user = prompt.render(
            story_text=(story.get("story_text") or "").strip(),
            story_bible_json=json.dumps(state.get("story_bible", {}), ensure_ascii=False, indent=2),
        )

        extraction, result = await generate_structured(
            provider,
            LLMRequest(
                prompt=user,
                system=system,
                prompt_version=prompt.version,
                temperature=settings.llm_temperature,
            ),
            CharacterExtraction,
        )

        logger.info("character_extractor found %d characters", len(extraction.characters))
        return {
            "characters": [character.model_dump() for character in extraction.characters],
            "current_step": "character_extractor",
            "usage": [
                *state.get("usage", []),
                _usage_record("character_extractor", provider, prompt.version, result),
            ],
            "prompt_versions": {
                **state.get("prompt_versions", {}),
                "character_extractor": prompt.version,
            },
        }

    return character_extractor


# --------------------------------------------------------------------------- #
# Node 3 -- Location Extractor
# --------------------------------------------------------------------------- #
def make_location_extractor_node(provider: LLMProvider):
    """Extract the Scene Bible (PRD section 8)."""

    async def location_extractor(state: StoryState) -> dict[str, Any]:
        story = state.get("story", {})
        prompt = load_prompt(LOCATION_EXTRACTOR_PROMPT)
        system, user = prompt.render(
            story_text=(story.get("story_text") or "").strip(),
            story_bible_json=json.dumps(state.get("story_bible", {}), ensure_ascii=False, indent=2),
        )

        extraction, result = await generate_structured(
            provider,
            LLMRequest(
                prompt=user,
                system=system,
                prompt_version=prompt.version,
                temperature=settings.llm_temperature,
            ),
            LocationExtraction,
        )

        logger.info("location_extractor found %d locations", len(extraction.locations))
        return {
            "locations": [location.model_dump() for location in extraction.locations],
            "current_step": "location_extractor",
            "usage": [
                *state.get("usage", []),
                _usage_record("location_extractor", provider, prompt.version, result),
            ],
            "prompt_versions": {
                **state.get("prompt_versions", {}),
                "location_extractor": prompt.version,
            },
        }

    return location_extractor


__all__ = [
    "CHARACTER_EXTRACTOR_PROMPT",
    "LOCATION_EXTRACTOR_PROMPT",
    "STORY_PARSER_PROMPT",
    "make_character_extractor_node",
    "make_location_extractor_node",
    "make_story_parser_node",
]
