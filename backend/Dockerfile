# syntax=docker/dockerfile:1
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app/backend

# curl backs the container healthcheck.
# NOTE: ffmpeg is deliberately NOT installed here. It is a Phase 8 (compose)
# dependency and pulls ~135 MB of archives / ~470 MB installed, which would
# bloat the Phase 1 image and slow every build. Add it in Phase 8:
#     RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
#         && rm -rf /var/lib/apt/lists/*
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./
COPY tests ./tests

RUN pip install --upgrade pip \
    && pip install ".[dev]"

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=5 \
    CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
