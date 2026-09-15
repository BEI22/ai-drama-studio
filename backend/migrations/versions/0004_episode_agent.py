"""shots table + episode generation state (Phase 4)

Revision ID: 0004_episode_agent
Revises: 0003_story_agent
Create Date: 2026-09-15

PRD Phase 4: the Episode Agent plans episodes, writes scripts and produces
storyboards. Section 11 defines the storyboard JSON, section 17 the ``shots``
table it lands in.

``episodes`` itself already exists (migration 0001); this revision adds the
per-step run state so a failed script/storyboard generation is distinguishable
from "never attempted", mirroring ``projects.analysis_*``.

Note on the shots constraint: PRD section 11 numbers shots *within* a scene, so
``shot_number`` restarts at 1 for each scene. Uniqueness is therefore
``(episode_id, scene_id, shot_number)`` -- a constraint on
``(episode_id, shot_number)`` would reject the second scene of every episode.
A separate ``sequence`` column carries the absolute order across the episode,
which is what Phase 8's composer needs.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_episode_agent"
down_revision: str | None = "0003_story_agent"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ------------------------------------------------- episode generation state
    op.add_column(
        "episodes",
        sa.Column(
            "script_status",
            sa.String(length=32),
            nullable=False,
            server_default="NOT_GENERATED",
        ),
    )
    op.add_column(
        "episodes",
        sa.Column(
            "storyboard_status",
            sa.String(length=32),
            nullable=False,
            server_default="NOT_GENERATED",
        ),
    )
    op.add_column("episodes", sa.Column("generation_error", sa.Text(), nullable=True))
    op.add_column(
        "episodes",
        sa.Column("script_generated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "episodes",
        sa.Column("storyboard_generated_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ------------------------------------------------------------------- shots
    op.create_table(
        "shots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("episode_id", sa.Uuid(), nullable=False),
        sa.Column("scene_id", sa.String(length=64), nullable=False),
        sa.Column("shot_number", sa.Integer(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duration", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("shot_size", sa.String(length=32), nullable=False, server_default="medium"),
        sa.Column("camera_movement", sa.String(length=32), nullable=False, server_default="static"),
        sa.Column("characters_json", sa.JSON(), nullable=True),
        sa.Column("action", sa.Text(), nullable=True),
        sa.Column("expression", sa.Text(), nullable=True),
        sa.Column("dialogue", sa.Text(), nullable=True),
        sa.Column("visual_description", sa.Text(), nullable=True),
        sa.Column("image_prompt", sa.Text(), nullable=True),
        sa.Column("video_prompt", sa.Text(), nullable=True),
        sa.Column("image_asset_id", sa.Uuid(), nullable=True),
        sa.Column("video_asset_id", sa.Uuid(), nullable=True),
        sa.Column("audio_asset_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="DRAFT"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["episode_id"],
            ["episodes.id"],
            name=op.f("fk_shots_episode_id_episodes"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_shots")),
        sa.UniqueConstraint(
            "episode_id",
            "scene_id",
            "shot_number",
            name="uq_shots_episode_scene_number",
        ),
    )
    op.create_index(op.f("ix_shots_episode_id"), "shots", ["episode_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_shots_episode_id"), table_name="shots")
    op.drop_table("shots")

    op.drop_column("episodes", "storyboard_generated_at")
    op.drop_column("episodes", "script_generated_at")
    op.drop_column("episodes", "generation_error")
    op.drop_column("episodes", "storyboard_status")
    op.drop_column("episodes", "script_status")
