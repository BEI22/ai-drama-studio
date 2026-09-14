"""API v1 router aggregation.

Feature routers are mounted here phase by phase -- see PRD section 22 for the
full target surface.

Phase 2: health, auth, projects (+ story).
"""

from fastapi import APIRouter

from app.api.v1 import auth, health, projects

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(projects.router)
