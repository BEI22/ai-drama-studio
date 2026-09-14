"""API v1 router aggregation.

Feature routers (projects, characters, episodes, shots, tasks, ...) are mounted
here phase by phase -- see PRD section 22 for the full target surface.
"""

from fastapi import APIRouter

from app.api.v1 import health

api_router = APIRouter()
api_router.include_router(health.router)
