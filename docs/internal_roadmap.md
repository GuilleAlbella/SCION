# SCION — Internal Engineering Roadmap

**Audience:** SCION dev team (Guillermo + Claude Code, anyone joining).
**Not:** product strategy (`docs/Hoja de Ruta del Producto.txt`), demo script
(`docs/demo_en.txt`), or marketing (`docs/use_cases.md`).
**Purpose:** the *engineering* view — what's done, what's next, what's blocked,
who owns each piece, and the gates that have to clear before we ship to a
real customer.

Last updated: 2026-09-02 · Current version: **v2.09.14 (BETA)** (`main`).

---

## Phases at a glance

```
  ┌────────────┐   ┌────────────┐   ┌────────────┐   ┌────────────┐   ┌────────────┐
  │  Phase 0   │──▶│  Phase 1   │──▶│  Phase 2   │──▶│  Phase 3   │──▶│  Phase 4   │
  │ Foundations│   │ Pipelines  │   │ Scale &    │   │ Pilot      │   │ v1.0 GA    │
  │ (DONE)     │   │ 2 & 3      │   │ Hardening  │   │ Customer 1 │   │            │
  └────────────┘   └────────────┘   └────────────┘   └────────────┘   └────────────┘
       ✅                   ✅           🟡 in flight     🔴 blocked       🔴 future
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

## Phase 1 — Pipelines 2 & 3, real data benchmark  ✅ DONE (v1.21.43)

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

## Phase 2 — Scale & Hardening + ED Integration  🟡 IN PROGRESS

**Trigger:** Phase 1 benchmark results. Phase 2 scope confirmed in Meeting 21 (2026-06-19) and expanded in Meeting 28 (2026-07-15).
**Owner:** Guillermo. Deadline estimate: **Monday 2026-07-21**. Presentation to Chris/Pilar: **Thursday 2026-07-24**.

> ⚠️ **Work scope — LAB ONLY until further notice.**
> All Phase 2 development, testing and validation is done against the lab environment
> (`docker-compose.lab.yml`, Postgres on `localhost:8080`). The production deployment
> (`ps-ubuntu-0043`, `docker-compose.yml`) is NOT touched until Phase 2 is validated
> in lab. Functional checks, benchmarks and tests run in lab.
>
> **Active database in lab:** Postgres 16 — volume `scion-lab_pgdata`.
> The full stack (importer, graph engine, impact, TAISA, usage) points to Postgres
> via `DATABASE_URL=postgresql+psycopg://scion:scion_lab@postgres:5432/scion`.
> The SQLite files in the container (`kalido_lite.db`, `scion_source.db`) are inert.

> **DataDNA Lite v1.0 declared complete by Rahul (Meeting 21, 2026-06-19).** SCION replaces both Kalido (metadata integration) and Click (visualization). Phase 2 expands the scope to full integration model + reference data + AI classification.

---

### Phase 2 Estimation Summary

Assumption: **1 developer (Guillermo) + Claude Code (AI-assisted)**, 5-day weeks.
With AI-assisted development, effective velocity is ~1.8–2x. Days are **real calendar days**.

Restructured after the Pilar meeting (2026-07-17): single delivery instead of two, SQLite→Postgres as the first mandatory item (foundation for the Integration Model), followed by Jon Brightling's 3 layers.

#### Single delivery — Phase 2 complete

| # | Item | Brief description | Est. (days) | Notes |
|---|------|--------------------|------------|-------|
| **2.5** | **SQLite → Postgres** | DB engine migration — performance foundation | **4** | First item; no longer conditional |
| ↳ 2.6 | Graph engine perf | Lazy-load nodes + indexing | **2** | Sub-task of 2.5 |
| ↳ 2.7 | Frontend pagination | Server-side + lazy graph fetch | **2** | Sub-task of 2.5 |
| **2.16** | **Staging Layer** | Validation + cross-source resolution before Integration | **5** | NEW — Jon Brightling architecture |
| **2.9** | **Integration Model** | Entity layer + backfill + trend UI | **7** | Requires §2.16 |
| **2.15** | **Access Layer** | Business Discovery + Executive Dashboard + Entity view | **4** | Requires §2.9 + §2.10 |
| **2.8** | Production runtime | Systemd units + JSON logging | **1** | — |
| **2.11** | ~~Col-lineage navigation~~ | ~~Downstream + upstream interactive~~ | **✅** | v2.05.00 |
| **2.12** | ~~AI column classification~~ | ~~PII / non-PII by name, type and comment~~ | **✅** | v2.06.00 |
| **2.10** | ~~Reference data~~ | ~~User hierarchy + app metadata + dashboards~~ | **✅** | v2.07.00 |
| **2.2** | ~~Incremental loading~~ | ~~CDC against baseline day zero~~ | **✅** | v2.08.00 |
| **2.13** | ~~Manifest timestamps~~ | ~~Extractor timestamps on snapshot screen~~ | **✅** | v2.09.00 |
| **2.4** | DDL timestamp merge | Keep most recent version on ingest | **1** | — |
| **2.14** | Buffer (contingency) | Reserved for unforeseen items | **5** | — |
| | **GROSS TOTAL** | | **49** | |
| | *AI-assisted gain (~20%)* | | *−10* | |
| | **NET TOTAL** | | **~39 days** | ~8 weeks |

> ⚠️ §2.10 blocked until Rahul's extractor provides username per row (today only `user_count`).
> §2.16 Staging Layer is prerequisite for §2.9. §2.15 Access Layer requires §2.9 + §2.10 complete.

---

Subject to what the real-data numbers tell us. Items:

### 2.0 Column-level lineage enhancements (Meeting 21 feature requests)

Three concrete requests from Rahul after the live demo of column-level lineage:

- [x] **Indirect lineage display** — collapsible "⊿ Indirect impacts" section per column card; amber rows with icon + expression. 10/10 tests. *(v1.21.27)*
- [x] **Transformation-type icons on column nodes** — `TransformBadge` component maps 8 types to Unicode glyphs (→ Σ ⊿ ≠ ƒ ⊞ ⊟) with full-name tooltip; replaces text badges in Sources, Feeds-into, and Indirect sections. *(v1.21.28)*
- [x] **Step / Query ID on edge click** — `step_natural_key` exposed in `ColumnEdge`; clicking a dashed column edge reveals originating SQL step IDs in a dismissable purple panel. *(v1.21.28)*
- [x] **Edge label click bug** — SVG hit-zone overlap caused wrong popup to fire; migrated labels to `EdgeLabelRenderer` (HTML layer) for precise click targets. *(v1.21.39)*
- [x] **Debug panel removed** — yellow debug overlay removed from col-lineage view. *(v1.21.40)*
- [x] **Producers/consumers panel** — long table names now split schema/table, scrollable lists, count badges inline. *(v1.21.41)*
- [x] **Indirect impacts cleanup** — removed "no expression" literal (tier 2 parser never populates expression); deduplicate identical rows into `· N queries` count badge. *(v1.21.42)*
- [x] **Edge label dedup fix** — dedup key changed from `source_column_key` to `(source_column_key, target_column_key)` pair; same source column mapping to multiple targets now all visible. *(v1.21.43)*

### 2.1 Ecosystem Decoded (ED) integration  *(new — Meeting 21)*

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

**Use cases proposed for Phase 2 (from Meeting 21 + ED use-case spreadsheet):**

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

### 2.2 Incremental snapshot handling *(confirmed Meeting 18)* ✅ COMPLETE (v2.08.00, 2026-07-21)

- [x] SCION must compare incremental batches against a "day zero" baseline (not the previous incremental).
- [x] Track cumulative object count across batches.
- [x] On full reset (gap in data), create a new day zero and reset baseline.

### 2.3 Dict view-definition parsing *(confirmed Meeting 18 — parser team)*

- [ ] Code Parser to parse view DDLs from the data dictionary (not just DBQL).
- [ ] Covers views created before the extraction window (lineage gaps in DBQL-only mode).
- [ ] Output: same JSON lineage format; SCION ingests alongside existing dict batch.
- [ ] Execution model: run once on "day zero", then incremental via DBQL.

### 2.4 DDL timestamp merge *(confirmed Meeting 19)*

- [ ] Same object can arrive from DBQL extract AND dict extract with different timestamps.
- [ ] SCION must keep the *latest* version (compare DDL timestamps on ingest).
- [ ] Applies to: views, stored procedures, macros, triggers.

### 2.5 SQLite → Postgres  *(first item — post-Pilar meeting, 2026-07-17)*  **Est: 4 days**

Previously marked as conditional. Post-Pilar meeting decision: done first as the performance
foundation before building the Integration Model on top of it. Graph engine perf and
Frontend pagination are sub-tasks completed in parallel with the migration.

**Sub-tasks:**

#### 2.5a — Engine migration (2.5 core — 4 days)  ✅ LAB COMPLETE (2026-07-20)
- SQLAlchemy abstracts the engine — the bulk of the work is operational, not code.
- [x] Connection-string + driver switch — `psycopg[binary]==3.2.13` (v3); dialect `postgresql+psycopg://`.
- [x] All Alembic migrations run against Postgres — `alembic/env.py` updated to read `DATABASE_URL` and register all ORM models via `app.db.base`.
- [x] FK/cascade behaviour verified — SQLite does not enforce FKs; Postgres does. Mitigated with `ALTER TABLE … DISABLE TRIGGER ALL` in the migration script.
- [x] `docker-compose.lab.yml` created with Postgres 16-alpine service (internal port 5432, SCION on 8080).
- [x] `DATABASE_URL` env var in docker-compose.lab.yml; production uses `sqlite:////data/scion.db` until migration.
- [x] 47,819 rows migrated to Postgres in lab. API verified: `GET /api/v1/snapshots` returns 10 snapshots correctly.

##### Key files
| File | Description |
|---|---|
| `docker-compose.lab.yml` | Lab environment with Postgres 16-alpine + SCION on port 8080 |
| `alembic/env.py` | Reads `DATABASE_URL` env var; imports `app.db.base` (all models) |
| `backend/tools/migrate_sqlite_to_postgres.py` | One-shot migration script SQLite → Postgres |

##### Migration procedure — lab (template for production)

> Run **inside the backend container** (`docker exec scion-lab-backend …`).

```bash
# Step 1 — Copy SQLite to the container
#   (lab: kalido_lite.db  |  prod: volume is already mounted at /data/scion.db)
docker cp kalido_lite.db scion-lab-backend:/tmp/scion_source.db

# Step 2 — Fix permissions (docker cp leaves the file owned by root)
docker exec --user root scion-lab-backend chown scion:scion /tmp/scion_source.db

# Step 3 — Update SQLite source to alembic HEAD
#   (needed if the backup was taken before the latest migration)
docker exec scion-lab-backend python backend/tools/db_init.py init \
    --db-url sqlite:////tmp/scion_source.db

# Step 4 — Dry-run: verify row counts per table
docker exec scion-lab-backend python backend/tools/migrate_sqlite_to_postgres.py --dry-run

# Step 5 — Full migration
docker exec scion-lab-backend python backend/tools/migrate_sqlite_to_postgres.py
```

> **In production**, replace `scion-lab-backend` with `scion-backend` and `--source` with
> `sqlite:////data/scion.db` (the volume is already mounted there).
> The container's `DATABASE_URL` will point to the production Postgres via the
> `docker-compose.yml` configuration (no explicit `--target` needed).

##### Documented gotchas

| Problem | Cause | Fix |
|---|---|---|
| `attempt to write a readonly database` | `docker cp` copies with root owner | `docker exec --user root … chown scion:scion …` |
| `alembic_version mismatch` | Backup taken 2 migrations before HEAD | Run `db_init.py init --db-url sqlite:///…` on the source |
| `ForeignKeyViolation` on insert | SQLite does not enforce FKs — orphan rows in source | `ALTER TABLE … DISABLE TRIGGER ALL` per batch (already in the script) |
| `InFailedSqlTransaction` on sequence reset | Sequence does not exist for FK or UUID PK columns | Each reset uses its own `engine.begin()` transaction — failed ones are ignored |
| Multi-line commands in PowerShell with `docker exec` | PowerShell interprets `"..."` differently | Use heredoc `$script = @'...'@; $script \| docker exec -i container python` |

