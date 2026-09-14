"""Business services: orchestrate repositories and providers (Phase 2+).

Routes must stay thin -- all business rules live here so they can be reused by
Celery workers and tested without HTTP.
"""
