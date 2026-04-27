from __future__ import annotations

"""SCION demo seed scenario (Punto 10.3.b).

This script creates a minimal, deterministic technical scenario for the SCION
end-to-end demo. It produces two distinct metadata snapshots (State A and
State B) with a single intentional, detectable change between them.

Scenario definition
-------------------

- State A (baseline):
  - The logical demo table ``demo_scion_table_v10`` does **not** exist in the
    runtime database.

- State B (modified):
  - The table ``demo_scion_table_v10`` exists with a simple, stable schema:

    .. code-block:: sql

       CREATE TABLE demo_scion_table_v10 (
           id   INTEGER PRIMARY KEY,
           name TEXT NOT NULL
       );

The change is therefore:

- "TABLE_ADDED" for ``demo_scion_table_v10`` between State A and State B.

This change is intentionally simple and is expected to be detectable by the
snapshot + diff engines, and consumable by the UI via the existing API.

Execution flow
--------------

The script performs the following steps against the **real** runtime
infrastructure:

1. Ensures the runtime database is reachable using ``app.db.engine.engine``.
2. Drops the ``demo_scion_table_v10`` table if it already exists to enforce a
   clean baseline (State A).
3. Calls the backend API ``POST /api/v1/snapshots`` to create **Snapshot A**.
4. Creates the ``demo_scion_table_v10`` table in the same database
   (transition to State B).
5. Calls the backend API ``POST /api/v1/snapshots`` again to create
   **Snapshot B**.

Both snapshot identifiers are printed to stdout so that they can be used
manually for diff, impact, and reasoning during the demo.

Assumptions
-----------

- The backend API is already running in local_integrated mode, typically via::

    uvicorn app.main:app --reload

- ``SCION_API_BASE_URL`` points to the backend API base URL, for example::

    http://127.0.0.1:8000/api/v1

- The runtime database schema for SCION (metadata tables, etc.) has already
  been bootstrapped, e.g. via ``backend/tools/bootstrap_sqlite_db.py``.

The script does **not** perform any UI interaction and does not require any
external systems beyond the local backend and its configured database.

Usage
-----

From the project root, with the backend running and the virtualenv activated::

    set SCION_API_BASE_URL=http://127.0.0.1:8000/api/v1  # Windows (cmd)
    # or in PowerShell:
    # $env:SCION_API_BASE_URL = "http://127.0.0.1:8000/api/v1"

    python -m backend.tools.demo_seed

On success, the script prints the two snapshot identifiers created for State A
and State B.
"""

import os
import sys
from typing import Any, Dict

import requests
from sqlalchemy import select, text
from sqlalchemy.orm import Session


# Ensure that the ``backend/`` directory is on sys.path so that ``app.*``
# imports resolve correctly when this script is executed directly via
# ``python backend/tools/demo_seed.py`` from the project root.
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, os.pardir, os.pardir))
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")

if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app.db.engine import engine as db_engine
from app.diff.diff_models import ChangeEvent


DEMO_PARENT_TABLE_NAME = "demo_scion_parent_v10"
DEMO_TABLE_NAME = "demo_scion_table_v10"


def _get_api_base_url() -> str:
    """Resolve the backend API base URL from environment.

    SCION_API_BASE_URL is the primary configuration knob. No hardcoded URL is
    used; a small default is provided only as a developer convenience when the
    variable is not set.
    """

    return os.getenv("SCION_API_BASE_URL", "http://127.0.0.1:8000/api/v1")


def _call_create_snapshot(api_base_url: str) -> Dict[str, Any]:
    """Call the backend API to create a snapshot and return the JSON payload."""

    url = f"{api_base_url}/snapshots"
    headers = {"Accept": "application/json"}

    api_key = os.getenv("API_KEY")
    if api_key:
        headers["X-API-Key"] = api_key

    response = requests.post(url, headers=headers, timeout=60)
    response.raise_for_status()
    return response.json()


def _call_execute_diff(api_base_url: str, snapshot_from: str, snapshot_to: str) -> Dict[str, Any]:
    """Execute the diff endpoint between two snapshots and return its JSON."""

    url = f"{api_base_url}/diff"
    headers = {"Accept": "application/json", "Content-Type": "application/json"}

    api_key = os.getenv("API_KEY")
    if api_key:
        headers["X-API-Key"] = api_key

    payload = {"snapshot_from": snapshot_from, "snapshot_to": snapshot_to}
    response = requests.post(url, json=payload, headers=headers, timeout=60)
    response.raise_for_status()
    return response.json()


def _drop_demo_table_if_exists() -> None:
    """Drop the demo table if it already exists to ensure a clean baseline."""

    # Drop child table first; parent table is part of the stable baseline.
    drop_child = f"DROP TABLE IF EXISTS {DEMO_TABLE_NAME}"
    with db_engine.begin() as conn:
        conn.execute(text(drop_child))


def _get_latest_change_event(snapshot_from_id: int, snapshot_to_id: int) -> ChangeEvent | None:
    """Return the most recent ChangeEvent for the given snapshot pair.

    This uses detected_at ordering so that repeated runs of the demo scenario
    will always pick the last computed diff for the same (from, to) pair.
    """

    with Session(bind=db_engine) as session:
        stmt = (
            select(ChangeEvent)
            .where(
                ChangeEvent.snapshot_from == snapshot_from_id,
                ChangeEvent.snapshot_to == snapshot_to_id,
            )
            .order_by(ChangeEvent.detected_at.desc(), ChangeEvent.change_id.desc())
        )
        return session.execute(stmt).scalars().first()