#### 2.5b — Graph engine performance (§2.6 — 2 days)  ✅ COMPLETE (2026-07-20)
- [x] **Lazy-load graph nodes on demand** — `compute_node_metrics` replaced: instead of loading all nodes+edges into Python RAM (~700 MB on Transcend), uses two SQL `GROUP BY` queries. Only degree counts are transferred, not edge rows. *(v2.01.00)*
- [x] **Computed metrics persisted in DB** — `node_metadata` JSON in `graph_node` already stored `{in_degree, out_degree, fragility, is_hub}`; `persist_node_metrics` continues writing post-ingest. Dead code in `blast_radius.py` removed (loaded all `GraphNode` rows per snapshot to build `node_names`/`node_schemas` that were never used). *(v2.01.00)*
- [x] **Index on `change_event(snapshot_to, object_identifier)`** — migration `a1b2c3d4e5f6` adds `ix_change_event_snapshot_to_object`. Also merges the two existing Alembic heads (`f1a2b3c4d5e6` + `d61e9f7a2b34`). *(v2.01.00)*

#### 2.5c — Frontend pagination (§2.7 — 2 days)  ✅ COMPLETE (v2.02.00, 2026-07-20)
- [x] Server-side pagination on /changes — infinite scroll with IntersectionObserver; replaces Previous/Next. `fetchPage` already had `"append"` mode; now wired to sentinel div + observer (rootMargin 400 px). Status row shows `N / total loaded`. *(v2.02.00)*
- [x] Lazy graph fetch — `/graph/{snapshot_id}` truncates to 5,000 nodes and returns `truncated: true`; frontend shows banner to select focus mode anchor. `/graph/focus` does server-side BFS (cap 1,000 nodes). Already live since v1.11.00. *(v2.02.00)*

### 2.6 Graph engine performance  ✅ COMPLETE (v2.01.00, 2026-07-20)
- [x] Lazy-load graph nodes on demand — SQL GROUP BY in `compute_node_metrics`.
- [x] Computed metrics persisted in DB — `node_metadata` JSON in `graph_node`.
- [x] Index on `change_event(snapshot_to, object_identifier)` — migration `a1b2c3d4e5f6`.
- [ ] Cython / Rust for `compute_impact` — discarded for now; SQL CTEs are sufficient at scale.

### 2.7 Frontend rendering  ✅ COMPLETE (v2.02.00, 2026-07-20)
- [x] Focus mode for /graph (v1.11.00).
- [x] Server-side infinite scroll on /changes — IntersectionObserver replaces Previous/Next; append mode wired to sentinel div. *(v2.02.00)*
- [x] Lazy graph fetch — truncation at 5 000 nodes + focus-mode BFS already in place since v1.11.00. *(v2.02.00)*

### 2.8 Production runtime  ✅ COMPLETE (v2.04.00, 2026-07-20)
- [x] `docker-compose.yml` — backend + frontend (production build) + nginx reverse proxy. Live on ps-ubuntu-0043 since v1.21.x. GHCR image publish wired.
- [x] Health check endpoints (`/healthz`, `/readyz`). *(v1.21.x)*
- [x] Linux systemd units — `deploy/systemd/scion.service` + `deploy/install_systemd.sh`. `docker/install.sh` step 7 installs and enables the unit automatically on Linux. Type=oneshot+RemainAfterExit; restart on-failure; EnvironmentFile from `.env`. *(v2.04.00)*
- [x] Structured JSON logging — `backend/app/logging_config.py` (dictConfig JSON/text, controlled by `LOG_FORMAT` env var). `python-json-logger==2.0.7`. nginx `log_format json_access escape=json` + security headers. `main.py` migrated to `lifespan`, `print()→logger.info()`, CORS from `ALLOWED_ORIGINS` env var. *(v2.04.00)*

### 2.16 Staging Layer  *(new — Jon Brightling architecture, 2026-07-17)*  **Est: 5 days**  ✅ COMPLETE (v2.03.00, 2026-07-20)

**Origin:** Jon Brightling email 2026-07-17. The formal 3-layer architecture is:
**Staging → Integration → Access**. The Staging Layer is the direct prerequisite for the
Integration Model (§2.9) — data must pass through validation and normalization before entering
the persistent entity layer.

**What it does:** Receives the raw client extracts (`.dat`, `.json`), validates them, resolves
cross-source conflicts, and "promotes" them to the Integration Model once clean. Today SCION
persists directly from import — the Staging Layer adds a controlled intermediate step.

**Components:**

#### 2.16.a — Staging tables + status tracking
- [x] New tables: `staging_table_import`, `staging_column_import` — migration `b2c3d4e5f6a7`. *(v2.03.00)*
- [x] Field `import_status` in `snapshot`: `pending → staged → committed → failed` — migration `b2c3d4e5f6a7` + `snapshot.validation_warnings` JSON field. *(v2.03.00)*
- [x] Alembic migration `b2c3d4e5f6a7` — revises `a1b2c3d4e5f6`. *(v2.03.00)*

#### 2.16.b — Validation pipeline
- [x] Validate completeness: `schema_name` non-null, recognized data types — `staging_validator.py` rules: NULL_SCHEMA + UNKNOWN_TYPE. *(v2.03.00)*
- [x] Detect and log cross-source duplicates — DUPLICATE_TABLE hard error; sets `import_status='failed'`. *(v2.03.00)*
- [x] Resolution rule: keep most recent version by `DDL_timestamp` (absorbs §2.4) — UNKNOWN_TYPE/NULL_SCHEMA as warnings, DUPLICATE_TABLE as hard error. §2.4 absorbed. *(v2.03.00)*
- [x] Result: import report with accepted / rejected / resolved rows — stored in `snapshot.validation_warnings` JSON + `staging_table_import.row_status`. *(v2.03.00)*

