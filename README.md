# Project SCION

**Structural Change Intelligence Platform**

SCION is a proprietary platform that replaces Kalido within Teradata DNA. It monitors structural changes across the data warehouse, assesses impact, and provides AI-powered risk recommendations — with full TAISA conversational Q&A, "what-if" simulation, and DataDNA parser integration.

**Version:** BETA v1.13.05

---

## Architecture

SCION is built on **7 independent engines** orchestrated through a REST API with a modern web UI. **All inputs come from offline extractor files** — SCION never connects to a customer database directly (committee decision).

```
┌─────────────────────────────────────────────────────────────────────┐
│  External extractors (owned by the parser/dict team)                │
│  ┌──────────────────┐    ┌──────────────────────┐                    │
│  │  DataDNA Parser  │    │  Data Dictionary     │                    │
│  │  (lineage JSON)  │    │  Extractor (6 .dat)  │                    │
│  └────────┬─────────┘    └────────┬─────────────┘                    │
│           │ POST /parser-import    │ POST /dict-import                │
└───────────┼────────────────────────┼──────────────────────────────────┘
            ▼                        ▼
       ┌──────────────┐         ┌──────────────┐
       │   Parser     │         │  Dict batch  │
       │   Ingest     │         │  validator + │
       │  subsystem   │         │  persister   │
       └──────┬───────┘         └──────┬───────┘
              └─────────┬───────────────┘
                        ▼
Snapshot → Diff → Graph & Impact → TAISA Reasoning
                              ↗
        Usage & Criticality → Intelligence Metrics
```

| Engine | Purpose |
|--------|---------|
| **Parser Ingest** | Consumes DataDNA parser JSON feeds (Tier 1/2/3 lineage), with noise filter + dry-run |
| **Data Dictionary Ingest** | Consumes 6-file `.dat` batch from the dict extractor, validates source + run_id + temporal coherence, persists as one snapshot keyed by `extract_run_id` |
| **Snapshot Engine** | Full EDW state capture, structural SHA-256 hashing, historical versioning |
| **Diff Engine** | 10+ change types, severity scoring, breaking-vs-compatibility classification |
| **Graph & Impact** | SQL-native dependency graph, blast radius, fragility, query-count integration |
| **Usage & Criticality** | Usage frequency scoring, combined criticality (60% usage + 40% graph) |
| **Intelligence Metrics** | Governance scorecard, domain risk, volatility, stability timeline |
| **TAISA AI Layer** | LLM-powered conversational Q&A with full SCION access |

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.11+, FastAPI, SQLAlchemy 2.0, Alembic |
| Frontend | Next.js 16, React 19, TypeScript, Tailwind CSS v4 |
| Database | SQLite (demo), PostgreSQL-ready |
| Charts | Recharts |
| Graphs | React Flow (@xyflow/react) + dagre layout |
| Data fetching | SWR + Axios |
| AI | TAISA conversational layer |

---

## Project Structure

```
backend/
  app/
    api/v1/              # REST API endpoints
      parser_import.py   #   POST /parser-import (JSON pipeline, v1.04+)
      dict_import.py     #   POST /dict-import (.dat batch pipeline, v1.12+)
      ...                #   snapshots, diff, graph, impact, …
    db/                  # ORM models (SQLAlchemy) — 14 tables
      models/            #   snapshot, schema_snapshot, table_snapshot,
                         #   column_snapshot, process, step, attribute_lineage, …
    ddl/                 # DDL generator engine
    diff/                # Diff engine + rules + models
    graph/               # Graph builder, impact analyzer, blast radius
    llm/                 # LLM provider abstraction (mock + real backend)
    metadata/            # Data-dictionary readers + validators + persisters
      dict_flat_file_reader.py   #   §-delimited / ENDREC reader
      format_detector.py         #   Content-based JSON vs .dat dispatch
      dict_batch_validator.py    #   Same source + run_id + temporal coherence
      dict_persister.py          #   Snapshot keyed by extract_run_id
      teradata_type_formatter.py #   2-char TD codes → canonical types
    metrics/             # Intelligence metrics engine
    parser_ingest/       # DataDNA parser JSON integration (v1.04)
      parser_models.py   #   Internal dataclasses (ParsedLineagePayload, …)
      teradata_parser.py #   Raw JSON → internal payload
      noise_filter.py    #   Drop NOT APPLICABLE / UNKNOWN / literals
      ingestor.py        #   Persist payload into SCION tables
      dry_run.py         #   Analyze without persisting
    snapshot/            # Snapshot engine, structural hash, metrics
    taisa/               # TAISA client, prompts, algorithm knowledge base
    usage/               # Usage ingestor, criticality engine
  tests/                 # pytest — metadata, graph, diff, taisa, api
  tools/                 # bootstrap_sqlite_db.py, rich_seed.py, fixtures

frontend/
  src/
    app/                 # Next.js App Router (14 pages)
    components/          # Shared UI components (Sidebar, GuidedSection, …)
    lib/                 # API clients, hooks, context, terminology, constants

Parser/                  # Sample payloads from the extractor team
  lineage-mvp.json       # Parser v1 JSON sample
  Data extract 2/        # Data dictionary spec + first real .dat sample
    README.md            #   16-col layout spec
    Sample 1/            #   6 rendered .dat files (Transcend-DevTest)
```

---

## UI Pages (13)

| Page | Description |
|------|-------------|
| **Dashboard** | Mission control: animated KPIs, engine status, processing pipeline, breaking changes ticker, recent activity |
| **Snapshots** | List snapshots, **3 ways to create**: capture live (demo backing DB), import parser JSON (two-phase preview/confirm), import dict `.dat` batch (multi-file drag-and-drop with coverage indicator). **Protected delete** with typed-ID confirmation |
| **Changes** | Compare snapshots, filters, expandable before/after, **DDL Generator**, **Visual Diff**, **quick links** to Lineage/Timeline/Impact/Usage, **CSV export** |
| **Impact Analysis** | Batch blast radius, donut charts, per-change table with **queries/users affected**, **Export Report** (HTML), **CSV export**, confetti on LOW risk |
| **What-If Simulation** | Preview a hypothetical change's impact without applying it |
| **Data Lineage** | Interactive ReactFlow graph centered on selected object (accepts `?object=X`) |
| **System Graph** | Full dependency visualization, 10+ object types each with own color |
| **Metrics** | Volatility index, trends, **Structure Change Timeline** |
| **Usage** | Usage heatmap, criticality distribution, **Risk Heatmap**, focused-object highlighting |
| **Intelligence** | Governance Report: **Structural Stability**, domain risk cards, volatility indicator, **CSV export** |
| **Timeline** | Object evolution across snapshots (accepts `?object=X`) |
| **Alerts** | 6 alert types: breaking, high-severity, TAISA risk, broken lineage, orphan objects, hub changes |
| **Control** | Engine stop/restart |

### Global Features

| Feature | Description |
|---------|-------------|
| **TAISA Widget** | Floating AI chatbot on every page. Full SCION data + algorithm knowledge, multilingual |
| **Global Search** | `Ctrl+K` command palette — searches graph nodes + change events |
| **Dark Mode** | Toggle in sidebar. Persists in localStorage |
| **Keyboard Shortcuts** | `?` for panel. `G+D/C/I/W/L/A/T` for navigation |
| **Toast Notifications** | Animated feedback on diff, DDL, impact, delete |
| **Info Tooltips** | Hover/click `?` icons for metric explanations |

---

## API Endpoints

### Core
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/health` | System health + engine status |
| POST | `/api/v1/snapshots` | Capture live snapshot |
| GET | `/api/v1/snapshots` | List all snapshots |
| DELETE | `/api/v1/snapshots/{id}?confirm_id=X` | Delete latest snapshot (protected, cascade) |

### Ingest pipelines
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/parser-import/lineage?dry_run=true\|false` | Import DataDNA parser JSON. Dry-run returns preview; real run persists snapshot + process + step + attribute_lineage |
| POST | `/api/v1/dict-import` | Multipart upload of 1–6 dict `.dat` files. Auto-detects content type per file, validates batch consistency (source + run_id + temporal coherence), persists as one snapshot keyed by `extract_run_id`. Idempotent re-import |

