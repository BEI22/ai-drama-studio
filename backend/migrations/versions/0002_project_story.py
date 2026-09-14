"""Add story_source / story_text to projects

Revision ID: 0002_project_story
Revises: 0001_initial
Create Date: 2026-09-14

PRD section 5.2 (创建项目: 故事来源 / 故事文本) and section 36 item 3-4
(Story 输入 + Story 保存). Phase 3's Story Agent consumes these columns.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_project_story"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("story_source", sa.String(length=32), nullable=True))
    op.add_column("projects", sa.Column("story_text", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("projects", "story_text")
    op.drop_column("projects", "story_source")