#### 2.16.c — UI: import status on Snapshots page
- [x] Show `staged / committed / failed` status per snapshot — badge column in snapshots table (green/blue/red). *(v2.03.00)*
- [x] Resolved conflict details — expandable table in each snapshot's detail panel; backend now includes `validation_warnings` in `GET /snapshots`; shows severity, type, message, object_name. *(v2.09.13)*

**Note:** §2.4 DDL timestamp merge is absorbed by §2.16.b — no longer a separate item.

---

### 2.9 Integration Model — Cross-Snapshot Entity Layer  *(Meeting 27 + Meeting 28)*  ✅ BACKEND COMPLETE (v2.03.00, 2026-07-20)

**Origin:** Jon Brightling (Data DNA team) identified in Meeting 27 (2026-07-15). Confirmed
in Meeting 28 by Rahul Kulkarni: this is the equivalent of the **Kalido BIM model** —
applies data warehousing principles to metadata: persistent, ongoing history of every entity
across snapshots. This layer is also the prerequisite for §2.10 (reference data must link
INTO this model). The full integration model includes: storage (data dictionary), processing
(lineage), usage, AND business metadata (§2.10).

**Problem today:** Every ingest regenerates fresh surrogate keys (`schema_id`, `table_id`,
`node_id`). Cross-snapshot identity exists only as natural-key strings in
`change_event.object_identifier`. This blocks:
- Criticality / usage trend analytics over time for a single object
- Cross-snapshot aggregate analytics (top-N consistently-critical objects)
- Correlation of usage drops with breaking changes across snapshots
- "Impact Analysis" in the Data DNA sense (Jon's explicit feedback: don't call it that yet)

**Proposed design — additive overlay, no rewrite:**

New table:
```sql
CREATE TABLE object_entity (
    entity_id    INTEGER  PRIMARY KEY AUTOINCREMENT,
    entity_type  TEXT     NOT NULL,   -- TABLE, VIEW, SCHEMA, COLUMN
    schema_name  TEXT     NOT NULL,
    object_name  TEXT     NOT NULL,   -- "SCHEMA.TABLE"
    first_seen   INTEGER  NOT NULL REFERENCES snapshot(snapshot_id),
    last_seen    INTEGER  NOT NULL REFERENCES snapshot(snapshot_id),
    is_active    BOOLEAN  NOT NULL DEFAULT 1,
    created_at   DATETIME NOT NULL
);
CREATE UNIQUE INDEX uix_object_entity ON object_entity(entity_type, object_name);
```

FK columns added to existing tables (nullable → backfill → NOT NULL):

| Table | Resolved by |
|---|---|
| `table_snapshot` | `(object_type, schema_name + "." + table_name)` |
| `graph_node` | `(object_type, schema_name + "." + object_name)` |
| `usage_event` | `(object_type, object_name)` |
| `change_event` | `(object_type, object_identifier)` |
| `object_criticality` | via `table_snapshot` lookup |

Resolution hook `resolve_entities(snapshot_id)` runs at ingest time: upserts entities and
sets FK columns. Backfill script handles existing snapshots.

**Note:** `node_uid` is NOT usable as resolution key — format is inconsistent between
`SnapshotEngine` (`"table:SCHEMA.TABLE"`) and `graph_builder` (`"TABLE:SCHEMA.TABLE:1"`).
Resolution uses the `(entity_type, schema_name, object_name)` natural key throughout.

**New capabilities unlocked:**
- `GET /entity/{entity_id}/history` — full criticality + usage + change history per object
- `GET /entity/resolve?name=SCHEMA.TABLE` — stable entity lookup
- Criticality trend charts over time (currently impossible)
- Usage trend per object over time
- Object lifecycle tracking (first_seen, last_seen, is_active)

**Effort:** ~8–10 days. Schema change is fully additive — no existing endpoints break.

**Execution order within Phase 2:**
1. `object_entity` table + Alembic migration
2. `resolve_entities()` hook wired into dict-import pipeline
3. Backfill existing prod snapshots
4. New `/entity/` API endpoints
5. UI: criticality trend, usage trend, object history views

- [x] Alembic migration `c3d4e5f6a7b8` — `object_entity` table + unique index `uix_object_entity_type_name`. *(v2.03.00)*
- [x] Nullable `entity_id` FK columns added to `table_snapshot`, `graph_node`, `usage_event`, `change_event` (4 tables). *(v2.03.00)*
- [x] `resolve_entities(snapshot_id, session)` hook wired in `run_post_ingest_pipeline()` as last step. *(v2.03.00)*
- [x] Backfill script `backend/tools/backfill_entities.py` — idempotent, supports `--dry-run` and `--snapshot-id`. *(v2.03.00)*
- [x] `GET /entity/{id}/history` endpoint — criticality + usage + change history across snapshots. *(v2.03.00)*
- [x] `GET /entity/resolve` endpoint — lookup by natural key (type + FQ name). *(v2.03.00)*
- [x] `GET /entity/` list endpoint — paginated, filterable by schema/type/active. *(v2.03.00)*
- [x] UI: criticality trend chart — sparkline on `/entity/[id]` page + `useEntityResolve` hook. *(v2.09.x)*
- [x] UI: usage trend per object — sparkline + usage history table on `/entity/[id]` page. *(v2.09.x)*
- [x] UI: "Entity history" link on Usage page drill-down panel + drill-down table. *(v2.09.x)*

### 2.10 Reference Data Support  ✅ COMPLETE (v2.07.00, 2026-07-20)

**Origin:** Rahul Kulkarni, Meeting 28. Prerequisite: §2.9 Integration Model.

SCION today only handles technical metadata (structure, lineage, usage). Customers need
to link that metadata with their business context: which users/teams use each object,
which business application "owns" each database/table.

**Sub-items:**

#### 2.10.a — User hierarchy ingestion  ✅
- [x] New tables: `user_entity`, `team_entity`, `department_entity` — migration `e5f6a7b8c9d0`. *(v2.07.00)*
- [x] Ingest pipeline: upload Excel/CSV via `POST /api/v1/reference-import/users` — flexible headers, idempotent upsert. *(v2.07.00)*
- [x] Nullable `username` field in `usage_event` — linkage to `user_entity` ready in DB. *(v2.07.00)*

