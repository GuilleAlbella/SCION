# SCION — Internal Engineering Roadmap

**Audience:** SCION dev team (Guillermo, Helton, anyone joining).
**Not:** product strategy (`docs/Hoja de Ruta del Producto.txt`), demo script
(`docs/demo_en.txt`), or marketing (`docs/use_cases.md`).
**Purpose:** the *engineering* view — what's done, what's next, what's blocked,
who owns each piece, and the gates that have to clear before we ship to a
real customer.

Last updated: 2026-06-18 · Current version: **v1.21.26 (BETA)**.

---

## Phases at a glance

```
  ┌────────────┐   ┌────────────┐   ┌────────────┐   ┌────────────┐   ┌────────────┐
  │  Phase 0   │──▶│  Phase 1   │──▶│  Phase 2   │──▶│  Phase 3   │──▶│  Phase 4   │
  │ Foundations│   │ Pipelines  │   │ Scale &    │   │ Pilot      │   │ v1.0 GA    │
  │ (DONE)     │   │ 2 & 3      │   │ Hardening  │   │ Customer 1 │   │            │
  └────────────┘   └────────────┘   └────────────┘   └────────────┘   └────────────┘
       ✅              🟡 in flight     🔵 planned       🔴 blocked       🔴 future
```

---

## Phase 0 — Foundations  ✅ DONE

The MVP that we demoed in Meeting #7. Ships today as v1.11.00 BETA.

### What's in
- 7 backend engines (graph, impact, criticality, anomaly, co-change,
  volatility, TAISA Q&A).
