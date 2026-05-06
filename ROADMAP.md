# SCION Roadmap

Forward-looking plan for SCION releases. Companion to `CHANGELOG.md`
(which records what already shipped). Items below are grouped by
release; ordering inside each release is a reasonable execution order
but not a contract.

Current version: **v1.20.00** (see `frontend/src/lib/constants.ts`).

---

## v1.21 — Containerised deploy (in progress)

Goal: one-command deploy on the test VM that ITS provisions on
CloudBolt. Target spec confirmed in Reunion 9: 8 core / 32 GB RAM,
single VM, SCION + Parser co-located.

- **Dockerfiles**: `backend.Dockerfile` (FastAPI + uvicorn, multi-stage,
  slim) and `frontend.Dockerfile` (Next.js standalone runtime).
- **`docker-compose.yml`**: backend + frontend + nginx reverse proxy
  on a single public port. Named volume for the SQLite file so
  rebuilds don't wipe the DB.
- **Entrypoint**: runs `backend/tools/db_init.py init` (idempotent,
  brings the DB to head) before launching uvicorn.
- **`.env.example`**: `NEXT_PUBLIC_API_URL`, `DATA_DIR`, `LOG_LEVEL`,
  `DATA_REGION` (logged-only for now, used in v1.23).
- **GHCR publish**: GitHub Action that builds and pushes
  `ghcr.io/<owner>/scion-backend:<tag>` and `:latest` on every
  release tag. Image visibility set to public (repo stays private).
- **Watchtower (read-only mode)**: container that polls GHCR every 6h
  and pulls new images automatically. No UI interaction yet.