### Diff & Changes
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/diff` | Run diff between two snapshots |
| GET | `/api/v1/diff/{from}/{to}/details` | Full diff details with cumulative changes |
| GET | `/api/v1/changes` | List recent change events |

### Graph, Impact & Simulation
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/graph/{snapshot_id}` | Graph nodes + edges with metrics |
| POST | `/api/v1/impact/{change_id}` | Impact analysis for single change |
| POST | `/api/v1/impact/batch` | Batch impact + queries affected |
| POST | `/api/v1/simulation` | What-If hypothetical change impact |

### Reasoning, Intelligence & Usage
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/reasoning/diff/{from}/{to}` | TAISA batch reasoning over a diff |
| POST | `/api/v1/reasoning/change/{change_id}` | Single-change deep-dive |
| GET | `/api/v1/intelligence/{snapshot_id}` | Governance scorecard, volatility trend |
| GET | `/api/v1/usage` | Usage events + criticality |

### Reports, Export, Timeline, Search, Alerts, DDL, Control, Schema-tree
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/report/{from}/{to}` | HTML impact report |
| GET | `/api/v1/export/{kind}/{params}` | CSV exports for changes / impact / intelligence / usage |
| GET | `/api/v1/timeline/{object}` | Object evolution across snapshots |
| GET | `/api/v1/search?q=...` | Cross-cutting search over graph nodes + change events |
| GET | `/api/v1/alerts` | Breaking, high-severity, broken-lineage, hub, orphan alerts |
| POST | `/api/v1/ddl/generate` | DDL generator for selected change events |
| POST | `/api/v1/control/{engine}/stop\|restart` | Engine lifecycle control |
| GET | `/api/v1/schema-tree/{snapshot_id}` | Hierarchical view: database → table → column |

---

## Database Schema (14 tables)

| Table | Purpose |
|-------|---------|
| `snapshot` | EDW state versions (now with indexed `extract_run_id` column for dict-import idempotency, v1.13.01) |
| `schema_snapshot` | Databases within a snapshot |
| `table_snapshot` | Tables/views within a database |
| `column_snapshot` | Columns with types and positions |
| `change_event` | Detected changes |
| `graph_node` | Dependency graph nodes |
| `graph_edge` | FEEDS and DEPENDS_ON relationships |
| `impact_event` | Impact analysis results |
| `reasoning_event` | TAISA reasoning results |
| `usage_event` | Usage statistics |
| `object_criticality` | Criticality scores |
| **`process`** | **NEW v1.04 — SQL scripts/jobs from parser** |
| **`step`** | **NEW v1.04 — statements / query blocks inside processes** |
| **`attribute_lineage`** | **NEW v1.04 — Tier 1/2 column-to-column lineage with expressions** |

---

## Ingest Pipelines

SCION accepts data from offline extractors only — never connects directly to a customer database (committee decision). Two pipelines are live today; two are planned. Architecture details in `docs/ingestion_pipelines.md`.

### Pipeline 1 — Parser BTEQ/SQL (live since v1.04)

Consumes a JSON parse-tree of CREATE / INSERT / view DDLs. The producer emits 7 entity types (platform, containers, datasets, attributes, processGroups, processes, steps) plus 3 tiers of lineage edges (Tier 1 query-block-level, Tier 2 statement-level, Tier 3 dataset-level) and a consolidated `lineageFactAttribute` fact table.

**Internal flow:**

```
raw JSON
    │
    ▼
teradata_parser.parse()    → ParsedLineagePayload (validated, structured)
    │
    ▼
noise_filter.apply()       → removes NOT APPLICABLE / UNKNOWN / literals
    │
    ▼
ingestor.ingest()          → persists Snapshot + schema/table/column +
                             graph_edge + process + step + attribute_lineage
    │
    ▼
(or) dry_run.analyze()     → returns stats without persisting
```

### Pipeline 2 — Data dictionary (live since v1.12)

Consumes a 6-file `.dat` batch from `DBC.DatabasesV` / `TablesV` / `ColumnsV` / `IndicesV` / `PartitioningConstraintsV` / `TableTextV`. The wire format is `§`-delimited, `ENDREC`-terminated for tabletext, with a fixed 16-column layout for the rest (spec in `Parser/Data extract 2/README.md`).

**Internal flow:**

```
1–6 .dat files
    │
    ▼
format_detector.detect()      → classify each file by content (filename is tiebreaker)
    │
    ▼
dict_flat_file_reader.*       → §-split, validate arity, build typed records
    │
    ▼
dict_batch_validator.*        → enforce same source + run_id + temporal coherence
    │
    ▼
dict_persister.persist_batch()→ one snapshot keyed by extract_run_id (idempotent)
```

Tested end-to-end against the real sample at `Parser/Data extract 2/Sample 1/` (`Transcend-DevTest`, 6 files × 10 records = 60 records). 41 metadata tests pass, including 9 edge-case temporal-coherence tests added in v1.13.01.

### Pipelines 3 & 4 — Usage and raw code (planned)

Out of scope for the current build. Same architecture: offline extractor produces files, SCION consumes. See `docs/ingestion_pipelines.md` for the full 4-pipeline picture.

---

## TAISA AI Engine

TAISA (Teradata AI System Advisor) — the reasoning layer:

- **Batch Analysis**: classification + risk level + recommendations for a full diff
- **Single-Change Analysis**: deep dive on individual changes
- **Conversational Q&A**: multi-turn chat with full SCION DB + algorithm knowledge
- **Algorithm-aware**: can explain WHY metrics have their value using exact formulas
- **Floating Widget**: available on every page
- **Multilingual**: responds in the user's language

Scalable context strategy (token usage stays ~constant regardless of DB size):
- Always loaded: aggregates, top-N usage, algorithm knowledge (~800 tokens)
- On-demand: detailed rows only when question requires it
- Hard caps: 50 changes, 30 impacts, 10 usage rows max

---

## Quick Start

### Prerequisites

- Python 3.11+ with pip
- Node.js 18+ with npm

### Setup

```bash
# Backend
cd backend
python -m venv ../.venv
../.venv/Scripts/activate   # Windows
pip install -r requirements/dev.txt

# Frontend
cd frontend
npm install

# Database
cd backend
python tools/bootstrap_sqlite_db.py
python tools/rich_seed.py
```

### Run

```powershell
# From project root (Windows PowerShell)
.\dev.ps1
```

Opens at **http://localhost:3000**

### Try an ingest

**Pipeline 1 (parser JSON)** — via HTTP:

```bash
curl -X POST "http://localhost:8000/api/v1/parser-import/lineage?dry_run=true" \
     -H "Content-Type: application/json" \
     -d @Parser/lineage-mvp.json
```

**Pipeline 2 (dict `.dat` batch)** — via the UI: open http://localhost:3000/import and drag the 6 files from `Parser/Data extract 2/Sample 1/` onto the drop zone. Or via curl:

```bash
curl -X POST http://localhost:8000/api/v1/dict-import \
  -F "files=@Parser/Data extract 2/Sample 1/databasesv_full_export.rendered.dat" \
  -F "files=@Parser/Data extract 2/Sample 1/tablesv_full_export.rendered.dat" \
  -F "files=@Parser/Data extract 2/Sample 1/columnsv_full_export.rendered.dat" \
  -F "files=@Parser/Data extract 2/Sample 1/indicesv_full_export.rendered.dat" \
  -F "files=@Parser/Data extract 2/Sample 1/partitioningconstraintsv_full_export.rendered.dat" \
  -F "files=@Parser/Data extract 2/Sample 1/tabletextv_full_export.rendered.dat"
```

Returns a JSON response with the new `snapshot_id` plus per-category counts (schemas / tables / columns / indices / partitioning / tabletext). Re-running with the same files is idempotent.

---

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `SCION_TAISA_MODE` | `real` | `mock` or `real` (TAISA backend) |
| `SCION_BACKEND_HOST` | `127.0.0.1` | |
| `SCION_BACKEND_PORT` | `8000` | |
| `API_KEY` | _(not set)_ | Optional endpoint auth |
| `DATABASE_URL` | SQLite demo | |