> ⚠️ **Extractor change pending:** until the PDCR extractor provides `username` per row,
> the `usage_event.username` column stays NULL and the teams dashboard shows `—` for queries.
> The DB field already exists — only requires re-ingest when Rahul updates the extractor.

#### 2.10.b — Business Application metadata  ✅
- [x] New tables: `application_entity`, `database_application_mapping`, `table_application_mapping` — migration `e5f6a7b8c9d0`. *(v2.07.00)*
- [x] Ingest pipeline: upload Excel/CSV via `POST /api/v1/reference-import/applications`. *(v2.07.00)*
- [x] Linkage via `schema_name`/`table_name` (no extractor change required). *(v2.07.00)*

#### 2.10.c — UI dashboards  ✅
- [x] Page `/reference` — KPI row + import cards + tabs Org/Applications. *(v2.07.00)*
- [x] Dashboard "Teams" — table with dept, user count, queries, objects accessed; amber warning when no per-user data. *(v2.07.00)*
- [x] Dashboard "Applications" — table with owner team, schema count, table count, query count. *(v2.07.00)*
- [x] API `/landscape/summary` enriched with `teams_count` + `applications_count`. *(v2.07.00)*
- [ ] Filters by team/dept on Usage and Intelligence pages — pending post-extractor upgrade
- [ ] TAISA: expose user/app metadata in Q&A context — pending

---

### 2.11 Column-Level Lineage Navigation  ✅ COMPLETE (v2.05.00 — 2026-07-20)

**Origin:** Rahul Kulkarni, Meeting 28 (min 21-25). Jon Brightling mentioned it multiple
times: column-to-column flow is more important than table-to-table from the business
perspective.

**Implementation:**

- **Backend** `GET /api/v1/lineage/columns/traverse` — BFS from a specific column
  following `attribute_lineage`, up to `max_depth=20` hops. Omits `NOT APPLICABLE` sentinels.
  Returns `ColumnTraverseResponse` with `nodes[]` (depth, path[], transformation_type, tier).
- **Frontend API** — `traverseColumnLineage()` in `graph.ts`; types `TraverseNode` /
  `ColumnTraverseResponse` in `types.ts`.
- **Nav state** — `colNavStack: string[]` + `colNavHighlight: string | null` in `LineagePage`.
- **Navigate buttons** — each Sources/Feeds Into row has `←/→` (violet) that calls
  `navigateToColumn(tableKey, columnName)`: push to stack + jump.
- **Breadcrumb** — appears when `colNavStack.length > 0`; each step is clickable, Back button.
- **Column card highlight** — `colNavHighlight` card highlighted in violet.
- **Graph node ring** — `isNavPath: true` applies `#DDD6FE` ring to the node in ReactFlow.
- `focusOn()` clears the nav stack when navigating manually.

**Tasks:**
- [x] Backend: `GET /api/v1/lineage/columns/traverse?snapshot_id=N&column_key=X&direction=downstream|upstream`
- [x] Frontend: columns in the panel with `→` / `←` button; navigation breadcrumb
- [x] Navigation state in the component (visited columns stack, "back")
- [x] Full path highlight in the main ReactFlow graph

---

### 2.12 AI-Based Column Classification (PII)  ✅ COMPLETE (v2.06.00)

**Origin:** Rahul Kulkarni, Meeting 28 (min 25-28).

Use AI (TAISA) to automatically classify columns as **PII / non-PII** and assign
an importance weight, based on: column name, data type, and (if available)
column comment/description from the dict.

**Future extension (NOT in this release):** Propagation via lineage — if ACCOUNT_ID is PII,
all downstream columns inherit the tag. Rahul mentioned it but marked it as post-v2.

**Tasks:**
- [ ] Dict extractor: include `column_comment` / `column_title` if available (coordinate with Rahul)
- [ ] Alembic migration: add `pii_classification TEXT`, `pii_confidence REAL`, `importance_score REAL` to `column_snapshot`
- [ ] Backend: `POST /api/v1/columns/classify?snapshot_id=N` — batch AI classification using TAISA; prompt with name + type + comment
- [ ] Result cached in `column_snapshot` — does not recalculate unless `force=true`
- [ ] UI: PII/non-PII badge in col-lineage panel + column view of the System Graph
- [ ] UI: "Show PII columns only" filter in col-lineage

---

### 2.13 Manifest-Derived Timestamps  *(confirmed Meeting 28)*  **Est: 1 day** ✅ COMPLETE (v2.09.00, 2026-07-21)

**Origin:** Parked from previous releases, confirmed as in-scope in Meeting 28.

On the Snapshots screen (combined-snapshot view), the timestamps shown today come from
the SCION ingest time, not from the manifest that accompanies the `.dat` files.
The manifest has the timestamp of when the extractor ran on the client, which is the
business-relevant piece of information.

- [x] Read timestamp field from manifest — the UTC prefix of `extract_run_id` (`YYYYMMDDTHHMMSSz`) already contains the extractor run time; no separate file required.
- [x] Persist `extract_timestamp` in `snapshot` table (migration `a7b8c9d0e1f2`).
- [x] UI: Snapshots page shows "Extracted: {extract_timestamp}" with fallback to "ingest time" for snapshots without `extract_run_id`.

---

### 2.14 Fixed Effort Buffer  *(Meeting 28)*  **5 days reserved (updated)**

Placeholder in the estimate for high-priority items that arise during Phase 2 development.
Rahul explicitly proposed including ~1 week as a buffer.

Does not map to specific tasks today.

---

### 2.15 Access Layer — Business-Friendly Views  *(Jon Brightling email, 2026-07-17)*  **Est: 4 days**  ✅ PHASE 1 COMPLETE (v2.03.00, 2026-07-20)

**Origin:** Jon Brightling (Data DNA team), formal email 2026-07-17 to Rahul Kulkarni + Kindy
Flyvholm. He described the 3-layer architecture of DataDNA Lite 2.0: Staging → Integration
Layer → **Access Layer**.

**Mandatory prerequisites:** §2.9 Integration Model (stable entity IDs) + §2.10 Reference
Data (applications and user hierarchy already in the database). Without those two,
the Access Layer has no business data to build its views from.