def _create_demo_table() -> None:
    """Create the demo child table for State B.

    The parent table ``demo_scion_parent_v10`` is part of the stable baseline
    and exists in both snapshots. The child table ``demo_scion_table_v10`` is
    created only in State B and includes a real FOREIGN KEY to the parent so
    that the System Graph can surface an explicit edge without inference.
    """

    ddl = f"""
    CREATE TABLE {DEMO_TABLE_NAME} (
        id         INTEGER PRIMARY KEY,
        parent_id  INTEGER NOT NULL,
        name       TEXT NOT NULL,
        CONSTRAINT fk_demo_child_parent
            FOREIGN KEY(parent_id)
            REFERENCES {DEMO_PARENT_TABLE_NAME}(id)
    )
    """
    with db_engine.begin() as conn:
        conn.execute(text(ddl))


def _ensure_parent_table_exists() -> None:
    """Ensure the stable parent table exists for both snapshots.

    The parent table is created once (if missing) and is *not* part of the
    diff scenario; it is present in both Snapshot A and Snapshot B so that the
    only structural change remains the addition of the child table.
    """

    ddl = f"""
    CREATE TABLE IF NOT EXISTS {DEMO_PARENT_TABLE_NAME} (
        id   INTEGER PRIMARY KEY,
        name TEXT NOT NULL
    )
    """
    with db_engine.begin() as conn:
        conn.execute(text(ddl))


def main() -> None:
    """Execute the demo seed scenario.

    This function is intentionally straightforward and performs no retries.
    Any exception will cause a non-zero exit code, making failures visible to
    the caller.
    """

    api_base_url = _get_api_base_url()

    print(f"[demo] Using API base URL: {api_base_url}")

    # Ensure database connectivity via the shared application engine.
    print("[demo] Verifying database connectivity …")
    with db_engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    print("[demo] Database connectivity OK.")

    # State A: baseline with the stable parent table but without the child
    # demo table.
    print(f"[demo] Ensuring parent table '{DEMO_PARENT_TABLE_NAME}' exists (baseline)…")
    _ensure_parent_table_exists()

    print(f"[demo] Dropping demo table '{DEMO_TABLE_NAME}' if it exists (State A baseline)…")
    _drop_demo_table_if_exists()
    print("[demo] Baseline state prepared.")

    print("[demo] Creating Snapshot A (baseline)…")
    snap_a = _call_create_snapshot(api_base_url)
    snapshot_a_id = snap_a.get("snapshot_id")
    print(f"[demo] Snapshot A created with snapshot_id={snapshot_a_id}.")

    # State B: create the demo table.
    print(f"[demo] Creating demo table '{DEMO_TABLE_NAME}' (State B)…")
    _create_demo_table()
    print("[demo] Demo table created.")

    print("[demo] Creating Snapshot B (after demo change)…")
    snap_b = _call_create_snapshot(api_base_url)
    snapshot_b_id = snap_b.get("snapshot_id")
    print(f"[demo] Snapshot B created with snapshot_id={snapshot_b_id}.")

    # Execute diff between Snapshot A and B via the real API.
    print("[demo] Executing diff between Snapshot A and B via /diff …")
    diff_result = _call_execute_diff(api_base_url, str(snapshot_a_id), str(snapshot_b_id))
    print(f"[demo] Diff result: {diff_result}")

    # Retrieve the most recent ChangeEvent for this snapshot pair from
    # persistence and extract its change_id for subsequent impact/reasoning.
    print("[demo] Retrieving latest ChangeEvent from persistence …")
    latest_event = _get_latest_change_event(int(snapshot_a_id), int(snapshot_b_id))
    if latest_event is None:
        print("[demo] No ChangeEvent found for the demo snapshot pair; cannot run impact/reasoning.")
        print("[demo] Demo seed scenario completed with diff only.")
        return

    change_id = latest_event.change_id
    print(f"[demo] Using change_id={change_id} for impact and reasoning.")

    # Execute impact analysis via the API.
    impact_url = f"{api_base_url}/impact/{change_id}"
    impact_headers = {"Accept": "application/json"}
    api_key = os.getenv("API_KEY")
    if api_key:
        impact_headers["X-API-Key"] = api_key

    print(f"[demo] Executing impact analysis via POST {impact_url} …")
    impact_resp = requests.post(impact_url, headers=impact_headers, timeout=60)
    impact_resp.raise_for_status()
    impact_payload = impact_resp.json()
    print(f"[demo] Impact result: {impact_payload}")

    # Execute reasoning via the API.
    reasoning_url = f"{api_base_url}/reasoning/{change_id}"
    reasoning_headers = impact_headers

    print(f"[demo] Executing reasoning via POST {reasoning_url} …")
    reasoning_resp = requests.post(reasoning_url, headers=reasoning_headers, timeout=60)
    reasoning_resp.raise_for_status()
    reasoning_payload = reasoning_resp.json()
    print(f"[demo] Reasoning result: {reasoning_payload}")

    print("[demo] Full script-driven demo completed successfully (snapshots, diff, impact, reasoning).")


if __name__ == "__main__":  # pragma: no cover - manual execution only
    main()
