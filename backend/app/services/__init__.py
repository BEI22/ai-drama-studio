"""Business services: orchestrate repositories and providers (PRD section 29).

Routes stay thin -- all business rules live here so they can be reused by Celery
workers and tested without HTTP.
"""

from app.services.auth_service import AuthService, get_auth_service
from app.services.project_service import ProjectService

__all__ = ["AuthService", "ProjectService", "get_auth_service"]