- Pipeline 1 ingest (parser JSON → snapshots → graph).
- 9 UI pages with guided narrative pattern.
- Hierarchical search + focus mode (Meeting #7 follow-ups).
- 3 architecture docs (`ingestion_pipelines.md`, `use_cases.md`,
  `release_policy.md`).
- ASCII-safe `dev.ps1` runner for Windows PowerShell 5.1.

### Known limitations carried into Phase 1
- SQLite only — no concurrency story, no horizontal scale.
- No auth — local-only deploy.
- Pipeline 2 (dict) wired but not consuming real data.
- Pipelines 3 & 4 not started.
- No real-customer-scale benchmark yet.

---

## Phase 1 — Pipelines 2 & 3, real data benchmark  ✅ DONE

**Owner:** Guillermo. Rahul's team owns the extractors.

### 1.1 Real parser JSON benchmark  ✅
Running against snapshot #8 (Transcend-DevTest, production data on ps-ubuntu-0043).
Decision gate resolved: SQLite performing within targets on current dataset; Postgres deferred to Phase 2 pending future scale data.

| Metric | Target | Status |
|---|---|---|
| Ingest wall time | < 2 min for 10k objects | ✅ within target |
| Graph query p95 | < 500 ms | ✅ within target |
| Impact analysis wall time | < 30 s | ✅ within target |

### 1.2 Pipeline 2 — Data dictionary  ✅ LIVE since v1.12
> Real dict exports from Rahul in production on ps-ubuntu-0043.

- [x] `dict_flat_file_reader.py` (parses §-delimited / `ENDREC` format).
- [x] `dict_persister.py` — persists to schema/table/column snapshot rows.
- [x] `/api/v1/dict-import` endpoint (multipart upload + parse + persist).
- [x] Idempotent re-import keyed by `extract_run_id` (v1.13.01).
- [x] Share import: auto-scan + one-click Import All + manual file picker (v1.21.16).
- [x] Share scan: already-imported detection before clicking Import All (v1.21.26).
- [x] Integration tests against Rahul's sample (29 tests, 12 types).

### 1.3 Pipeline 3 — PDCR Usage statistics  ✅ LIVE since v1.21.6
> 6-PR sprint shipped 2026-05-29. Format: `pdcr_object_usage_*.dat` (§-delimited).

- [x] `pdcr_flat_file_reader.py` + `pdcr_persister.py`.
- [x] Wired into dict-import pipeline (PDCR files auto-detected in same batch).
- [x] Wire into `criticality_engine.py` — real usage weight (60% usage + 40% graph).
- [x] Case-insensitive lookups across graph resolver, diff linker, usage criticality (v1.21.20).
- [x] Build-node-index orphan root cause fixed — qualified name prefix stripping (v1.21.19).
- [x] PDCR ingest: 997 rows now inserted correctly (was 0 before fix).

### 1.4 Internal handover doc for Helton
- [x] `docs/handover.md` — written and current.

---

## Phase 2 — Scale & Hardening  🔵 PLANNED

**Trigger:** Phase 1 benchmark results.
**Owner:** Helton + Guillermo on return.

Subject to what the real-data numbers tell us. Likely items:

### 2.1 SQLite → Postgres (if benchmark says so)
- SQLAlchemy abstracts the engine — bulk of work is operational, not code.
- [ ] Connection-string + driver dependency switch.
- [ ] Run all Alembic migrations against Postgres in a staging DB.
- [ ] Verify FK/cascade behaviour (SQLite is permissive; Postgres isn't).
- [ ] Update `dev.ps1` / Linux scripts for both modes.
- [ ] `DATABASE_URL` env var; default still SQLite for dev.

### 2.2 Graph engine performance
- [ ] Lazy-load graph nodes on demand (today: full snapshot in RAM).
- [ ] Persist computed metrics in DB so re-render doesn't recompute.
      (Partly done — extend.)
- [ ] Index on `change_event(snapshot_id, object_identifier)` if benchmark
      shows slow change queries.
- [ ] Consider Cython / Rust for `compute_impact` if BFS becomes the
      bottleneck (last resort — the algorithm itself is O(N+E)).

### 2.3 Frontend rendering
- [x] Focus mode for /graph (v1.11.00).
- [ ] Server-side pagination on /changes if event count crosses 10k.
- [ ] Lazy graph fetch — only request the focused subgraph from backend
      instead of the whole snapshot.

### 2.4 Production runtime
- [ ] `docker-compose.yml` — backend + frontend (production build) +
      optional Postgres.
- [ ] Linux systemd units (no PowerShell in production).
- [ ] Health check endpoints (`/healthz`, `/readyz`).
- [ ] Structured JSON logging (today: stdout text).

---

## Phase 3 — First Customer Pilot  🔴 BLOCKED on Phase 2 + infosec

**Owner:** Guillermo + Helton + Rahul Shiyekar (infra).

Per Kindy's warning in Meeting #7: cannot install at customer until release
discipline is in place.

### 3.1 Cloud test machine  *(in progress, Meeting #8)*
- [ ] Rahul Shiyekar provisions VM (target: 4×8×40, see `release_policy.md`).
- [ ] Install SCION, run benchmark from Phase 1.1 against real data.
- [ ] Internal tester walkthrough (Pilar's team) before exposing to customer.

### 3.2 Authentication
- [ ] Decide: HTTP Basic behind nginx? SSO via Teradata IDP? Reverse-proxy
      with the customer's existing auth?
- [ ] Implement minimal viable option.
- [ ] Audit: no PII in logs, no row-level data exfiltration via TAISA.

### 3.3 Release discipline (per `release_policy.md`)
- [ ] Tag v1.0.0-rc1 once Phase 2 lands.
- [ ] Write `ROLLBACK.md` for that tag.
- [ ] Verify Alembic down-migrations work end-to-end.
- [ ] Smoke-test `dev.ps1` walkthrough against fresh seed.

### 3.4 Use-case validation sessions
- [ ] Kindy organizes 30-min sessions with 6–8 architects (2 per region).
- [ ] We bring `docs/use_cases.md` as straw-man, they redline.
- [ ] Aggregate findings into a one-pager for sales.

---

## Phase 4 — v1.0 GA  🔴 FUTURE

**Trigger:** all GA criteria in `docs/release_policy.md` §3 satisfied.

When we flip `APP_STAGE` from `"BETA"` to `""`. Concrete sign-off needed
from: Chris (scope), Kindy (sales-readiness), Rahul (extractor stability),
infosec.

---

## Cross-cutting backlog (no specific phase)

Things to do whenever there's slack — none of them block a phase.

### Tooling TODO
- [ ] `tools/benchmark_ingest.py` — runs an ingest end-to-end and prints
      the table from §1.1. Useful for any future scaling decision.
- [ ] `tools/bump_version.ps1` — single-command version bump:
      updates `constants.ts`, prepends README changelog, optionally tags.
      *(See response in this thread for the spec.)*
- [ ] CI on push: `npx tsc --noEmit` + `pytest backend/tests/`.

### Tests
- [ ] Backend coverage on `graph/` and `metrics/` to 60% (release-policy gate).
- [ ] Frontend smoke tests for the 3 main pages (Lineage, Impact, Graph).
- [ ] Regression test for the v1.10.03 column→parent fallback (Impact).

### Docs
- [x] `ingestion_pipelines.md`
- [x] `use_cases.md`
- [x] `release_policy.md`
- [ ] `handover.md` (Phase 1.4)
- [ ] `CHANGELOG.md` separated from README (release-policy gate).
- [ ] `INSTALL.md` for Linux (when Phase 2.4 lands).

### Pipeline 4 — raw code  🔴 FUTURE
Defer until at least one customer asks for it. Today the parsed tree is
enough for impact / lineage; raw text only matters for code-diff UI which
is a v1.x feature, not a v1.0 feature.

---

## Decision log (key past decisions, so we don't re-litigate)

| Date | Decision | Rationale | Source |
|---|---|---|---|
| Pre-2026-04 | SCION never connects to customer DB | Committee | Meeting #7, Luis |
| 2026-04-15 | Migrate UI from Streamlit to Next.js+React | Performance, narrative UX | MEMORY.md |
| 2026-04-22 | Centralize `APP_VERSION` in constants.ts | Single source of truth | v1.06 |
| 2026-04-22 | Rename "Blast radius" → "Impact spread" | User feedback | v1.09 |
| 2026-04-22 | Column changes redirect to parent table for lineage | Columns aren't graph nodes | v1.10.02 / 03 |
| 2026-04-22 | FK direction in graph: referenced → fk_holder | Semantic correctness | v1.10.00 |
| 2026-04-23 | Hierarchical + searchable object picker | Meeting #7 (Rahul, Kindy) | v1.11.00 |
| 2026-04-23 | Graph focus mode (N-hop BFS) | Meeting #7 (Kindy, 500M-edge case) | v1.11.00 |
| 2026-04-23 | Benchmark with real JSON before SQLite/Postgres decision | Avoid premature optimization | This roadmap |
| 2026-05-07 | Helton takes over while Guillermo on vacation | — | Meeting #8 |
| 2026-05-29 | Pipeline 3 (PDCR usage) shipped — 6 PRs | Rahul request; real usage data for criticality engine | v1.21.6 |
| 2026-06-18 | Column-level lineage exposed via `/lineage/columns` + full UI panel | Rahul explicit request in Reunión 20: "real distinguishing point from user perspective" | v1.21.23 |
| 2026-06-18 | Column lineage dedup in API layer (not DB) | Parser intentionally stores one row per SQL step for audit trail; dedup at presentation layer preserves traceability | v1.21.24 |
| 2026-06-18 | Share scan now checks already-imported before user clicks Import | UX: user should know before clicking, not after | v1.21.26 |

---

## Owner cheat-sheet

| Area | Primary | Secondary |
|---|---|---|
| Backend engines | Guillermo / Helton | — |
| Frontend | Guillermo / Helton | — |
| Pipeline 1 (parser) | Rahul (extract) | Guillermo (ingest) |
| Pipeline 2 (dict) | Rahul (extract) | Helton (ingest) |
| Pipeline 3 (usage) | Rahul (extract) | Helton (ingest) |
| Infra / VM | Rahul Shiyekar | Pilar (coord) |
| Release / scope | Chris | Kindy |
| Sales / use cases | Kindy | Luis |
| Project mgmt / time-tracking | Pilar | Luis |