TAISA LLM settings in `backend/app/config/taisa_llm.yaml`.

---

## Terminology

SCION uses Teradata-native terminology in the UI while keeping backend field names engine-agnostic:

| Backend field | UI label | Reason |
|---------------|----------|--------|
| `schema_name` | **Database** | Teradata uses "database" instead of "schema" |
| `overall_health` | **Structural Stability** | Avoids implying operational failures |
| `container` (parser) | **Database** | Aligned with Teradata convention |
| `dataset` (parser) | **Table / View / ...** | Classified by `datasetType` |

Supported object types: Database, Table, View, Stored Procedure, Macro, Function, UDF, Trigger, Index, Sequence, Column.

---

## Roadmap

The engineering roadmap (phases, gates, owners, decision log) lives in **`docs/internal_roadmap.md`** — the canonical place to look for "what's next, who owns it, and what's blocking what".

Top-level phases at a glance:

| Phase | Status | Highlights |
|-------|--------|------------|
| **0 · Foundations** | ✅ Done | 7 engines, 14 UI pages, parser + dict ingest, narrative UX |
| **1 · Pipelines 2 & 3** | 🟡 In flight | Pipeline 2 (dict) live; Pipeline 3 (usage) format pending |
| **2 · Scale & hardening** | 🔵 Planned | Benchmark on real data, SQLite→Postgres decision, Docker packaging |
| **3 · First customer pilot** | 🔴 Future | Auth, infosec, release discipline (`docs/release_policy.md`) |
| **4 · v1.0 GA** | 🔴 Future | Flip `APP_STAGE` from `BETA` once GA criteria are satisfied |

Other docs worth reading once: `docs/use_cases.md` (what SCION does in 8 bullets), `docs/handover.md` (first-day setup for new maintainers), `docs/release_policy.md` (versioning + rollback), `docs/ingestion_pipelines.md` (architecture of the 4 input pipelines).

---

## Changelog

### v1.13.05 (2026-04-29) — Test isolation: stop wiping the developer's DB

**Critical bug fix.** Most tests under `backend/tests/` (diff/, snapshot/,
graph/, api/, taisa/) imported the global engine from `app.db.engine`
and called `Base.metadata.drop_all/create_all` against it. Without
redirection, those tests wiped the developer's working `kalido_lite.db`
on every `pytest` run — including the rich-seed demo data and any
imported customer snapshots. We hit this for real on this branch:
a routine `pytest backend/tests/` torched the demo DB.

Fix in `backend/tests/conftest.py`:

- **Engine redirection** — `_ensure_test_database_url()` sets
  `DATABASE_URL` to a per-PID file under `tempfile.gettempdir()`
  *before* any `app.db.engine` import. Since the engine reads the
  env var at module import time, this must happen in `conftest.py`
  (loaded by pytest before any `test_*.py`); a fixture would be
  too late.
- **Sanity guard** — `pytest_configure` aborts the run with a clear
  error if the engine ends up pointed at a path that looks like the
  developer's working DB (`<root>/kalido_lite.db` or
  `<root>/backend/kalido_lite.db`). Defence in depth — if a future
  refactor breaks the env redirection, the next run fails loudly
  instead of silently destroying data.
- **CI compatibility** — if `DATABASE_URL` is already set by the
  caller (CI injecting a test DB), we respect it. We only intervene
  when nothing's been configured, which is the dangerous default
  on a developer machine.

19 test files use the global engine destructively; rather than
refactor each one to use `tmp_path`, the conftest fix is one place,
no behaviour change inside the tests, no risk of missing one. The
test count regressed 44→46 fails because two tests that were
"passing by luck" (depending on whichever data the developer's DB
happened to have) now correctly fail against a clean DB. Those are
tracked as a separate cleanup task — they need per-test fixtures.

Verified end-to-end: demo DB had 10 snapshots before pytest, has 10
snapshots after pytest. Bomb defused.

### v1.13.04 (2026-04-29) — Usage page scoped to selected snapshot

`/usage` was showing demo-seed data (`core_banking.transactions`,
`reporting.daily_pl_summary`, etc.) even when a dict-imported snapshot
like `Transcend-DevTest` was selected. Root cause: `UsageEvent` rows
have no `snapshot_id` column (the table was designed as a "global"
usage feed before the per-snapshot model firmed up), and the
`/usage/summary` endpoint aggregated every row regardless of the
selected snapshot.

Fix:

- **Backend** — `GET /api/v1/usage/summary` now accepts an optional
  `snapshot_id` query param. When passed, the aggregation is filtered
  to only objects present in that snapshot's `graph_node` set
  (joining on `object_name`). When omitted, legacy global behaviour
  is preserved for any caller that may still rely on it.
- **Frontend** — the `/usage` page now re-fetches the summary every
  time the user picks a snapshot, passing the snapshot ID through.
  Without a snapshot selected the heatmap is empty. A snapshot whose
  objects don't appear in any `usage_event` row (typical for
  dict-imported snapshots until pipeline 3 lands) gets an empty list,
  which is the correct answer rather than the misleading "global
  bleed-through" we had before.

No schema migration needed — we filter by joining on `object_name`.
Adding a proper `snapshot_id` column to `UsageEvent` is the right
long-term fix but was deferred because it would require backfilling
every demo-seed row and isn't blocking anything.

### v1.13.03 (2026-04-29) — Dict snapshot post-ingest pipeline

The v1.12 dict-import was leaving snapshots in a half-baked state: rows
landed in `snapshot` / `schema_snapshot` / `table_snapshot` /
`column_snapshot`, but the analytical pipeline that fills `graph_node` /
`graph_edge` / `snapshot_metrics` / `object_criticality` never ran.
Result: a fresh dict-import showed up in `/snapshots` but every other
page (`/graph`, `/lineage`, `/metrics`, `/usage`, `/intelligence`,
`/impact`) reported the snapshot as empty.

Fix:

- **`run_post_ingest_pipeline(snapshot_id)`** — new public function
  in `dict_persister.py`. Calls in order: `compute_structural_hash`,
  `compute_snapshot_metrics`, `build_graph_for_snapshot`,
  `persist_node_metrics`, `compute_criticality(usage_available=False)`.
  Each step is wrapped in try/except + log so a failure in one
  metric doesn't abort the whole pipeline.
- **Endpoint hook** — `POST /api/v1/dict-import` now calls
  `run_post_ingest_pipeline(result.snapshot_id)` after a successful
  commit. Skipped on idempotent re-imports (the prior run already
  did the work).
- **Why `usage_available=False`** — dict-import doesn't bring usage
  data; pipeline 3 (usage extractor) is still planned. The
  graph-only criticality fallback (added in v1.08 for exactly this
  scenario) keeps `/usage` and `/intelligence` populated. Combined
  score equals the graph score; HIGH/MEDIUM/LOW thresholds
  unchanged at 0.6 / 0.3.
- **Verified end-to-end** against the user's already-imported
  snapshot #11 (`Transcend-DevTest`): backfilled to 30 graph nodes,
  10 edges, structural hash, 30 criticality rows. Future imports
  run the pipeline automatically.

### v1.13.02 (2026-04-29) — Consolidate Import into Snapshots

The standalone `/import` page added in v1.13.00 was redundant: Snapshots
already had an "Import from Parser" button, and a separate top-level
nav entry for "Import" duplicated the same conceptual action ("create a
snapshot from a file").

Consolidation:

- **Snapshots page** gains a third action: **"Import Dict Batch"**
  (blue button, distinct from the orange parser button). Clicking it
  toggles a drag-and-drop panel inline below the action row, with the
  same coverage indicator and result card the standalone page had.
- **`/import` route deleted.** Sidebar entry removed. The
  `dict_import.ts` API client stays — it's the typed wrapper around
  the multipart endpoint and was always meant to be reused.
- **Intro text updated** to describe all three creation paths
  (capture live / parser JSON / dict batch) instead of mentioning a
  v1.10 plug-in point that never materialised.

No backend changes — the `POST /api/v1/dict-import` endpoint is
unchanged. Pure frontend reorganisation; users get one less nav item
and a single page to manage all snapshot creation.

### v1.13.01 (2026-04-29) — Batch validator: stricter temporal checks

Defence-in-depth for `dict_batch_validator`. We were trusting the
`extract_run_id` alone as proof that 6 files belonged to one
extraction run. That's correct in 99.9% of cases (Rahul generates
run_id once per orchestration as `timestamp_UUID`), but doesn't
catch the edge case where someone hand-stitches files from a
paused or partially re-run extraction that happens to share a
run_id.