**The problem with SCION today:** All navigation is technical by nature. The user must
know what a snapshot, a schema, a graph_node is. Jon described it as: *"users should
be able to discover and leverage metadata without requiring detailed technical knowledge of
the underlying source systems."*

**Difference from what was already planned:**

| Layer | What it builds | Section |
|------|--------------|---------|
| Integration Layer | Unified, persistent entity per real object | §2.9 |
| Reference Data | Business context: applications, user hierarchy | §2.10 |
| **Access Layer** | **Business-friendly presentation of all the above** | **§2.15** |

**The Access Layer does NOT remove the technical views** — it complements them. A DBA still uses
the System Graph; a Finance VP uses the Access Layer.

---

#### 2.15.a — Business Discovery Entry Point
Replace the snapshot-centric home page with a business-centric view:
- Summary: "Your data landscape: 12 Applications · 8 Teams · 4 High-risk objects · 2 recent changes"
- Three entry points: by **Business Application** / by **Team** / by **Domain**
- Cross-source search: "customer" finds `CUSTOMER_DIM`, `CUST_PROFILE`, `DIM_ACCOUNT`
  across all schemas, without knowing the schema name

- [x] `GET /api/v1/landscape/summary` — entity_count, active_entity_count, high_risk_count, recent_changes, top_risk_objects. *(v2.03.00)*
- [x] Page `/landscape` — new route with KPI cards, risk distribution bar, top critical objects, high-risk + recently changed panels. *(v2.03.00)*
- [x] Sidebar: "Landscape" entry with Globe2 icon between Intelligence and Timeline. *(v2.03.00)*
- [ ] Cross-source search via `object_entity.object_name LIKE` — pending UI input component.
- [ ] Alembic migration: none (uses §2.9 + §2.10 tables)

#### 2.15.b — Executive Summary Dashboard
High-level view for non-technical stakeholders:

- [x] `GET /api/v1/landscape/risk-overview` — risk distribution (HIGH/MEDIUM/LOW), top_critical, recently_changed_high_risk. *(v2.03.00)*
- [x] `ExecutiveSummaryDashboard` component with portfolio health score — integrated in `/landscape` page. *(v2.09.x)*
- [x] Widget "this week's changes affecting [X] applications" — uses `applications_count` + `teams_count` from `LandscapeSummary`. *(v2.09.x)*

#### 2.15.c — Entity-Centric Object View
- [x] Refactor `/entity/[id]` — business context first ("Owned by / Used by"), KPIs in business language ("Criticality", "Structural changes"), technical details (sparklines, tables, metadata) collapsible via toggle. *(v2.09.13)*
- [x] "Owned by / Used by" panel — data from §2.10, already complete (v2.07.00). *(v2.09.13)*
- [x] Criticality + query volume trend sparklines — `/entity/{id}/history` endpoint + inline SVG sparkline component. *(v2.09.x)*
- [ ] Business name / alias: optional field in `object_entity` — pending.

#### 2.15.d — Progressive Disclosure UI (Meeting 29, 2026-07-30)  🔴 PENDING
**Origin:** Meeting 29 (2026-07-30) — Kindy Flyvholm confirmed that SCION's real value
proposition is what no DBA can do today: aggregated analysis by department/application,
not the technical view of tables and columns. Chris Pilon: "it's not a race... but we are going to
try and drive each other to the best possible thing."

