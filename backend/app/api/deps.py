"""Shared FastAPI dependencies.

Authentication dependencies (``get_current_user``) land here in Phase 2; Phase 1
only exposes the database session and settings.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.database import get_db

DbSession = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]

__all__ = ["AppSettings", "DbSession", "get_db", "get_settings"]