Two new checks, both within a single `extract_run_id`:

1. **Same `snapshot_date`** across all files. Catches "files cross
   midnight" — a coherent run finishes within hours, never spans a
   day boundary.
2. **`extracted_at_utc` drift ≤ 2 hours.** Catches paused
   orchestrations and concatenated batches. The 2-hour window is
   generous for Lloyds-scale customers running multi-million-row
   TPT exports back-to-back, while still rejecting anything that
   crossed a meaningful time gap.

Both errors emit the offending filenames and timestamps so the user
knows immediately which file to investigate. Unparseable timestamps
silently skip the check rather than blocking — the reader's arity
validation would have caught a truly malformed record before this
code runs.

9 new tests in `test_batch_temporal_coherence.py`. All 41 metadata
tests pass.

### v1.13.00 (2026-04-29) — Dict ingest UI + handover + hardening

Follow-ups on top of v1.12.00 that don't depend on Rahul's pending
format-direction reply, so the team has something to test against
while we wait for his answer.

**Frontend**
- New `/import` page with drag-and-drop for the 6-file dict batch.
  Coverage indicator (which views are present), per-file remove,
  inline result panel with snapshot_id and counts, server errors
  rendered verbatim (the batch-validator emits a multi-line diff that
  we want users to see in full). Sidebar gains an "Import" entry.
- `frontend/src/lib/api/dict_import.ts` — typed Axios client for the
  multipart endpoint. Mirrors the response shape from the backend so
  TypeScript flags drift if/when the contract changes.

**Backend**
- Alembic migration `a72b8c4f9d31` — adds a dedicated, indexed
  `extract_run_id` column to `snapshot`. Replaces the fragile
  `description LIKE '%extract_run_id=...%'` idempotency lookup. The
  description-side hint stays for one release for backward
  compatibility (drop in v1.14).
- `dict_persister.py` — writes the new column on insert and reads
  both the column and the legacy description as a transitional
  fallback.

**Tests**
- 17 new edge-case tests for `format_detector.py`: empty / whitespace
  input, JSON with BOM / leading whitespace / unknown shape,
  flat-files with and without filename hints, arity drift, garbage /
  XML / CSV. All pass.

**Docs**
- `docs/handover.md` — first-day checklist, conventions,
  Windows gotchas, decision-not-to-relitigate list, who-to-ping.
  Written before Guillermo's vacation (2026-05-07) so Helton can pick
  up cold.

### v1.12.00 (2026-04-29) — Data dictionary ingest pipeline (Sample 1 wired)

End-to-end implementation of Pipeline 2 (data dictionary). Validated
against Rahul's first real sample at `Parser/Data extract 2/Sample 1/`.

**What's in**

- `backend/app/metadata/dict_flat_file_reader.py` — rewritten to
  match Rahul's real 16-column fixed layout (was a guessed 12-col
  layout with 5 tech fields including `row_hash`; reality is 4 tech
  fields and a strict 16-col TPT-friendly layout). TableTextV stays
  on its 9-field, ENDREC-terminated path.
- `backend/app/metadata/format_detector.py` — new. Inspects bytes
  (not extension) to classify JSON vs flat-file, then disambiguates
  to one of 7 content types: `parser_lineage` for JSON or one of the
  6 dict views for `.dat`. Filename is used as a tiebreaker only.