**The problem:** The current UI is entirely technical — the user must know what a
snapshot, a graph_node, a schema is. This blocks adoption by consultants, sales
(Lydia's team), and business stakeholders.

**Proposal:** Progressive depth without a "mode" switch. Pages speak business language
by default; technical detail appears naturally when drilling down. It is not
a second UI or a toggle — it is an information hierarchy where the top layer is
business-friendly and the DBA reaches the technical level by clicking.

**Difference from §2.15.a/b/c:** Those items add business _data_. This item changes
the _language and navigation structure_ of the entire UI so that a non-technical person
can find their way without help. Starts with Landscape (already has the criticality
and risk infrastructure) and extends to the rest if it works as a demo.

- [x] **Pilot on Entity page** — `/entity/[id]` now shows business context first and hides technical details until the user requests them. *(v2.09.13)*
- [ ] **Validate with Chris/Ripley** — demo of Landscape + Entity page before extending to the rest.
- [ ] **Extend to remaining pages** if the demo works — Changes, Intelligence, Timeline.

**Terminology note:** Jon uses "Access Layer" in the classical data warehousing sense
(Staging → Integration → Access = "consumable data mart"). In SCION we implement it as
UI layers on top of the Integration Model, without creating separate "access" tables — the view
is generated on-the-fly from `object_entity` + `application_entity` + `team_entity`.

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
| 2026-06-18 | Column-level lineage exposed via `/lineage/columns` + full UI panel | Rahul explicit request in Meeting 20: "real distinguishing point from user perspective" | v1.21.23 |
| 2026-06-18 | Column lineage dedup in API layer (not DB) | Parser intentionally stores one row per SQL step for audit trail; dedup at presentation layer preserves traceability | v1.21.24 |
| 2026-06-18 | Share scan now checks already-imported before user clicks Import | UX: user should know before clicking, not after | v1.21.26 |
| 2026-06-19 | DataDNA Lite v1.0 declared complete by Rahul (Meeting 21) | End-to-end testing passed with Ashish; one minor parser defect (Soham) non-blocking | Meeting 21 |
| 2026-06-19 | Phase 2 expands to include Ecosystem Decoded (ED) integration | Combine SCION structure/lineage with ED usage/business context; Rahul presenting to Rahul Shiyekar 2026-06-23 | Meeting 21 |
| 2026-06-19 | Three column-lineage enhancements queued (indirect lineage, type icons, step ID on edge) | Rahul requests after live demo; non-blocking for v1.0 rollout | Meeting 21 |
| 2026-06-25 | Col-lineage edge labels moved from SVG `label` prop to `EdgeLabelRenderer` (HTML above SVG) | SVG hit-zones (20px invisible) overlap on dense graphs; HTML labels give precise per-label click targets | v1.21.39 |
| 2026-06-25 | Indirect impacts dedup key = `(transformation_type, expression)` | Tier 2 parser stores one row per SQL step for audit trail; dedup at presentation collapses identical rows into a count badge | v1.21.42 |
| 2026-06-26 | Col-lineage edge label dedup key = `(source_column_key, target_column_key)` | Same source column legitimately maps to multiple target columns (e.g. LOG_MIN→_COL6 Direct Copy + LOG_MIN→_COL7 Column Expression); dedup by src alone was collapsing these | v1.21.43 |
| 2026-06-26 | `graph_diff_linker.py` fallback: name-only match when exact `(object_type, name, snapshot_id)` fails | Lineage importer creates nodes with `object_type='UNKNOWN'` while ChangeEvent has `object_type='TABLE'`; fallback fixes zero-impact display for TEDW.EVENTS_V and similar objects | v1.21.57 |
| 2026-06-26 | Graph "Unclassified" nodes from lineage importer shown as TABLE | Lineage importer uses `node_uid=SCHEMA.NAME` (no colons); SCION now resolves these as TABLE instead of UNKNOWN | v1.21.58 |
| 2026-06-26 | DEPENDS_ON button hidden when `stats.dependsEdges === 0` | In lineage-only graphs (FEEDS edges only, no data dictionary), the button was always visible but non-functional | v1.21.58 |
| 2026-07-01 | `fragility` formula fixed: `outd / max_out_degree` (was `outd / total_edges` ≈ 0 at Transcend scale) | Old formula rounded to 0.0 for all nodes on 250k-node graphs; new formula normalises against the hub node so relative fragility is preserved | v1.21.72 |
| 2026-07-01 | `change_impact_summary.direct_count` = depth-1 downstream (was total downstream count) | Old semantics: direct=total downstream, indirect=upstream count. New: direct=depth-1, indirect=depth>1 — semantically correct and consistent with UI labels | v1.21.x |
| 2026-07-01 | `object_criticality` total denominator = `SnapshotMetrics.total_objects` (was `len(ObjectCriticality rows)`) | ObjectCriticality rowcount inflated by ~845 duplicates at Transcend scale; SnapshotMetrics.total_objects = schema+table+view count is authoritative | v1.21.72 |
| 2026-07-01 | Domain risk `impact_count` uses `change_ids_by_schema` reverse mapping (was querying by schema substring match) | Old approach over-counted objects from other schemas sharing a prefix; reverse mapping is exact | v1.21.72 |
| 2026-07-15 | Integration Model (§2.9) added to Phase 2 scope | Jon Brightling (Data DNA team, Meeting 27) identified SCION as a "landing area" not an integration model; without it cross-snapshot aggregate analytics are impossible | Meeting 27 |
| 2026-07-15 | Term "Impact Analysis" to be avoided in marketing / demos | Data DNA team recommendation — the term implies capabilities SCION does not yet have at scale; preferred: "impact of change at object level" | Meeting 27 |
| 2026-07-15 | SCION scope confirmed as Kalido + Click replacement | Rahul Kulkarni in Meeting 28: SCION already replaces both Kalido (metadata integration) and Click (visualization layer); Phase 2 expands toward full Data DNA parity | Meeting 28 |
| 2026-07-15 | Reference data sourced from customer Excel/CSV, not from extractors | User hierarchy and application metadata come from customer-provided spreadsheets; technical linkage via username (PDCR) and database name (dict) | Meeting 28 |
| 2026-07-15 | PDCR extractor must provide per-user rows (not aggregated user_count) for §2.10 | Today's extractor only gives user_count; user-level usage analytics require username per row; extractor change needed from Rahul's team | Meeting 28 |
| 2026-07-15 | Column PII propagation via lineage deferred post-Phase 2 | Rahul acknowledged the feature (Data DNA does it) but explicitly deferred; Phase 2 only includes initial AI classification, not downstream propagation | Meeting 28 |
| 2026-07-15 | Phase 2 revised estimate: 3 weeks / 30 dev-days (was 2 weeks pre-Meeting 28) | Delivery 1 (30d): §2.2, §2.8, §2.9 lite, §2.11, §2.12, §2.13, §2.14. Delivery 2 (31d additional): §2.10 ref data + trend UI + perf items. §2.10 blocked pending extractor change | Meeting 28 |
| 2026-07-17 | Access Layer (§2.15) added to Phase 2 Delivery 2 | Jon Brightling email (2026-07-17) to Rahul/Kindy formally described 3-layer architecture for DataDNA Lite 2.0: Staging → Integration → Access. Access Layer = business-friendly presentation of Integration Model — entry points by application/team/domain, executive summary, entity-centric view. Requires §2.9 + §2.10 as prerequisites. Delivery 2 total updated: 25d → 34d | Jon Brightling email 2026-07-17 |
| 2026-07-17 | SCION today = Landing Area (Jon Brightling's formal characterization) | Jon described DataDNA Lite 1.0 as a "Landing Area that stores multiple snapshots" — inherently limits capabilities. Phase 2 moves to Integration Layer (§2.9) + Access Layer (§2.15). This is a strategic endorsement of the §2.9 direction, communicated formally to Rahul Kulkarni and Kindy Flyvholm | Jon Brightling email 2026-07-17 |
| 2026-07-17 | Phase 2 restructured to single delivery; SQLite→Postgres promoted to first item | Post-Pilar meeting: removed Delivery 1/2 split; SQLite→Postgres is no longer conditional — it's the performance foundation needed before building Integration Model at scale; Graph engine perf + Frontend pagination become sub-tasks of §2.5 | Pilar meeting 2026-07-17 |
| 2026-07-17 | Staging Layer (§2.16) added as prerequisite to Integration Model (§2.9) | Jon Brightling 3-layer architecture: Staging → Integration → Access; §2.16 adds validation + cross-source conflict resolution before data enters the entity layer; §2.4 DDL timestamp merge absorbed into §2.16.b | Pilar meeting 2026-07-17 |
| 2026-07-17 | Time estimates revised (post-Pilar): §2.10 12d→5d, §2.15 9d→4d, §2.14 2d→5d, §2.11 4d→5d | Adjusted based on revised scope and Pilar feedback; §2.10 reduced significantly because dashboard scope was narrowed | Pilar meeting 2026-07-17 |
| 2026-07-20 | §2.5a SQLite→Postgres migration complete in lab environment | docker-compose.lab.yml + alembic/env.py + migrate_sqlite_to_postgres.py. 47,819 rows migrated, 12 sequences reset, API verified on localhost:8080. Procedure documented in §2.5a as template for production. Gotchas captured: permissions post-docker-cp, alembic version alignment, FK orphans (DISABLE TRIGGER ALL), sequence reset per isolated transaction | Lab 2026-07-20 |
| 2026-07-20 | §2.5b/§2.6 Graph engine perf — SQL GROUP BY instead of RAM edge loading | `compute_node_metrics` was loading all edges into Python RAM (~700 MB on Transcend). Replaced by two SQL `GROUP BY` queries: only degree counts are transferred. Dead code in `blast_radius` removed (loaded all GraphNodes per snapshot but never used them). New composite index `ix_change_event_snapshot_to_object (snapshot_to, object_identifier)` via migration `a1b2c3d4e5f6` (also merges the two Alembic heads) | v2.01.00 |
| 2026-07-20 | §2.11 Col-lineage navigation complete in v2.05.00 | Traverse BFS endpoint + nav state (colNavStack/colNavHighlight) + breadcrumb + ←/→ buttons + graph ring highlight. Navigate buttons use the existing `getColumnLineage` endpoint; `traverse` endpoint available for future features (multi-hop highlight). `focusOn()` clears the stack. | v2.05.00 |
| 2026-07-20 | §2.8 Production runtime complete in v2.04.00 | Systemd: `deploy/systemd/scion.service` + `install_systemd.sh`; `install.sh` step 7 writes unit on install. JSON logging: `logging_config.py` dictConfig JSON/text via `LOG_FORMAT`; `python-json-logger==2.0.7`; nginx `json_access` format + security headers; `main.py` migrated to lifespan + `logger.info()` + CORS env-driven. | v2.04.00 |
| 2026-07-30 | Progressive Disclosure UI added as §2.15.d — pending | Meeting 29 confirmed that the real value is the analysis no DBA can do today (aggregated by dept/app). Kindy: "We never sell lineage — customers are always disappointed because it didn't solve anything." The UI must speak business language by default, with technical detail accessible via natural drill-down (no mode switch). Starts as a pilot on Landscape. | Meeting 29 (2026-07-30) |
| 2026-07-20 | §2.16 + §2.9 + §2.15 Architecture Layers implemented in v2.03.00 | Staging Layer: migration `b2c3d4e5f6a7` adds `import_status`+`validation_warnings` to `snapshot`, creates `staging_table_import`/`staging_column_import`. Pipeline hook in `run_post_ingest_pipeline` calls `validate_import()` → `committed`/`failed`. Integration Model: migration `c3d4e5f6a7b8` adds `object_entity` (unique on entity_type+object_name) + nullable FK `entity_id` on 4 tables. `resolve_entities()` wired as last pipeline step. `backfill_entities.py` for existing snapshots. APIs `/entity/` + `/landscape/`. Access Layer: new `/landscape` page with KPI cards + risk distribution bar + top critical objects. Sidebar "Landscape" entry added. | v2.03.00 |
| 2026-07-21 | Branch `hotfix/rahul-round4` created from v1.21.73 for urgent production fixes | Rahul (round 3-4) reported: case normalization in search, change-ID search, TAISA active change-ID, criticality thresholds, VIEW object type, duplicate node prevention. Fixes done in a parallel branch to lab (v1.21.74→v1.21.78) to avoid mixing with the Phase 2 lab. Merge pending. | hotfix/rahul-round4 |
| 2026-07-21 | Global case normalization + change-ID search (v1.21.74) | Case-insensitive search across all fields; change-ID now searches by prefix in addition to exact match | v1.21.74 |
| 2026-07-21 | TAISA active change-ID + clear session + configurable criticality thresholds (v1.21.75) | TAISA scope automatically set to the active change_id on screen; criticality threshold configuration via env vars | v1.21.75 |
| 2026-07-21 | 5 fixes Rahul round-4: UI/API polish (v1.21.76) | UI/API fixes reported by Rahul in round 4 of testing | v1.21.76 |
| 2026-07-21 | VIEW object type + duplicate node prevention in graph (v1.21.77) | Parser emits VIEW nodes; graph builder was deduplicating nodes with the same key | v1.21.77 |
| 2026-07-21 | Parser adapters Phase 2 + authoritative object_type from TablesV (v1.21.78) | `object_type` resolved from `TablesV` instead of inference; Informatica and OpenLineage base parsers added as stubs | v1.21.78 |
| 2026-08-31 | Meetings 32-33: Phase 2 scope expanded with GROUP 4-5 (Affinity, Duplicates, col-impact, what-if, rollup) | Rahul Kulkarni email 2026-08-07 adds affinity analysis (ED-09) and duplicate detection (ED-05). Meeting 31 (2026-08-14) adds items 16-20 (col-level impact, what-if, rollup, usage hierarchy, proactive alerts) as "Y?" pending scope confirm | Meetings 31-33 / Excel `SCION_Phase2_Estimate 2.xlsx` |

---

## Owner cheat-sheet

| Area | Primary | Secondary |
|---|---|---|
| Backend engines | Guillermo | Claude Code (AI pair) |
| Frontend | Guillermo | Claude Code (AI pair) |
| Pipeline 1 (parser) | Rahul (extract) | Guillermo (ingest) |
| Pipeline 2 (dict) | Rahul (extract) | Guillermo (ingest) |
| Pipeline 3 (usage) | Rahul (extract) | Guillermo (ingest) |
| Infra / VM | Rahul Shiyekar | Pilar (coord) |
| Release / scope | Chris | Kindy |
| Sales / use cases | Kindy | Luis |
| Project mgmt / time-tracking | Pilar | Luis |
