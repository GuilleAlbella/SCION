# SCION — Internal Engineering Roadmap

**Audience:** SCION dev team (Guillermo, Helton, anyone joining).
**Not:** product strategy (`docs/Hoja de Ruta del Producto.txt`), demo script
(`docs/demo_en.txt`), or marketing (`docs/use_cases.md`).
**Purpose:** the *engineering* view — what's done, what's next, what's blocked,
who owns each piece, and the gates that have to clear before we ship to a
real customer.

Last updated: 2026-08-03 · Current version: **v1.21.75 (BETA) — Phase 1 final**.

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

## Phase 1 post-v1.0 polish  ✅ DONE (v1.21.44–75)

All items below were shipped after DataDNA Lite v1.0 was declared complete (Reunión 21),
in response to Rahul's round-2 and round-3 observations and internal testing.

### Performance
- [x] Instant Visual Diff + infinite scroll in Changes and Impact (v1.21.45–46)
- [x] Impact engine: eliminate full 337k-node scans on single-change endpoint (v1.21.68)
- [x] Intelligence page: domain card cap + memoized derived data (v1.21.70)
- [x] What-if depth capped to prevent runaway BFS (v1.21.71)

### Import & archive
- [x] Archive import: scan `/mnt/vm1_share/archive`, full progress panel, flat layout detection (v1.21.47–48)
- [x] Share scan: skip `.manifest.csv` and non-data files (v1.21.48)

### Bug fixes — Rahul round-2
- [x] Graph node text overflow (v1.21.55)
- [x] Snapshot comparison: per-category Y-axis scale (v1.21.52 / v1.21.55)
- [x] TAISA server-side search instead of page-filtered (v1.21.55)
- [x] Changes page: correct label for views ("View added/removed") (v1.21.55)
- [x] Graph: "Show database nodes" tooltip added (v1.21.56)
- [x] Usage and Intelligence filters by object/database (v1.21.56)
- [x] UNKNOWN nodes classified as TABLE; Depends On hidden when no edges (v1.21.58)
- [x] TEDW.EVENTS\_V impact was 0 — UNKNOWN type mismatch resolved in graph\_diff\_linker (v1.21.57)

### Bug fixes — Rahul round-3
- [x] Case normalization: parser ingestor + graph builder + frontend lineage resolver (v1.21.74)
- [x] Blast radius usage\_map keys normalized to UPPERCASE (v1.21.74)
- [x] Change-ID search: numeric input matches `change_id` directly (v1.21.74)
- [x] TAISA: uses `activeChangeId` from SelectionContext (v1.21.75)
- [x] TAISA: "New session" button clears chat history (v1.21.75)
- [x] Criticality thresholds moved to env-var overridable config (v1.21.75)

### Metrics cleanup
- [x] Columns excluded from KPI cards, donut chart, trend charts, total\_objects (v1.21.65–67)
- [x] Impact count per domain corrected; graph score normalization fixed (v1.21.72)
- [x] Usage page: dynamic section numbering (v1.21.73)

---

## Phase 2 — Scale & Hardening + ED Integration  🔵 PLANNED

**Trigger:** Phase 1 benchmark results. Phase 2 scope confirmed in Reunión 21 (2026-06-19).
**Owner:** Guillermo. Rahul Kulkarni presenting integration proposal to Rahul Shiyekar 2026-06-23, then to Chris/Pilar week of 2026-06-23.

> **DataDNA Lite v1.0 declared complete by Rahul (Reunión 21, 2026-06-19).** End-to-end testing passed. One minor parser defect assigned to Soham (non-blocking). Solution ready to roll out.

Subject to what the real-data numbers tell us. Likely items:

### 2.0 Column-level lineage enhancements (Reunión 21 feature requests)

Three concrete requests from Rahul after the live demo of column-level lineage:

- [x] **Indirect lineage display** — collapsible "⊿ Indirect impacts" section per column card; amber rows with icon + expression. 10/10 tests. *(v1.21.27)*
- [x] **Transformation-type icons on column nodes** — `TransformBadge` component maps 8 types to Unicode glyphs (→ Σ ⊿ ≠ ƒ ⊞ ⊟) with full-name tooltip; replaces text badges in Sources, Feeds-into, and Indirect sections. *(v1.21.28)*
- [x] **Step / Query ID on edge click** — `step_natural_key` exposed in `ColumnEdge`; clicking a dashed column edge reveals originating SQL step IDs in a dismissable purple panel. *(v1.21.28)*
- [x] **Edge label click bug** — SVG hit-zone overlap caused wrong popup to fire; migrated labels to `EdgeLabelRenderer` (HTML layer) for precise click targets. *(v1.21.39)*
- [x] **Debug panel removed** — yellow debug overlay removed from col-lineage view. *(v1.21.40)*
- [x] **Producers/consumers panel** — long table names now split schema/table, scrollable lists, count badges inline. *(v1.21.41)*
- [x] **Indirect impacts cleanup** — removed "no expression" literal (tier 2 parser never populates expression); deduplicate identical rows into `· N queries` count badge. *(v1.21.42)*
- [x] **Edge label dedup fix** — dedup key changed from `source_column_key` to `(source_column_key, target_column_key)` pair; same source column mapping to multiple targets now all visible. *(v1.21.43)*

### 2.1 Ecosystem Decoded (ED) integration  *(new — Reunión 21)*

**Idea:** Combine SCION's strengths (structure, change intelligence, column-level lineage) with Ecosystem Decoded's strengths (rich usage metrics, business context / user-group mapping).

