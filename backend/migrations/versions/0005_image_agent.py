"""assets + generation_tasks (Phase 5)

Revision ID: 0005_image_agent
Revises: 0004_episode_agent
Create Date: 2026-09-15

PRD Phase 5 adds the image pipeline: ImageProvider, Character Reference,
Location Reference, Prompt Builder, Image Task. Two tables from PRD section 17
carry it:

* ``assets``            -- one row per generated file (section 25: the DB stores
                          ``storage_key`` / ``url`` / ``metadata`` only, never
                          the bytes).
* ``generation_tasks``  -- the durable half of the section 21 async contract
                          (PENDING -> RUNNING -> SUCCESS, RUNNING -> FAILED ->
                          RETRY, max 3 retries).

``characters.reference_image_url`` and ``locations.reference_image_url`` already
exist (added in migrations 0002/0003) because PRD section 17 lists them; Phase 5
is the first phase that actually fills them, so no column work is needed here.

The partial unique index on ``idempotency_key`` implements the "必须保证幂等"
requirement from section 21: a second POST while a task is still live reuses the
existing row instead of paying for a second image, but the index only covers
unfinished tasks -- so a *finished* task never blocks a deliberate regeneration.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_image_agent"
down_revision: str | None = "0004_episode_agent"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LIVE_STATUSES = "status IN ('PENDING', 'RUNNING', 'RETRY')"


def upgrade() -> None:
    # ------------------------------------------------------------------ assets
    op.create_table(
        "assets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("episode_id", sa.Uuid(), nullable=True),
        sa.Column("shot_id", sa.Uuid(), nullable=True),
        sa.Column("type", sa.String(length=32), nullable=False, server_default="IMAGE"),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_assets_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["episode_id"],
            ["episodes.id"],
            name=op.f("fk_assets_episode_id_episodes"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["shot_id"],
            ["shots.id"],
            name=op.f("fk_assets_shot_id_shots"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_assets")),
    )
    op.create_index(op.f("ix_assets_project_id"), "assets", ["project_id"], unique=False)
    op.create_index(op.f("ix_assets_episode_id"), "assets", ["episode_id"], unique=False)
    op.create_index(op.f("ix_assets_shot_id"), "assets", ["shot_id"], unique=False)

    # -------------------------------------------------------- generation_tasks
    op.create_table(
        "generation_tasks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("episode_id", sa.Uuid(), nullable=True),
        sa.Column("shot_id", sa.Uuid(), nullable=True),
        sa.Column("task_type", sa.String(length=32), nullable=False, server_default="IMAGE"),
        sa.Column("provider", sa.String(length=64), nullable=True),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="PENDING"),
        sa.Column("input_payload", sa.JSON(), nullable=True),
        sa.Column("output_payload", sa.JSON(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=200), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_generation_tasks_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["episode_id"],
            ["episodes.id"],
            name=op.f("fk_generation_tasks_episode_id_episodes"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["shot_id"],
            ["shots.id"],
            name=op.f("fk_generation_tasks_shot_id_shots"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_generation_tasks")),
    )
    op.create_index(
        op.f("ix_generation_tasks_project_id"), "generation_tasks", ["project_id"], unique=False
    )
    op.create_index(
        op.f("ix_generation_tasks_episode_id"), "generation_tasks", ["episode_id"], unique=False
    )
    op.create_index(
        op.f("ix_generation_tasks_shot_id"), "generation_tasks", ["shot_id"], unique=False
    )
    op.create_index(
        "uq_generation_tasks_live_idempotency_key",
        "generation_tasks",
        ["idempotency_key"],
        unique=True,
        postgresql_where=sa.text(_LIVE_STATUSES),
        sqlite_where=sa.text(_LIVE_STATUSES),
    )


def downgrade() -> None:
    op.drop_index("uq_generation_tasks_live_idempotency_key", table_name="generation_tasks")
    op.drop_index(op.f("ix_generation_tasks_shot_id"), table_name="generation_tasks")
    op.drop_index(op.f("ix_generation_tasks_episode_id"), table_name="generation_tasks")
    op.drop_index(op.f("ix_generation_tasks_project_id"), table_name="generation_tasks")
    op.drop_table("generation_tasks")

    op.drop_index(op.f("ix_assets_shot_id"), table_name="assets")
    op.drop_index(op.f("ix_assets_episode_id"), table_name="assets")
    op.drop_index(op.f("ix_assets_project_id"), table_name="assets")
    op.drop_table("assets")
