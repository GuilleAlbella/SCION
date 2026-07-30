from __future__ import annotations

"""Runtime configuration for SCION (ex Kalido-lite).

This module centralises environment-driven configuration that is shared
across backend subsystems and the UI. It does **not** start services or
perform any I/O; it only exposes configuration values.

Punto 10.1 focuses on the "local integrated" execution mode, where the
backend API and the Streamlit UI run together on a single developer
machine.
"""

import os

# Execution mode -------------------------------------------------------------

# Explicit execution mode identifier. This is intended to distinguish
# between:
# - "local_integrated"  – developer machine, FastAPI + UI running locally.
# - "tests"             – pytest / CI execution.
# - future modes such as "docker" or "prod".
SCION_EXECUTION_MODE: str = os.getenv("SCION_EXECUTION_MODE", "local_integrated")


# Backend connectivity --------------------------------------------------------

# Host and port where the backend API is expected to listen in
# local_integrated mode. These values are **not** used to start the
# server; they simply describe how other components (UI, tools) should
# reach it.
SCION_BACKEND_HOST: str = os.getenv("SCION_BACKEND_HOST", "127.0.0.1")
SCION_BACKEND_PORT: str = os.getenv("SCION_BACKEND_PORT", "8000")

# Base path for versioned API.
SCION_API_BASE_PATH: str = os.getenv("SCION_API_BASE_PATH", "/api/v1")

# Canonical base URL seen by HTTP clients (including the UI). A dedicated
# SCION_API_BASE_URL can override the composed URL entirely when needed.
SCION_API_BASE_URL: str = os.getenv(
    "SCION_API_BASE_URL",
    f"http://{SCION_BACKEND_HOST}:{SCION_BACKEND_PORT}{SCION_API_BASE_PATH}",
)


# Feature flags --------------------------------------------------------------

# TAISA reasoning mode. For Punto 10.1 this is purely declarative; the
# backend and UI can use it to decide whether they are running against a
# mock implementation or a real remote service in future milestones.
#
# Valid values (by convention):
# - "mock"  – default, contract-only behaviour.
# - "real"  – future integration with a live TAISA provider.
SCION_TAISA_MODE: str = os.getenv("SCION_TAISA_MODE", "real")


# Share-folder watcher ---------------------------------------------------------

# Filesystem path where the shared import folder is mounted. SCION scans this
# directory for new data files and notifies the user when fresher data is
# available than the latest snapshot. Set to "" to disable the watcher.
# Default matches the mount point configured on ps-ubuntu-0043.
SCION_SHARE_MOUNT_PATH: str = os.getenv("SCION_SHARE_MOUNT_PATH", "/mnt/vm1_share")


# Logging ----------------------------------------------------------------------

# Level for the root logger and all managed sub-loggers.
# Valid values: debug | info | warning | error | critical  (case-insensitive)
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "info")

# Output format. "json" (default for production) emits one JSON line per
# record — suitable for Loki / CloudWatch / Datadog. "text" emits a compact
# human-readable line for local development.
LOG_FORMAT: str = os.getenv("LOG_FORMAT", "json")


# CORS -------------------------------------------------------------------------

# Comma-separated list of allowed CORS origins. The browser talks to nginx
# (same origin), so this is only relevant for direct API calls. Defaults
# to localhost for local dev; override in docker-compose or .env for other
# environments.
ALLOWED_ORIGINS: str = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000")


# Criticality scoring -----------------------------------------------------------

# Weight of PDCR usage score in the combined criticality formula.
# combined = USAGE_WEIGHT * usage_score + GRAPH_WEIGHT * graph_score
# Must sum to 1.0. Override via env vars for customer-specific tuning.
CRITICALITY_USAGE_WEIGHT: float = float(os.getenv("CRITICALITY_USAGE_WEIGHT", "0.6"))
CRITICALITY_GRAPH_WEIGHT: float = float(os.getenv("CRITICALITY_GRAPH_WEIGHT", "0.4"))

# Band thresholds for HIGH / MEDIUM / LOW.
# combined >= HIGH_THRESHOLD  → "HIGH"
# combined >= MED_THRESHOLD   → "MEDIUM"
# combined <  MED_THRESHOLD   → "LOW"
CRITICALITY_HIGH_THRESHOLD: float = float(os.getenv("CRITICALITY_HIGH_THRESHOLD", "0.6"))
CRITICALITY_MED_THRESHOLD:  float = float(os.getenv("CRITICALITY_MED_THRESHOLD",  "0.3"))