Ecosystem Decoded is an existing but dormant Teradata service that analyzes CPU usage by user group, table affinity, query complexity, migration readiness, etc. It has data SCION lacks: detailed performance metrics, user-to-group mappings, and some business context.

**Capability gap summary:**

| Dimension | SCION | Ecosystem Decoded |
|---|---|---|
| Structure | ✅ Strong | ❌ Limited |
| Change intelligence | ✅ Strong | ❌ None |
| Lineage | ✅ Column-level | ❌ None |
| Usage | 🟡 Basic | ✅ Strong |
| Business context | ❌ Limited | ✅ Strong |

**Use cases proposed for Phase 2 (from Reunión 21 + ED use-case spreadsheet):**

- [ ] **ED-06 — PII data identification**: AI-based classification of columns as likely PII (name, address, credit card, etc.) + lineage propagation (if source column is PII → downstream columns inherit PII tag).
- [ ] **ED-05 — Duplicate / unused data**: Fuzzy-logic detection of redundant datasets (ED flagged this as SCION-suited).
- [ ] **ED-08 — Archivable data**: Identify data that can be archived (similar to ED-05).
- [ ] **ED-09 — Migration plan**: Build migration plans based on data association / affinity.
- [ ] **ED-10 — Business data use map**: Understand how different business functions use data across the org (sales, marketing, ops, finance). Requires user-group mapping from ED.

**Dependencies / open questions:**
- Rahul Kulkarni presenting proposal to Rahul Shiyekar (2026-06-23).
- Effort estimate for Phase 2 items to be presented to Chris/Pilar week of 2026-06-23.
- ED data format / availability not yet confirmed — Rahul studying with a second person.
- PII propagation via lineage requires column-level lineage to be stable (just shipped v1.21.23).

### 2.2 Incremental snapshot handling *(confirmed Reunión 18)*

- [ ] SCION must compare incremental batches against a "day zero" baseline (not the previous incremental).
- [ ] Track cumulative object count across batches.
- [ ] On full reset (gap in data), create a new day zero and reset baseline.

### 2.3 Dict view-definition parsing *(confirmed Reunión 18 — parser team)*

- [ ] Code Parser to parse view DDLs from the data dictionary (not just DBQL).
- [ ] Covers views created before the extraction window (lineage gaps in DBQL-only mode).
- [ ] Output: same JSON lineage format; SCION ingests alongside existing dict batch.
- [ ] Execution model: run once on "day zero", then incremental via DBQL.

### 2.4 DDL timestamp merge *(confirmed Reunión 19)*

- [ ] Same object can arrive from DBQL extract AND dict extract with different timestamps.
- [ ] SCION must keep the *latest* version (compare DDL timestamps on ingest).
- [ ] Applies to: views, stored procedures, macros, triggers.

### 2.5 SQLite → Postgres (if benchmark says so)
- SQLAlchemy abstracts the engine — bulk of work is operational, not code.
- [ ] Connection-string + driver dependency switch.
- [ ] Run all Alembic migrations against Postgres in a staging DB.
- [ ] Verify FK/cascade behaviour (SQLite is permissive; Postgres isn't).
- [ ] Update `dev.ps1` / Linux scripts for both modes.
- [ ] `DATABASE_URL` env var; default still SQLite for dev.

### 2.6 Graph engine performance
- [ ] Lazy-load graph nodes on demand (today: full snapshot in RAM).
- [ ] Persist computed metrics in DB so re-render doesn't recompute.
      (Partly done — extend.)
- [ ] Index on `change_event(snapshot_id, object_identifier)` if benchmark
      shows slow change queries.
- [ ] Consider Cython / Rust for `compute_impact` if BFS becomes the
      bottleneck (last resort — the algorithm itself is O(N+E)).

### 2.7 Frontend rendering
- [x] Focus mode for /graph (v1.11.00).
- [x] Server-side pagination on /changes (v1.21.50).
- [x] Infinite scroll in Impact sections (v1.21.45).
- [ ] Lazy graph fetch — only request the focused subgraph from backend
      instead of the whole snapshot.

### 2.8 Production runtime
- [x] `docker-compose.yml` — backend + frontend + nginx, deployed on ps-ubuntu-0043 via GHCR images.
- [x] Linux deploy — Docker Compose replaces systemd; no PowerShell dependency in production.
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
| 2026-06-19 | DataDNA Lite v1.0 declared complete by Rahul (Reunión 21) | End-to-end testing passed with Ashish; one minor parser defect (Soham) non-blocking | Reunión 21 |
| 2026-06-19 | Phase 2 expands to include Ecosystem Decoded (ED) integration | Combine SCION structure/lineage with ED usage/business context; Rahul presenting to Rahul Shiyekar 2026-06-23 | Reunión 21 |
| 2026-06-19 | Three column-lineage enhancements queued (indirect lineage, type icons, step ID on edge) | Rahul requests after live demo; non-blocking for v1.0 rollout | Reunión 21 |
| 2026-06-25 | Col-lineage edge labels moved from SVG `label` prop to `EdgeLabelRenderer` (HTML above SVG) | SVG hit-zones (20px invisible) overlap on dense graphs; HTML labels give precise per-label click targets | v1.21.39 |
| 2026-06-25 | Indirect impacts dedup key = `(transformation_type, expression)` | Tier 2 parser stores one row per SQL step for audit trail; dedup at presentation collapses identical rows into a count badge | v1.21.42 |
| 2026-06-26 | Col-lineage edge label dedup key = `(source_column_key, target_column_key)` | Same source column legitimately maps to multiple target columns (e.g. LOG_MIN→_COL6 Direct Copy + LOG_MIN→_COL7 Column Expression); dedup by src alone was collapsing these | v1.21.43 |

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
