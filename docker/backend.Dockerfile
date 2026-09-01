# SCION backend container — FastAPI + uvicorn.
#
# Multi-stage build: stage 1 installs Python deps into a dedicated
# venv; stage 2 copies that venv plus the application source into a
# slim runtime image. Keeps the final image around ~250 MB.

# ──── Stage 1: builder ────
FROM python:3.12-slim-bookworm AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

# Build deps for psycopg / etc. — stripped from the runtime image.
# `apt-get upgrade` pulls the latest Debian security patches on every
# build, so we don't ship CVEs that were already fixed upstream by
# the time the image was published. Combined with `--pull` in the
# publish workflow this guarantees no stale base layers.
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && apt-get install -y --no-install-recommends build-essential gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Copy only requirement files first so dependency installs cache
# independently of source changes.
COPY backend/requirements ./requirements

RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip wheel \
    && /opt/venv/bin/pip install -r requirements/prod.txt


# ──── Stage 2: runtime ────
FROM python:3.12-slim-bookworm AS runtime

# SCION_VERSION is injected at build time (the publish workflow passes
# the git tag, e.g. `1.21.0`). It's read by /api/v1/system/version so
# the in-app banner matches what's actually deployed.
ARG SCION_VERSION=dev
ENV SCION_VERSION=${SCION_VERSION}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH="/app/backend"

# tini = minimal init process; reaps zombies and forwards signals so
# `docker stop` shuts uvicorn down gracefully instead of SIGKILL.
# Runtime stage gets the same security upgrade so user code lives on
# top of fully-patched OS layers, not just the build deps.
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && apt-get install -y --no-install-recommends tini curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 1000 scion \
    && useradd  --system --uid 1000 --gid scion --create-home scion

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app

# Application source. We deliberately copy backend/ and alembic/
# separately (rather than the whole repo) to keep the image tight
# and avoid pulling node_modules / frontend build artefacts.
COPY backend     ./backend
COPY alembic     ./alembic
COPY alembic.ini ./alembic.ini

COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# /data holds persistent artefacts (uploaded files, etc.).
# DB state lives in the `pgdata` Postgres volume on the scion-postgres container.
RUN mkdir -p /data && chown -R scion:scion /data /app

USER scion

EXPOSE 8000

# Healthcheck hits the readiness endpoint that engine_registry exposes
# at startup. Compose uses this to gate the frontend on the backend.
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=4 \
    CMD curl -fsS http://localhost:8000/api/v1/health/ready || exit 1

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/entrypoint.sh"]
# --no-access-log: uvicorn per-request lines suppressed; nginx already
# emits structured JSON access logs so we avoid duplicating every line.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
