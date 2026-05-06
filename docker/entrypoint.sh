#!/usr/bin/env bash
# SCION backend container entrypoint.
#
# Brings the database to HEAD via the canonical lifecycle tool
# (`backend/tools/db_init.py init`) before launching whatever command
# was passed as CMD (uvicorn by default). The init step is idempotent:
# fresh DB → alembic upgrade head; managed DB at HEAD → no-op; legacy
# DB → stamp + upgrade.
#
# DATABASE_URL controls the target. In production compose this points
# to /data/scion.db (volume-backed). For local Postgres dev override
# it to postgresql://...
set -euo pipefail

echo "[entrypoint] SCION backend starting..."
echo "[entrypoint] DATABASE_URL=${DATABASE_URL:-<default sqlite>}"
echo "[entrypoint] DATA_REGION=${DATA_REGION:-unset}"

cd /app

# Idempotent schema upgrade. Fails loudly if the DB is in an
# inconsistent legacy state — better than a half-running service.
python backend/tools/db_init.py init

echo "[entrypoint] DB ready, exec'ing command: $*"
exec "$@"
