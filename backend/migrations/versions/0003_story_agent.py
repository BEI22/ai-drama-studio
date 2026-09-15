"""characters / locations tables + project analysis state

Revision ID: 0003_story_agent
Revises: 0002_project_story
Create Date: 2026-09-14

PRD Phase 3 (section 37): the Story Agent extracts characters and locations and
builds the Story Bible. Section 7 (Character Bible) and section 8 (Scene Bible)
define the semantic fields; section 17 defines the table shape.

Two deliberate deviations from section 17, documented in the models:
  * ``locations.style`` is named ``visual_style`` to match section 8;
  * several section 7/8 fields missing from section 17 are added (age, gender,
    hair, time, lighting) because the Bible schemas require them.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_story_agent"
down_revision: str | None = "0002_project_story"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ------------------------------------------------------ project run state
    op.add_column(
        "projects",
        sa.Column(
            "analysis_status",
            sa.String(length=32),
            nullable=False,
            server_default="NOT_ANALYZED",
        ),
    )
    op.add_column("projects", sa.Column("analysis_error", sa.Text(), nullable=True))
    op.add_column("projects", sa.Column("analyzed_at", sa.DateTime(timezone=True), nullable=True))

    # ----------------------------------------------------------- characters
    op.create_table(
        "characters",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False, server_default="SUPPORTING"),
        sa.Column("age", sa.String(length=50), nullable=True),
        sa.Column("gender", sa.String(length=50), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("appearance", sa.Text(), nullable=True),
        sa.Column("hair", sa.String(length=200), nullable=True),
        sa.Column("clothing", sa.Text(), nullable=True),
        sa.Column("personality", sa.JSON(), nullable=True),
        sa.Column("voice_id", sa.String(length=100), nullable=True),
        sa.Column("reference_image_url", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_characters_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_characters")),
    )
    op.create_index(op.f("ix_characters_project_id"), "characters", ["project_id"], unique=False)

    # ------------------------------------------------------------ locations
    op.create_table(
        "locations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("time", sa.String(length=100), nullable=True),
        sa.Column("lighting", sa.String(length=200), nullable=True),
        sa.Column("visual_style", sa.String(length=200), nullable=True),
        sa.Column("reference_image_url", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_locations_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_locations")),
    )
    op.create_index(op.f("ix_locations_project_id"), "locations", ["project_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_locations_project_id"), table_name="locations")
    op.drop_table("locations")
    op.drop_index(op.f("ix_characters_project_id"), table_name="characters")
    op.drop_table("characters")

    op.drop_column("projects", "analyzed_at")
    op.drop_column("projects", "analysis_error")
    op.drop_column("projects", "analysis_status")
