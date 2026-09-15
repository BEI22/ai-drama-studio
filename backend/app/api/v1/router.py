"""API v1 router aggregation.

Feature routers are mounted here phase by phase -- see PRD section 22 for the
full target surface.

Phase 1: health
Phase 2: auth, projects (+ story)
Phase 3: story agent, characters, locations
"""

from fastapi import APIRouter

from app.api.v1 import auth, bible, health, projects

api_router = APIRouter()

api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(bible.router)
api_router.include_router(projects.router)

__all__ = ["api_router"]
