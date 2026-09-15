"""LangGraph shared state (PRD section 13).

PRD section 13's guidance is followed deliberately:

* the state carries **only** what the workflow needs;
* no large media ever enters the state -- later phases store URLs / object
  storage keys, not bytes;
* large text is represented by an id when it is not needed by every node.

The story text *is* needed by all three Phase 3 nodes, so it is carried inline.
That is a text field (max 200k chars per the API schema), not a binary -- the
PRD's concern is images and video, which is why media stays out.
"""

from __future__ import annotations

from typing import Any, TypedDict


class StoryInput(TypedDict, total=False):
    """The project facts each node needs."""

    story_text: str
    genre: str | None
    style: str | None
    project_name: str | None


class WorkflowError(TypedDict):
    node: str
    message: str


class UsageRecord(TypedDict, total=False):
    """Per-call accounting (PRD section 26 -- cost tracking groundwork)."""

    node: str
    provider: str
    model: str
    prompt_version: str
    input_tokens: int
    output_tokens: int
    estimated_cost: float


class StoryState(TypedDict, total=False):
    """Matches the shape in PRD section 13, scoped to what Phase 3 produces."""

    project_id: str
    episode_id: str

    story: StoryInput
    story_bible: dict[str, Any]

    characters: list[dict[str, Any]]
    locations: list[dict[str, Any]]

    # Phase 4+ (declared so the state shape does not churn later).
    episode_plan: dict[str, Any]
    script: dict[str, Any]
    storyboard: dict[str, Any]

    errors: list[WorkflowError]
    current_step: str

    # Phase 3 audit trail.
    usage: list[UsageRecord]
    prompt_versions: dict[str, str]
    mock_generated: bool


__all__ = ["StoryInput", "StoryState", "UsageRecord", "WorkflowError"]