- **Version banner in Sidebar**: backend exposes `/api/v1/system/version`
  (current vs. latest from GitHub releases API, cached 1h). Frontend
  pill in the sidebar shows `v1.20.00 — Update available → v1.21.00`
  when behind, links to release notes. **Read-only**, no in-app update
  trigger yet (that's v1.22).
- **Deploy README** under `docker/README.md`: how to bring SCION up on
  a fresh CloudBolt VM, how to point it at a Teradata source, how to
  upgrade.

Acceptance: ITS hands us an empty 8c/32GB VM, we run
`git clone && docker compose up -d`, SCION is reachable on port 80,
and the upload flow ingests a dictionary export end-to-end.

---

## v1.22 — Self-update + portability hygiene

Goal: close the deploy story and remove future migration risk.

- **In-app "Update now" button**: enable Watchtower's HTTP API,
  add `POST /api/v1/system/update` endpoint (backend → Watchtower
  token-protected call), wire a confirmation modal in the sidebar
  pill. Clicking pulls + recreates containers (~30s downtime).
- **SQL portability sweep**: replace SQLite-only constructs
  (`INSERT OR IGNORE`, `strftime`, `julianday`, ad-hoc `||` casts) with
  ANSI equivalents that also work on Postgres. Behaviour-preserving,
  zero-risk, paid forward to v1.25.
- **`DATABASE_URL` discipline**: audit that no module hardcodes the
  SQLite path; everything reads from the env var. Add a runtime check
  at boot that the URL is reachable.
- **`/system/version` fix**: today the endpoint queries the SCION
  repo's GitHub Releases API, which returns 404 anonymously because
  the repo is private — so the "update available" pill never lights
  up. Switch the lookup to `scion-deploy` (public) and either
  cross-tag releases there from the SCION publish workflow or
  publish a `LATEST.txt` in `scion-deploy` that the workflow
  updates. Either way, the banner only matters once there is a
  newer release than what's installed.

Acceptance: a user clicks "Update" in the UI, the version pill goes
green, and `grep -RE "INSERT OR (IGNORE|REPLACE)|strftime|julianday"
backend/app` returns nothing.

---

## v1.23 — Multi-region readiness

Goal: meet the data-residency point Kindy raised in Reunion 9 — US
data stays in US, EU in EU, etc. Code change is small; the bulk is
deploy doc + telemetry hygiene.

- **`DATA_REGION` env var** surfaced in the Sidebar footer ("Region:
  eu-west-1") and stamped on every log line and audit row.
- **Region-scoped logs**: confirm that no logger ships off-region.
  Sentry / OTLP exporters (when added) read `DATA_REGION`.
- **Deploy guide for Azure AKS** (the option Asim flagged at
  ~$350/month, 8c / 64GB / 200GB NVMe), one section per supported
  region. Includes ingress config and TLS termination.
- **CloudBolt vs. AKS decision matrix** in `docker/README.md` so the
  field team knows which to pick per customer.

Acceptance: `docker/azure-aks/eu-west.md` walks a fresh deployer from
zero to a running SCION pinned to one region in under an hour.

---

## v1.24 — Parser integration (depends on Rahul)

Goal: ingest the Tier-3 lineage edges produced by the Parser pipeline
so `/impact` returns real numbers on dictionary-only imports
(Transcend-class data).

- **Edge ingest endpoint**: `POST /api/v1/edges/bulk` accepting the
  format Rahul defines, validated and chunked at 900 (SQLite var
  limit). Idempotent on `(source_id, target_id, edge_type, snapshot_id)`.
- **Edge-source provenance**: each `graph_edge` row gains a
  `source` column (`fk_heuristic` | `parser_feed` | `manual`) so the
  UI can show where lineage came from and we can re-derive on demand.
- **Compose extension**: a sidecar service in the same VM running the
  Parser, sharing the volume that holds the SQLite file. Optional —
  customers who run Parser elsewhere just hit the new endpoint over
  HTTPS.
- **`/impact` smoke test on Transcend** with parser feed loaded:
  expected non-zero impacted-objects KPI on at least 80% of
  changes.

Blocked on: Parser output format from Rahul's team. Email sent
2026-05-05.

---

## v1.25 — Postgres migration (when needed)

Trigger: first multi-region or multi-tenant customer. **Not before.**
Until then SQLite + WAL is fine and lets us iterate fast.

- **`docker-compose.postgres.yml`** override: brings up Postgres 16
  alongside backend, swaps `DATABASE_URL`, mounts a backup volume.
- **Alembic migrations validated against Postgres** in CI (parallel
  job to the existing SQLite parity test).
- **JSON → JSONB** for the columns that benefit from indexed key
  lookups (`change_event.metadata`, `impact_event.payload`).
- **Backup / restore runbook**: `pg_dump` schedule, PITR config,
  restore drill documented.
- **Migration guide**: how to take an existing SQLite SCION instance
  and move it to Postgres without losing history.

Estimated effort once triggered: 1-2 days, given the v1.22 portability
hygiene is in place.

---

## Backlog (no version pinned)

- **TAISA batch reasoning cap** — the reasoning-event generator can
  still spike memory on very large change sets. Cap + paginate.
- **Export / report endpoints** — paginate or stream the existing
  CSV/PDF exports (currently buffer the full result in memory).
- **Extractor packaging** — separate Docker image for the on-prem
  extractor that lives next to the customer's Teradata. Out of scope
  of the main compose; ships independently when Rahul's design lands.
- **Naming audit** — Reunion 9: Kindy noted the "lite" connotation
  is the wrong message. Sweep README, package.json, page titles, any
  user-visible string for residual `Kalido-lite` / `lite` mentions.
- **CI: parity test against Postgres** — same idea as the SQLite
  parity test, blocks merges that introduce dialect drift.
- **Audit log UI** — surface `usage_event` and `reasoning_event` in
  a filterable table for compliance review.
- **SSO / RBAC** — required for any deployment that has more than one
  human user. Likely Azure Entra (formerly AAD) given Teradata's
  ecosystem.

---

## Out of scope (for now)

These have come up in conversation and are explicitly **not** on the
roadmap. Re-raise if priorities change.

- **Kubernetes-native deploy (Helm chart)** — overkill for the
  single-VM topology Rahul described. Revisit if a customer asks.
- **Real-time change detection** — current model is batch-on-demand.
  Streaming detection is a different product.
- **Mobile UI** — desktop-first; mobile is read-only at best and not
  a priority for the steward persona.
- **Custom AI model fine-tuning** — TAISA uses the platform model.
  Fine-tuning is a much bigger commitment than the value justifies
  today.

---

*Last updated: 2026-05-06. Edit this file when scope shifts; don't let
it drift behind reality.*
