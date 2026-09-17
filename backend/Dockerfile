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

# Dependencies are installed as their own layer, driven by the manifest, BEFORE the
# source is copied. Ordering matters a lot here: with `COPY app ./app` above the
# install (as this file originally had it), every source edit invalidated the pip
# layer and forced a full dependency reinstall -- minutes per build, and each Phase 5
# iteration paid it. Now only a pyproject change reinstalls.
# Index is a build arg so a slow/blocked route to pypi.org (common from CN networks,
# where the *host* is fine but the container's route stalls) can be pointed at a
# mirror without editing this file. Default keeps upstream behaviour.
ARG PIP_INDEX_URL=https://pypi.org/simple

COPY pyproject.toml ./
RUN python -c "\
import tomllib, pathlib; \
data = tomllib.loads(pathlib.Path('pyproject.toml').read_text(encoding='utf-8')); \
deps = list(data['project']['dependencies']); \
deps += list(data['project'].get('optional-dependencies', {}).get('dev', [])); \
pathlib.Path('/tmp/reqs.txt').write_text('\n'.join(deps), encoding='utf-8')" \
    && pip install --upgrade pip --index-url "$PIP_INDEX_URL" \
    && pip install -r /tmp/reqs.txt --index-url "$PIP_INDEX_URL"

COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./
COPY tests ./tests

# The project itself, editable, with deps already satisfied -- so this stays cheap
# and always reflects the freshly copied source.
RUN pip install --no-deps -e . --index-url "$PIP_INDEX_URL"

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=5 \
    CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