- `backend/app/metadata/dict_batch_validator.py` — new. Enforces
  that all files in a batch share the same `source_system_name` and
  `extract_run_id` (Rahul's per-run UUID). Raises a clear error
  diff when files disagree, preventing silent snapshot corruption
  from mixing two extraction runs.
- `backend/app/metadata/dict_persister.py` — new. Persists a
  validated batch as one SCION snapshot keyed by `extract_run_id`.
  Idempotent: re-importing the same batch is a no-op (lookup by
  `extract_run_id` substring in `snapshot.description`).
- `backend/app/api/v1/dict_import.py` — new endpoint
  `POST /api/v1/dict-import`. Multipart upload of 1–6 files, any
  order. Each file is auto-routed by content-type detection. Returns
  per-category counts in the response for UI feedback.
- `backend/tests/metadata/test_dict_real_sample.py` — 5 integration
  tests pinned to `Parser/Data extract 2/Sample 1/`. All readers,
  detector, validator, persister, idempotency. Skip-if-missing so
  CI without the sample stays green.
- `python-multipart==0.0.27` added to `backend/requirements/base.txt`
  (required by FastAPI for multipart/form-data uploads).

**Architecture decision**

A single ingest endpoint is intentionally avoided: the parser
pipeline (`POST /api/v1/parser-import`) and dict pipeline
(`POST /api/v1/dict-import`) stay separate because they consume
different content and follow different schemas. The `format_detector`
exists to be **reused** if/when Rahul standardises both pipelines on
one wire format (his choice — see Meeting #8 follow-up email
sent 2026-04-29). Until then, two endpoints, one shared detector.

**Known follow-ups (deferred to v1.13+)**

- UI page for drag-and-drop dict upload — backend is ready, frontend
  not yet wired.
- Indices, partitioning, tabletext are parsed and counted but not
  yet persisted to dedicated tables (tabletext DDL is recoverable
  via `assemble_ddl()` if a consumer wants it). Adding tables for
  them is a Phase-2 schema migration.
- `extract_run_id` lookup by description LIKE works but is fragile
  to description-format changes; a dedicated column on `snapshot`
  is cleaner long-term (one-line Alembic migration when needed).

### v1.11.02 (2026-04-23) — Doc-only: TAISA branding sweep

User-facing prose no longer mentions the underlying LLM provider — TAISA
is the brand customers and stakeholders see. Replacements applied to
README.md, `docs/use_cases.md`, `docs/demo.txt`, `docs/demo_en.txt`, and
`docs/Estado de desarrollo.txt`. Backend module names, Python imports,
and env variable names are unchanged (renaming would touch working code
for no functional benefit; only the doc-level wording mattered).

### v1.11.01 (2026-04-23) — Internal engineering roadmap

Doc-only release. Adds `docs/internal_roadmap.md` — the project did not have
an engineering-side roadmap (only product / strategic / demo roadmaps). The
new doc consolidates everything currently on the table:

- **Phase 0 (DONE):** what's already shipped in v1.11.00.
- **Phase 1 (in flight):** real-JSON benchmark, Pipelines 2 & 3, Helton
  handover doc.
- **Phase 2 (planned):** scale & hardening — SQLite→Postgres decision gate,
  graph engine perf, Docker/systemd packaging.
- **Phase 3 (blocked on Phase 2 + infosec):** first customer pilot,
  authentication, release discipline, use-case validation sessions.
- **Phase 4 (future):** v1.0 GA — flip `APP_STAGE` from `"BETA"`.

Plus a **cross-cutting backlog**, a **decision log** so past calls don't
get re-litigated, and an **owner cheat-sheet** so anyone joining the team
(Helton in particular, after 2026-05-07) knows who owns what.

The benchmark gate ("real JSON measurement before SQLite/Postgres
decision and before sizing the customer VM") is now a formal step,
not just an informal agreement.

### v1.11.00 (2026-04-23) — Meeting #7 follow-ups: scale, search, docs

Rolled up the gaps raised in Meeting #7 (Rahul / Kindy / Luis) into one
minor bump. Three code changes plus three new architecture docs:

- **ObjectPicker component** (`frontend/src/components/shared/ObjectPicker.tsx`).
  A searchable + hierarchical picker: free-text substring match across all
  fully-qualified names *and* a drill-down tree grouped by database. Both
  modes are active simultaneously — the user can type to filter *or* expand
  a database to browse. Hard-capped at 50 results per query to keep
  thousands-of-objects customers responsive. Designed for the Lloyds-scale
  (500M relationships) case Kindy called out.

- **Lineage page uses ObjectPicker.** The old flat `<select>` dropdown on
  `/lineage` is gone; same object list, now searchable + tree-browsable.
  Addresses Rahul's direct request ("how do you filter or narrow down to
  specific objects when there are hundreds or thousands?").

- **Graph page focus mode.** `/graph` gained an optional anchor picker +
  an N-hops slider (1–5). When an anchor is set, an undirected BFS carves
  out the neighbourhood within N hops and renders only that subgraph. With
  no anchor, the page behaves exactly as before (full graph). Addresses
  Kindy's and John's repeated note that enterprise graphs are unreadable
  without drill-down.

- **`docs/ingestion_pipelines.md`** (new). Canonical architecture doc for
  the four extraction pipelines (parser / dict / usage / raw code). Locks
  in the committee decision that SCION never touches customer DBs — all
  inputs are flat files owned by Rahul's extractors.

- **`docs/use_cases.md`** (new). One-pager for the 6–8-person architect
  working sessions Kindy suggested (2 per region). Lists 8 use cases the
  current build supports, plus an honest "not yet" list. Starting point,
  not final wording — the whole point is the architects will rewrite it.

- **`docs/release_policy.md`** (new draft). Addresses Kindy's warning about
  needing versioning, rollback plans, and a single bug-fix distribution
  path before we install at any customer. Defines semver scheme, v1.0 GA
  criteria, fallback procedure, scope-lock process. Needs Chris sign-off.

### v1.10.06 (2026-04-22) — dev.ps1 PowerShell 5.1 compatibility

The v1.10.05 dev.ps1 rewrite used Unicode box-drawing characters and
em-dashes in comments, plus `&&` inside a string literal and
`"$var KB"` interpolation — all of which broke on Windows PowerShell 5.1
because the file is read with the system codepage (not UTF-8) so the
non-ASCII bytes garbled into invalid tokens.

Rewrote the script with strict ASCII-only content (`==`, `||`, `--`,
`*` for the banner / separators / bullets), replaced `&&` in the venv
error message with two separate lines, and fixed `"${dbSize} KB"`
interpolation syntax. Validated with `[System.Management.Automation.
Language.Parser]::ParseFile` -> `PARSE OK`.

No functional change — same UX (banner, pre-flight checks, status icons,
endpoint URLs, tips, clean shutdown). Just encoding-safe on PS 5.1.

### v1.10.05 (2026-04-22) — Recharts warnings + dev.ps1 facelift

**Recharts `width(-1) height(-1)` warnings fixed.** The volatility
sparkline in the `/intelligence` domain cards used
`<ResponsiveContainer width="100%" height="100%">` inside a 96×32 px
wrapper. On first render the DOM measurement occasionally raced the
layout engine, producing `-1` dimensions that Recharts shouted about on
stdout. Replaced with a bare `<LineChart width={96} height={32}>` —
fixed sizes are known at design time anyway, skip the measurement.

**`dev.ps1` CLI is now user-friendly.** New UX:

- ASCII-art SCION banner + version (auto-read from
  `frontend/src/lib/constants.ts APP_VERSION`).
- **Pre-flight checks** before launch:
  - Python venv exists
  - `frontend/node_modules` installed (runs `npm install` if missing)
  - `kalido_lite.db` present (warns if not — points to `rich_seed.py`)
  - Ports 8000 and 3000 free (exits early with a clear message if not)
- Bracketed status icons `[OK]` / `[...]` / `[!]` / `[X]` in the style
  of systemd/k8s.
- Clear sections: banner → pre-flight → launching → endpoints → tips →
  live logs.
- Helpful tips reminding about hot-reload scope and the reseed command.
- On shutdown: prints *which* child died if one exited unexpectedly,
  instead of a silent kill.

Everything else (process lifecycle, port cleanup, `--reload-dir app` to
prevent the tools-folder reload bug from v1.06.03) unchanged.

### v1.10.04 (2026-04-22) — Impact detail table spacing fix

The `Upstream/Downstream Impact Inventory` tables on `/impact/[changeId]`
had cells with `py-1.5` but no horizontal padding, so text ran together
visually (`COLUMNcore_banking.transactions.amountCOLUMN_TYPE_CHANGED`).
Added `pr-3` between columns, `whitespace-nowrap` on Type/Impact,
`break-all` on Name (for long dotted identifiers), `break-words` on
Description, and `align-top` on rows so wrapped cells line up with the
first line of their neighbours.

### v1.10.03 (2026-04-22) — Impact analysis for column-level changes

Same root cause as v1.10.02 (Lineage column redirect), applied in the
Impact engine. Clicking *"Impact detail"* on a column change from
`/changes` used to return `direct_count=0, indirect_count=0, total=0`
because `graph_diff_linker.py` failed to map changes with
`object_type=COLUMN` to any graph node — the graph only has
table/view/proc nodes, not column nodes.

**Backend fix** — `graph_diff_linker.py`:
Added a fallback: when the exact `(type, name)` lookup misses AND the
change is `object_type=COLUMN`, strip the last dot-segment from
`object_identifier` and look up the parent by name alone. The
propagation semantics are correct: a column-type-change ripples to
every view/proc/table that references that column, and all of those
show up as consumers of the parent table.

**Frontend fix** — `/impact/[changeId]/page.tsx`:
New green banner at the top that fires whenever `direct_impact[0]`
is a column. Explains explicitly that the counts below reflect impact
traced through the parent table, so the numbers are interpretable
and not mistaken for inflated column-specific metrics.

**Seed impact** — after re-running `rich_seed.py`, persisted impact
events jumped from **19 → 696** because column-level changes (COLUMN_TYPE,
NULLABILITY, POSITION, REMOVED — 17 of the 31 total) now contribute
propagation events via their parent tables. The demo for
`core_banking.transactions` is dramatically richer:
- Change #13 (amount widening): 6 direct + 8 indirect impacts across
  schemas, triggers, stored procs, views.
- Change #27 (raw_payload removed): full ripple through reporting.

**Re-seed required after update.** If you pulled this and see old
zeros in Impact Analysis, run `tools/rich_seed.py` once.

### v1.10.02 (2026-04-22) — Lineage column→parent auto-redirect

Fixed a UX dead-end reported during demo rehearsal.

When the user clicked "Lineage" on a column-level change in `/changes`
(e.g. `core_banking.transactions.amount`), the lineage page showed
*"object not present in this snapshot"* on every snapshot they tried.
The reason was subtle: columns are never lineage-level nodes in SCION —
only `DATABASE / TABLE / VIEW / STORED_PROCEDURE / …` get graph nodes,
because column-level lineage is modelled separately as `attribute_lineage`
(from the parser integration). So a 3-part identifier like `A.B.c` was
by construction absent from every graph.

Fix: on the lineage page, detect 3+ segment URL params, auto-resolve to
the parent table (`A.B`), and render a green info banner explaining
*"original change was on column <c> — columns aren't lineage-level
nodes, so we're showing lineage for its parent table <A.B>"*.

The existing amber "object not in this snapshot" banner still fires if
the *parent table* itself isn't in the selected snapshot (e.g. the
table was added later or dropped earlier).

### v1.10.01 (2026-04-22) — Object-name filter in Changes page

Added a free-text search box at the top of the "Detailed changes"
section filter bar on `/changes`. Case-insensitive substring match
against `object_identifier`.

Makes the single-object demo walkthrough much cleaner: typing
`transactions` narrows the 31-row table to the 5 rows that touch
`core_banking.transactions`, which is the pivot for the whole demo.

UX details:
- Placeholder shows a realistic example (`core_banking.transactions`).
- Clear `✕` button appears inside the input when non-empty.
- Live match count ("Match: 5 of 31") renders next to the box.
- Select-all checkbox and Generate DDL both honour the filter — a
  filtered selection will only generate DDL for the visible rows.

### v1.10.00 (2026-04-22) — Procedural objects on the graph + FK direction fix

Preparing for a full single-object demo walkthrough. Two issues were
blocking realistic lineage:

**1. Graph only showed tables/views/databases.** Everything else — stored
procedures, macros, functions, triggers — was absent because
`BASELINE_SCHEMAS` in `rich_seed.py` only ever declared `"TABLE"` and
`"VIEW"` object_types. The backend (terminology, colours, type
formatter, `TableKind` mapper) always supported every Teradata object
class; the seed just hadn't used them. Added 5 procedural objects
across 3 schemas, no columns (they don't need any):

- `core_banking.sp_daily_close` (STORED_PROCEDURE)
- `core_banking.fn_calc_interest` (FUNCTION)
- `core_banking.trg_audit_transaction` (TRIGGER)
- `risk_management.m_format_risk_alert` (MACRO)
- `reporting.sp_generate_regulatory_report` (STORED_PROCEDURE)

`/graph` now renders 7 object classes with the colour palette already
defined in `terminology.ts`.

**2. FK-heuristic FEEDS edges were inverted.** `graph_builder.py` was
emitting edges in the wrong direction: a column `customer_id` on
`accounts` produced `accounts FEEDS customers`. Semantically this said
"accounts is upstream of customers" — backwards for every dim→fact
warehouse relationship. Flipped the direction so the edge is now
`customers → accounts` (producer → consumer). This was a latent bug
that affected any lineage inference on real FK-style columns.

**3. Explicit `EXPLICIT_FEEDS_EDGES` list** added to `rich_seed.py` for
edges the FK heuristic can't see:

- `staging → core` feeds,
- `core → reporting` view composition (views reading from multiple
  tables without FK columns),
- `procedural objects ↔ touched tables` (no columns, no heuristic
  signal at all).

`_persist_explicit_edges()` runs after `build_graph_for_snapshot` for
each snapshot, resolves names against the snapshot's `graph_node`
table, skips endpoints that don't exist in that snapshot (so an edge
referencing `analytics_sandbox` naturally stops rendering after S10
when the sandbox is decomissioned).

**Seed output after fixes (snapshot #10):**
```
Object types: SCHEMA(4), TABLE(11), VIEW(4), STORED_PROCEDURE(2),
              FUNCTION(1), TRIGGER(1), MACRO(1)
Edges: 20 DEPENDS_ON, 28 FEEDS (was ~6 FK-only and inverted)
```

Lineage page now shows rich upstream/downstream chains for the demo
walkthrough object (`core_banking.transactions`):
- Upstream: `staging.stg_transaction_feed`, `core_banking.accounts`
- Downstream: `reporting.daily_pl_summary`, `core_banking.sp_daily_close`,
  `core_banking.trg_audit_transaction`

### v1.09.03 (2026-04-22) — Quick-link audit + Usage focus-banner polish

Audited all 4 "Explore this object" quick-links from `/changes`:
| Button | URL | Bug? |
|---|---|---|
| Lineage | `?object&snapshot` | fixed in v1.09.02 |
| Timeline | `?object` | OK — timeline is snapshot-agnostic |
| Impact detail | `/impact/{change_id}` | OK — path-param driven |
| Usage | `?object` | Minor polish (below) |

**Usage focus banner** now detects whether the focused object actually
appears in the usage or criticality tables. If no match (e.g. user
clicked Usage on a schema-level change, which has no query telemetry),
the copy switches from a promise ("highlighted below") to an explanation
("no usage telemetry found — common for schemas and parser-only
imports"). Prevents the "clicked Usage and nothing lit up" confusion.

### v1.09.02 (2026-04-22) — Lineage deep-link + UX clarifications

Two user-reported bugs on `/lineage`.

**Deep-link from Changes was being ignored.** Clicking "Lineage" on a
change row in `/changes` passes `?object=X&snapshot=Y` in the URL, but
the lineage page was checking the `activeDiffPair` SelectionContext
FIRST and falling back to URL only when no diff pair existed. So when
a user had (say) diff #1 → #10 selected and clicked Lineage on an
object from snapshot #2, the page loaded snap #10's graph — where that
object may not exist at all, producing a misleading "no objects selected"
state. Flipped the precedence: URL param > `selectedSnap` > diff pair.
The old inline comment had the rule inverted; rewrote it.

**Snapshot dropdown was hidden when a diff pair existed.** Users who
came from Changes had no way to switch snapshots without leaving the
page. Now the Snapshot dropdown is always visible.

**Added an "object not in this snapshot" amber hint.** Fires when the
selected object name can't be resolved to a node in the current
snapshot's graph — gives a plain-English explanation ("may have been
added in a later snapshot or removed in an earlier one") instead of
silently showing an empty state.

**Clarified the "19 objects" count** in the intro and in the title
tooltip of the objects counter: lineage operates at object level
(databases / tables / views / procs) — columns aren't listed because
they aren't lineage nodes. For column-level detail, Changes page.

### v1.09.01 (2026-04-22) — Guided-narrative rollout to the remaining pages

Completed the pass started in v1.09.00 by applying the `GuidedSection`
pattern to the five pages we hadn't touched.

**`/changes`** (was 780 lines — the biggest and most overloaded page)
- Diff-runner block at top gets a compact blue intro explaining the flow.
- Section 1 — **Summary** (KPIs) with a paragraph clarifying severity vs
  breaking as independent dimensions (moved the floating blue banner into
  this section's intro).
- Section 2 — **Detailed changes** wrapping view-mode toggle, filters,
  the expandable table, and the conditional DDL generator panel. Intro
  explains when to use Table vs Visual mode.
- Section 3 — **What next?** replaces the old "navigation hint" card,
  same drill-down-to-single-change selector, now in an explanatory shell.

**`/simulation`**
- Replaced the gradient purple banner with a Section 1 intro that states
  the key property up front: read-only, no DDL issued, no catalog touched.
- Section 2 wraps the whole result area (risk card + 4 KPIs + affected-
  objects table). Intro describes what each of the four numbers means.

**`/lineage`** (visualisation-heavy — lighter touch)
- Page-level intro paragraph answering the two questions users actually
  come here for: "what breaks downstream if I break X?" and "where did
  this bad value come from?"
- Section 1 around the graph + KPIs + legend; Section 2 around the 3
  detail panels (upstream list, object info, downstream list).

**`/graph`** (visualisation-dominant)
- Top intro describing nodes = objects, edges = dependencies, and what
  each control does. Legend at the bottom stays as-is for formal reference.

**`/snapshots`** (mostly a list page)
- Top intro explaining what a snapshot is, the two creation paths
  (Capture Live / Import from Parser), and why older snapshots are
  immutable.

No data-model or backend changes. Every page still renders the same
information — it just reads like a document now instead of a dashboard
of floating charts.

### v1.09.00 (2026-04-21) — Guided-narrative rollout + “Blast radius” renamed

Applied the Impact page redesign pattern (v1.08.01) across the three other
most confusing report-style pages. Every section now opens with a plain-
English intro box explaining what the reader is looking at, how to interpret
it, and when it matters.

**New shared component**
- `frontend/src/components/shared/GuidedSection.tsx` — extracts the numbered-
  title + icon + blue intro-box + children pattern that was local to the
  Impact page into a reusable component. Plus `HeroStat` (tight inline KPI)
  and `BigStat` (3-up stat card for feature sections).

**Pages refactored**
- **`/impact`** — migrated from inline helpers to the shared component
  (no visual change, just less code).
- **`/metrics`** — hero + 3 numbered sections (Historical trend,
  Composition & change detection, Snapshot comparison). Every chart now has
  a paragraph intro; the volatility indicator became the hero left-border
  accent matching the Impact page visual language.
- **`/intelligence`** — 3 numbered sections (Governance KPIs, Database
  risk breakdown, Historical co-change patterns). The old fragmented
  H2s + floating paragraphs became consistent GuidedSection intros.
- **`/usage`** — 3 numbered sections (Usage footprint, Criticality overview,
  Per-object drill-down). Added explanatory intros about what usage telemetry
  means and how criticality = 0.6 × Usage + 0.4 × Graph.

**Terminology: "Blast radius" → "Impact spread"**
- Military jargon out, plain English in. Changed on the Impact page
  (section title, hero text, empty state), on the Home dashboard (engine
  cards), and on the page subtitle. Backend API field names
  (`result.blast_radius`) unchanged — it's a UI-only rename.

No backend changes. Build clean, all existing state logic preserved.

### v1.08.01 (2026-04-21) — Impact Analysis page redesign

Users reported the Impact page felt confusing: redundant KPIs at the top
and no narrative between the 4 donuts. Rewrote the layout into a guided,
numbered story with plain-English intros on every section.

**Before**: 2 stacked blocks of KPIs (Blast Radius banner + KPI row) with
overlapping fields, a floating blue "criteria explainer" mid-page, and a
2×2 donut grid without section headers.

**After** — single hero + 5 numbered sections:
1. **Hero** with the overall-risk color as left-border accent, 4 de-duplicated
   top-line KPIs (Changes / Breaking / Impacted / Queries), the Report +
   CSV export buttons inline, and a 1-sentence narrative.
2. **Risk classification** — severity vs breaking, with a full intro
   paragraph explaining they are independent dimensions. The old floating
   "criteria" blurb is now this section's intro.
3. **Blast radius** — 3 prominent stat cards (Impacted objects / Max depth
   / Weighted score) + touched-databases chips, with a paragraph on how
   SCION walks the dependency graph.
4. **Distribution** — By database + By type donuts, with a paragraph on
   what each cross-cut reveals (team ownership vs change-type mix).
5. **Per-change drill-down** — the original table, now with a section
   intro describing Direct vs Indirect and the Score column.
6. **Affected objects, by database** — grouped grid with a paragraph
   clarifying the "database node only, no children impacted" case.

Reusable local components `Section`, `HeroStat`, `BlastStat` live at the
bottom of the file. Dropped `KpiCard` / unused lucide imports.

No backend changes. The page renders the same data, just readable.

### v1.08.00 (2026-04-21) — Data-dictionary ingestion foundation (pre-implementation)

After Rahul delivered his data-dictionary extract spec (6 SQL templates:
DatabasesV, TablesV, ColumnsV, IndicesV, PartitioningConstraintsV,
TableTextV — with full + incremental variants, and an `export` flat-file
output using `§`/`ENDREC`), we built the **consumer-side foundation**
without waiting for a real production extract. Everything here is
non-destructive scaffolding — no schemas, no migrations, no API changes
visible to the current UI.

**New backend modules (`backend/app/metadata/`)**
- `teradata_type_formatter.py` — pure function from Teradata internal
  `ColumnType` code (`"CV"`, `"I"`, `"DA"`, `"TS"`, etc.) + length/decimal
  fields → canonical SCION string (`"VARCHAR(255)"`, `"DECIMAL(18,2)"`,
  `"TIMESTAMP(6) WITH TIME ZONE"`, `"INTERVAL YEAR TO MONTH"`…). Full
  coverage of integer, decimal, float, char, binary, date/time, interval,
  period, JSON/XML/ST_GEOMETRY, and UDT families. Unknown codes fall
  back to `UNKNOWN(<code>)` to avoid ingest failure. Also exposes
  `object_type_from_tablekind()` (T/V/M/P/F/... → SCION enum).
- `dict_flat_file_reader.py` — parses the `§`-delimited / `ENDREC`-terminated
  export flat-files back into typed dataclasses. Handles escaped delimiters
  (`\§`), multi-line `RequestText` chunks, empty / zero-row files. One
  reader per view, sharing the column-order contract (validated at parse
  time — arity mismatch → `DictFlatFileError` with context).
- `dict_ingestor.py` — orchestrator stub. Reads all 6 files into a
  `DictionaryBundle`, validates referential integrity (columns must
  reference known tables, tables must reference known databases, etc.),
  and returns an `IngestionPreview` with counts + translation samples +
  categorised warnings. **Does not persist** — that's the v1.09 step once
  a real production extract is in hand.

**New dev tool**
- `backend/tools/generate_dict_fixtures.py` — emits 6 realistic flat-files
  from the most recent seeded snapshot, using the exact format Rahul's
  `run_metadata_extracts.py` produces. Reverse-translates SCION canonical
  types back to Teradata internal codes so the round-trip
  (seed → flat-file → reader → formatter) is stable. Output lands in
  `backend/tests/fixtures/dict_extracts/`. Useful for demos and for CI.

**Criticality engine — usage-out-of-scope fallback**
- `compute_criticality(..., usage_available: bool = True)`. When `False`,
  skips the usage aggregation step and uses `combined_score = graph_score`
  directly. Same HIGH/MEDIUM/LOW thresholds, no UI changes needed.
  Runtime flag only — protects us from the open Chris-level decision on
  whether usage ships in Phase 1 or Phase 2.

**Design documentation**
- `docs/dictionary_integration.md` — full merge-strategy doc:
  dictionary-first, parser-lineage-attached, conflict resolution table,
  API sketch for v1.09, open questions tracked. Recorded rationale for
  "dictionary-first" over "lineage-first".

**Validation on the seed**
Round-trip test: 4 databases, 15 tables, 122 columns, 11 indices,
4 view DDLs — all read and type-translated cleanly back from the
fixtures. Zero warnings on referential integrity.

**Not yet wired**
- `dict_persister.py` (writes to DB): blocked on seeing a real Rahul
  extract, then a few hours of work.
- `/api/v1/dict-import/*` endpoints: same blocker.
- Frontend `/snapshots` flow to accept dict + parser together: same blocker.

### v1.07.00 (2026-04-21) — Data-science pack (Statistical Process Control + Association Mining + Rolling Trend)

Three analytical layers over the existing `change_event` history, surfacing
signals the point-in-time metrics couldn't. All three are classical,
explainable techniques — no ML, no training, no black boxes.

**Backend (`backend/app/metrics/`)**
- `anomaly_detection.py` — per-`(schema, snapshot)` z-score over leave-one-out
  mean/stdev of change volumes. Flags snapshots where a schema deviated
  from its own historical cadence (`HIGH` at ≥3σ, `MEDIUM` at ≥2σ).
  Classical Shewhart SPC, not ML.
- `cochange.py` — Apriori-style pairwise association mining over snapshot
  deltas. Computes support / confidence / lift for each object pair,
  surfacing historical couplings invisible to the lineage graph.
- `volatility_trend.py` — rolling volatility per schema across all
  snapshots with a current-vs-prior delta + trend label
  (`worsening` / `stable` / `improving`).

**API**
- `GET /api/v1/alerts/anomalies` (z-score ≥ threshold)
- `GET /api/v1/intelligence/cochange` (top-N rules by lift)
- `GET /api/v1/intelligence/volatility-trend` (series per schema)

**Frontend**
- `/alerts` — new purple "Statistical Anomalies" card above the rule-based
  alerts. Each entry shows schema, snapshot, observed vs expected, σ,
  and baseline size.
- `/intelligence` domain cards — each now renders a 24×8 px sparkline of
  its rolling volatility series + a delta badge (e.g. `34% ↗ +42% vs prior`)
  coloured by trend.
- `/intelligence` — new "Historical Co-change Patterns" table at the bottom,
  sorted by lift, with confidence + co-occurrence columns. Lift ≥ 3
  highlighted as strong coupling.

**Validation on the demo seed (10 snapshots)**
- Anomalies: snapshot #10 flagged as z=8.2σ for `core_banking` (GDPR drop)
  and z=6.4σ for `risk_management`, matching the seed storyline.
- Cochange: strongest rule is `exposure_summary → stg_customer_feed`
  (lift=7.0) and `analytics_sandbox` internal triplet (lift=3.5, confidence=1.0).
- Volatility trend: `core_banking` and `risk_management` marked as
  `worsening` (+100% delta), `reporting` / `staging` stable.

### v1.06.03 (2026-04-20) — `dev.ps1` silent-shutdown fix

- Backend + frontend were dying silently whenever a file outside `backend/app/`
  was edited (e.g. `tools/rich_seed.py`, `alembic/versions/*`, tests).
- Root cause: `uvicorn --reload` default-watches the whole `backend/`
  directory. On Windows, WatchFiles' reload propagates a signal that
  PowerShell interprets as Ctrl+C on the parent `dev.ps1`, which runs the
  `finally` block and `taskkill`s both child processes — the engines then
  shut down without any error, just the Spanish prompt
  `¿Desea terminar el trabajo por lotes (S/N)?`.
- Fix: pass `--reload-dir app` so only the served FastAPI app triggers
  reloads. Editing seed scripts / migrations / tests no longer kills the demo.

### v1.06.02 (2026-04-20) — Teradata terminology fix (round 2)

- **Impact donut chart** was bypassing `changeTypeLabel()` and building its
  own labels via raw `replace(/_/g, " ")` → showed `SCHEMA ADDED`,
  `SCHEMA REMOVED`. Now uses the terminology helper.
- **SchemaVisualDiff** (table + column change badges) same fix.
- **Lineage sidebar** "Changed in this diff" detail.
- **Changes → Select a change** dropdown.
- **Snapshots page** copy: "Schema-change detection" → "Structural change
  detection"; "All schemas, tables, and columns" → "All databases, tables,
  and columns" in the delete confirmation modal.

### v1.06.01 (2026-04-20) — Teradata terminology fix

- `terminology.ts` (`changeTypeLabel()`) was defined in v1.03 but never
  actually imported. Raw change_type strings (`SCHEMA_ADDED`, etc.) were
  leaking into Timeline, Changes, Impact and the Home dashboard.
- Wired `changeTypeLabel()` into all five display sites so users see
  **"Database added / removed"** instead of `SCHEMA_ADDED / SCHEMA_REMOVED`,
  matching Teradata convention.
- Raw token preserved as a `title` tooltip for power-users / debugging.

### v1.06.00 (2026-04-20) — Rich demo seed ("sabroso" edition)

**`backend/tools/rich_seed.py` — full rewrite**
- **10 snapshots** spread across a 30-day window (was 3)
- **Full Teradata data type catalog** exercised in the baseline: numeric
  (`BYTEINT`/`SMALLINT`/`INTEGER`/`BIGINT`/`DECIMAL`/`NUMBER`/`FLOAT`/`DOUBLE PRECISION`),
  character (`CHAR`/`VARCHAR`/`CLOB`/`LONG VARCHAR`), binary (`BYTE`/`VARBYTE`/`BLOB`),
  date/time (`DATE`/`TIME`/`TIME WITH TIME ZONE`/`TIMESTAMP`/`TIMESTAMP WITH TIME ZONE`),
  intervals (13 variants from `YEAR` to `SECOND`), periods (`PERIOD(DATE)`,
  `PERIOD(TIMESTAMP(6))`), complex (`JSON`, `XML`, `ST_GEOMETRY`, `ARRAY`, `BOOLEAN`)
- **All 10 change types** produced at least once across the timeline:
  `SCHEMA_ADDED`, `SCHEMA_REMOVED`, `TABLE_ADDED`, `TABLE_REMOVED`,
  `TABLE_TYPE_CHANGED`, `COLUMN_ADDED`, `COLUMN_REMOVED`, `COLUMN_TYPE_CHANGED`,
  `COLUMN_NULLABILITY_CHANGED`, `COLUMN_POSITION_CHANGED`
- Each snapshot tells a short business story (sandbox spin-up, GDPR cleanup,
  capital-adequacy widening, staging retirement, …) so diff/impact pages
  feel narrative, not synthetic
- Mutation engine is pure and deterministic (`apply_mutation()` returns a
  new dict; originals never touched)
- Self-wiping: script DELETEs demo + parser tables FK-safely, no need to
  stop the backend or rerun `bootstrap_sqlite_db.py`
- Pairwise diffs computed between every consecutive pair, not only the
  latest, so the Changes/Impact pages have data across the whole timeline
- Output: **31 changes, 6 impacts, 15 usage rows, criticality computed
  on snapshot #10**

### v1.05.00 (2026-04-20) — Parser UI Integration (Day 2)

**Frontend — Snapshots page**
- `Import from Parser` button now calls the real `/parser-import/lineage` endpoint (previously only validated JSON locally)
- Two-phase flow: file select triggers a **dry-run preview**, user reviews counts + warnings, then clicks **Confirm Import** to persist
- Preview panel renders three count cards (input → filtered → would-persist) driven dynamically by the backend `IngestionReport` dicts
- Amber **"Structural snapshot incomplete — waiting for parser v2"** callout whenever the backend report contains `UNKNOWN`-related warnings
- Success toast with the new `snapshot_id` and auto-selects the imported snapshot

**Frontend — System Graph page**
- New `UNKNOWN` object_type style (amber, dashed border) with hover tooltip *"Waiting for parser datasetType field"*
- Header stats now include `N unclassified` badge so parser-v1 imports don't look deceptively empty (previous "0 tables" was technically true but hid real data)
- Legend auto-includes the Unclassified entry only when such nodes are present

**New frontend modules**
- `src/lib/api/parser_import.ts` — `previewParserImport()` / `confirmParserImport()` wrappers
- `ParserImportResponse` type in `src/lib/api/types.ts` mirrors the backend pydantic model

**Validation**
- Bootstrap → parser import (real `lineage-mvp.json`) → snapshot #1 visible in UI with 1 database, 1 unclassified table, 2 unclassified columns, 1 process, 2 steps, 1 attribute_lineage (expression + `transformation_type=Filter` preserved)

### v1.04.00 (2026-04-20) — Parser Integration Scaffolding (Day 1)

**Database**
- 3 new tables: `process`, `step`, `attribute_lineage`
- Alembic migration `f1a8b3c5d207`

**Backend — new `parser_ingest` module**
- `parser_models.py` — internal dataclasses (`ParsedLineagePayload`, `IngestionReport`, ...)
- `teradata_parser.py` — tolerant JSON → dataclasses (future-proofs parser v2 fields)
- `noise_filter.py` — heuristic filter for `NOT APPLICABLE`, `UNKNOWN`, SQL literals, temp tables
- `ingestor.py` — persists full payload in one transaction, produces `IngestionReport`
- `dry_run.py` — analyzes without persisting

**API**
- New endpoint `POST /api/v1/parser-import/lineage?dry_run=true|false`

**Validation**
- End-to-end tested with `parser/lineage-mvp.json` (real sample from DataDNA team)
- 15 noisy entities correctly filtered; 1 real database + 1 table + 2 columns + 1 process + 2 steps + 1 attribute_lineage edge persisted with the actual SQL expression and `transformationType="Filter"`

### v1.03.00 (2026-04-16) — Clarity, Context & What-If
- Release A: terminology unification, Graph legend fix, Breaking vs Severity separation, schema → database rename, 10+ object types supported, Reasoning page removed (replaced by TAISA widget)
- Release B: quick links Lineage/Timeline/Impact/Usage from Changes, queries/users affected in Impact, InfoTooltip component, bigger Heatmap labels
- Release C: What-If Simulation page + endpoint, proactive Alerts (broken lineage, orphans, hub changes), TAISA Algorithm Knowledge Base
- Release D: hash hidden in Metrics, protected snapshot delete with typed confirmation, 23 docstrings added
- Release E: README + version bump
- **Plus**: ~260 inline code comments added across 74 files for onboarding

### v1.02.00 (2026-04-16) — UX polish
- Dark Mode, animated counters, TAISA floating widget, Mission Control dashboard, Visual Diff, Risk Heatmap, skeleton loaders, toasts, page transitions, confetti, keyboard shortcuts

### v1.01.00 (2026-04-16) — Wow features
- DDL Generator, Comparison Report, Timeline, Global Search, Alerts Panel, CSV Export, TAISA conversational layer

### v1.00.00 (2026-04-15) — Initial release
- 7 engines, 13 pages, full diff/impact/reasoning pipeline

---

## License

Proprietary — Teradata Corporation. All rights reserved.
