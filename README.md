# Project SCION

**Structural Change Intelligence Platform**

SCION is a proprietary platform that replaces Kalido within Teradata DNA. It monitors structural changes across the data warehouse, assesses impact, and provides AI-powered risk recommendations — with full TAISA conversational Q&A, "what-if" simulation, and DataDNA parser integration.

**Version:** BETA v1.16.00

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
  tools/                 # db_init.py (canonical schema/seed lifecycle), rich_seed.py, fixtures

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

# Database — single canonical entry point (alembic-only schema, optional demo seed).
# Replaces the older split between `bootstrap_sqlite_db.py` and bare `alembic upgrade`.
# IMPORTANT: always invoke with the project venv's Python, not system `python` —
# the script needs alembic/sqlalchemy from the venv.
.venv\Scripts\python.exe backend\tools\db_init.py reset --with-seed   # fresh DB + demo data
# Subsequent setups / new dev: `db_init.py init` (without flags) is idempotent.
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
| `API_KEY` | _(unset = auth disabled)_ | When set, all `/api/v1/*` endpoints require `X-API-Key` header. See "Security" below |
| `DATABASE_URL` | SQLite demo | |
| `NEXT_PUBLIC_API_KEY` | _(unset)_ | Frontend-side counterpart — included automatically on every API request when set |

TAISA LLM settings in `backend/app/config/taisa_llm.yaml`.

---

## Security

API key authentication is built in. **Off by default** for local
development convenience; **must be enabled before any pilot deploy**
(per `docs/release_policy.md` §3.2).

**To enable:**

1. Generate a strong key: `openssl rand -hex 32` (or any other
   ≥32-char random string).
2. Set on backend: add `API_KEY=<value>` to `backend/.env`.
3. Set on frontend: add `NEXT_PUBLIC_API_KEY=<same value>` to
   `frontend/.env.local`.
4. Restart both services.

**Behaviour with `API_KEY` set:**

- Every endpoint under `/api/v1/*` requires the `X-API-Key: <value>`
  header. Missing → `401`. Wrong → `403`.
- `/api/v1/health`, `/api/v1/healthz`, and `/api/v1/health/ready`
  are intentionally exempt so liveness/readiness probes don't
  need the secret.
- The frontend client (`frontend/src/lib/api/client.ts`) reads
  `NEXT_PUBLIC_API_KEY` at build time and injects it on every
  request via an Axios interceptor.

**Behaviour with `API_KEY` unset (default):**

- Every endpoint is open. Convenient for `dev.ps1`, never
  acceptable for any deploy where the network is shared.

**Out of scope today:** SSO via Teradata IDP, RBAC, per-user
auditing. Those are tracked in the Phase-3 roadmap.

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

The full changelog lives in [`CHANGELOG.md`](./CHANGELOG.md).
Bump the version with `.	oolsump_version.ps1 X.Y.Z "summary"` and
edit the generated stub in `CHANGELOG.md` (no longer in README).

---

## License

Proprietary — Teradata Corporation. All rights reserved.
