"""Location / Scene Bible table (PRD sections 8, 17).

Section 17 calls the table ``locations`` with a ``style`` column; section 8's
Scene Bible is the authoritative field list and names it ``visual_style``. We
follow section 8 and note the rename here.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, TimestampMixin

if TYPE_CHECKING:  # pragma: no cover
    from app.models.project import Project


class Location(Base, TimestampMixin):
    __tablename__ = "locations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    time: Mapped[str | None] = mapped_column(String(100), nullable=True)
    lighting: Mapped[str | None] = mapped_column(String(200), nullable=True)
    visual_style: Mapped[str | None] = mapped_column(String(200), nullable=True)

    reference_image_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    project: Mapped[Project] = relationship(back_populates="locations")
