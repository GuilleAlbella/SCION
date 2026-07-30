# SCION — Internal Engineering Roadmap

**Audience:** SCION dev team (Guillermo + Claude Code, anyone joining).
**Not:** product strategy (`docs/Hoja de Ruta del Producto.txt`), demo script
(`docs/demo_en.txt`), or marketing (`docs/use_cases.md`).
**Purpose:** the *engineering* view — what's done, what's next, what's blocked,
who owns each piece, and the gates that have to clear before we ship to a
real customer.

Last updated: 2026-07-21 · Current version: **v2.09.00 (BETA)**.

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

**Trigger:** Phase 1 benchmark results. Phase 2 scope confirmed en Reunión 21 (2026-06-19) y ampliado en Reunión 28 (2026-07-15).
**Owner:** Guillermo. Deadline estimación: **lunes 2026-07-21**. Presentación a Chris/Pilar: **jueves 2026-07-24**.

> ⚠️ **Scope de trabajo — SOLO LAB hasta nueva indicación.**
> Todo el desarrollo, testing y validación de Phase 2 se hace contra el entorno lab
> (`docker-compose.lab.yml`, Postgres en `localhost:8080`). El deploy de producción
> (`ps-ubuntu-0043`, `docker-compose.yml`) NO se toca hasta que Phase 2 esté validada
> en lab. Las comprobaciones funcionales, los benchmarks y los tests se ejecutan en lab.
>
> **Base de datos activa en lab:** Postgres 16 — volumen `scion-lab_pgdata`.
> Todo el stack (importer, graph engine, impact, TAISA, usage) apunta a Postgres
> via `DATABASE_URL=postgresql+psycopg://scion:scion_lab@postgres:5432/scion`.
> Los archivos SQLite en el container (`kalido_lite.db`, `scion_source.db`) son inertes.

> **DataDNA Lite v1.0 declared complete by Rahul (Reunión 21, 2026-06-19).** SCION reemplaza tanto Kalido (integración de metadata) como Click (visualización). Phase 2 expande el scope a integration model completo + reference data + AI classification.

---

### Resumen de estimación Phase 2

Asunción: **1 developer (Guillermo) + Claude Code (AI-assisted)**, semanas de 5 días.
Con AI-assisted development la velocidad efectiva es ~1.8–2x. Los días son **días calendario reales**.

Reestructurado post-reunión con Pilar (2026-07-17): entrega única en vez de dos, SQLite→Postgres como primer item obligatorio (fundación para Integration Model), seguido por las 3 capas de Jon Brightling.

#### Entrega única — Phase 2 completo

| # | Ítem | Descripción breve | Est. (días) | Notas |
|---|------|--------------------|------------|-------|
| **2.5** | **SQLite → Postgres** | DB engine migration — fundación de performance | **4** | Primer item; ya no condicional |
| ↳ 2.6 | Graph engine perf | Lazy-load nodos + indexing | **2** | Sub-task de 2.5 |
| ↳ 2.7 | Frontend pagination | Server-side + lazy graph fetch | **2** | Sub-task de 2.5 |
| **2.16** | **Staging Layer** | Validación + resolución cross-source antes de Integration | **5** | NUEVO — arquitectura Jon Brightling |
| **2.9** | **Integration Model** | Entity layer + backfill + trend UI | **7** | Requiere §2.16 |
| **2.15** | **Access Layer** | Business Discovery + Executive Dashboard + Entity view | **4** | Requiere §2.9 + §2.10 |
| **2.8** | Production runtime | Systemd units + JSON logging | **1** | — |
| **2.11** | ~~Col-lineage navigation~~ | ~~Downstream + upstream interactivo~~ | **✅** | v2.05.00 |
| **2.12** | ~~AI column classification~~ | ~~PII / non-PII por nombre, tipo y comentario~~ | **✅** | v2.06.00 |
| **2.10** | ~~Reference data~~ | ~~User hierarchy + app metadata + dashboards~~ | **✅** | v2.07.00 |
| **2.2** | ~~Incremental loading~~ | ~~CDC contra baseline day zero~~ | **✅** | v2.08.00 |
| **2.13** | ~~Manifest timestamps~~ | ~~Timestamps del extractor en snapshot screen~~ | **✅** | v2.09.00 |
| **2.4** | DDL timestamp merge | Mantener versión más reciente en ingest | **1** | — |
| **2.14** | Buffer (contingency) | Reservado para imprevistos | **5** | — |
| | **TOTAL BRUTO** | | **49** | |
| | *Ganancia AI-assisted (~20%)* | | *−10* | |
| | **TOTAL NETO** | | **~39 días** | ~8 semanas |

> ⚠️ §2.10 bloqueado hasta que el extractor de Rahul provea username por fila (hoy solo `user_count`).
> §2.16 Staging Layer es prerequisito de §2.9. §2.15 Access Layer requiere §2.9 + §2.10 completos.

---

Subject to what the real-data numbers tell us. Ítems:

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

### 2.2 Incremental snapshot handling *(confirmed Reunión 18)* ✅ COMPLETO (v2.08.00, 2026-07-21)

- [x] SCION must compare incremental batches against a "day zero" baseline (not the previous incremental).
- [x] Track cumulative object count across batches.
- [x] On full reset (gap in data), create a new day zero and reset baseline.

### 2.3 Dict view-definition parsing *(confirmed Reunión 18 — parser team)*

- [ ] Code Parser to parse view DDLs from the data dictionary (not just DBQL).
- [ ] Covers views created before the extraction window (lineage gaps in DBQL-only mode).
- [ ] Output: same JSON lineage format; SCION ingests alongside existing dict batch.
- [ ] Execution model: run once on "day zero", then incremental via DBQL.

### 2.4 DDL timestamp merge *(confirmed Reunión 19)*

- [ ] Same object can arrive from DBQL extract AND dict extract with different timestamps.
- [ ] SCION must keep the *latest* version (compare DDL timestamps on ingest).
- [ ] Applies to: views, stored procedures, macros, triggers.

### 2.5 SQLite → Postgres  *(primer item — post-reunión Pilar, 2026-07-17)*  **Est: 4 días**

Antes marcado como condicional. Decisión post-reunión con Pilar: se hace primero como fundación
de performance antes de construir el Integration Model sobre ella. Graph engine perf y
Frontend pagination son sub-tareas que se completan en paralelo con la migración.

**Sub-tareas:**

#### 2.5a — Migración de motor (2.5 core — 4 días)  ✅ LAB COMPLETO (2026-07-20)
- SQLAlchemy abstrae el engine — el grueso del trabajo es operacional, no código.
- [x] Connection-string + driver switch — `psycopg[binary]==3.2.13` (v3); dialect `postgresql+psycopg://`.
- [x] Todas las Alembic migrations corren contra Postgres — `alembic/env.py` actualizado para leer `DATABASE_URL` y registrar todos los modelos ORM via `app.db.base`.
- [x] FK/cascade behaviour verificado — SQLite no enforcea FKs; Postgres sí. Mitigado con `ALTER TABLE … DISABLE TRIGGER ALL` en el script de migración.
- [x] `docker-compose.lab.yml` creado con servicio Postgres 16-alpine (puerto 5432 interno, SCION en 8080).
- [x] `DATABASE_URL` env var en docker-compose.lab.yml; producción usa `sqlite:////data/scion.db` hasta migración.
- [x] 47 819 filas migradas a Postgres en lab. API verificada: `GET /api/v1/snapshots` devuelve 10 snapshots correctamente.

##### Archivos clave
| Archivo | Descripción |
|---|---|
| `docker-compose.lab.yml` | Entorno lab con Postgres 16-alpine + SCION en puerto 8080 |
| `alembic/env.py` | Lee `DATABASE_URL` env var; importa `app.db.base` (todos los modelos) |
| `backend/tools/migrate_sqlite_to_postgres.py` | Script de migración one-shot SQLite → Postgres |

##### Procedimiento de migración — lab (template para producción)

> Ejecutar **dentro del container backend** (`docker exec scion-lab-backend …`).

```bash
# Paso 1 — Copiar SQLite al container
#   (lab: kalido_lite.db  |  prod: el volumen ya está montado en /data/scion.db)
docker cp kalido_lite.db scion-lab-backend:/tmp/scion_source.db

# Paso 2 — Ajustar permisos (docker cp deja el archivo como root)
docker exec --user root scion-lab-backend chown scion:scion /tmp/scion_source.db

# Paso 3 — Actualizar fuente SQLite a alembic HEAD
#   (necesario si el backup fue tomado antes de la última migration)
docker exec scion-lab-backend python backend/tools/db_init.py init \
    --db-url sqlite:////tmp/scion_source.db

# Paso 4 — Dry-run: verificar conteo de filas por tabla
docker exec scion-lab-backend python backend/tools/migrate_sqlite_to_postgres.py --dry-run

# Paso 5 — Migración completa
docker exec scion-lab-backend python backend/tools/migrate_sqlite_to_postgres.py
```

> **En producción**, reemplazar `scion-lab-backend` por `scion-backend` y `--source` por
> `sqlite:////data/scion.db` (el volumen ya está montado ahí).
> El `DATABASE_URL` del container apuntará al Postgres de producción por la configuración del
> `docker-compose.yml` (sin necesidad de `--target` explícito).

##### Gotchas documentados

| Problema | Causa | Solución |
|---|---|---|
| `attempt to write a readonly database` | `docker cp` copia con owner root | `docker exec --user root … chown scion:scion …` |
| `alembic_version mismatch` | Backup tomado 2 migrations antes de HEAD | Correr `db_init.py init --db-url sqlite:///…` en la fuente |
| `ForeignKeyViolation` al insertar | SQLite no enforcea FKs — filas huérfanas en fuente | `ALTER TABLE … DISABLE TRIGGER ALL` por batch (ya en el script) |
| `InFailedSqlTransaction` en reset de sequences | Secuencia no existe para columnas FK o UUID PK | Cada reset usa su propia transacción `engine.begin()` — las fallidas se ignoran |
| Comandos multilínea en PowerShell con `docker exec` | PowerShell interpreta `"..."` de forma distinta | Usar heredoc `$script = @'...'@; $script \| docker exec -i container python` |

#### 2.5b — Graph engine performance (§2.6 — 2 días)  ✅ COMPLETO (2026-07-20)
- [x] **Lazy-load graph nodes on demand** — `compute_node_metrics` reemplazado: en vez de cargar todos los nodes+edges en Python RAM (~700 MB en Transcend), usa dos `GROUP BY` en SQL. Solo se transfieren los conteos de grado, no las filas de edges. *(v2.01.00)*
- [x] **Computed metrics persistidas en DB** — `node_metadata` JSON en `graph_node` ya almacenaba `{in_degree, out_degree, fragility, is_hub}`; `persist_node_metrics` sigue escribiendo post-ingest. Dead code en `blast_radius.py` eliminado (cargaba todos los `GraphNode` por snapshot para construir `node_names`/`node_schemas` que nunca se usaban). *(v2.01.00)*
- [x] **Index on `change_event(snapshot_to, object_identifier)`** — migration `a1b2c3d4e5f6` añade `ix_change_event_snapshot_to_object`. También mergea los dos heads de Alembic que existían (`f1a2b3c4d5e6` + `d61e9f7a2b34`). *(v2.01.00)*

#### 2.5c — Frontend pagination (§2.7 — 2 días)  ✅ COMPLETO (v2.02.00, 2026-07-20)
- [x] Server-side pagination en /changes — infinite scroll con IntersectionObserver; reemplaza Previous/Next. `fetchPage` ya tenía modo `"append"`; ahora conectado a sentinel div + observer (rootMargin 400 px). Status row muestra `N / total cargados`. *(v2.02.00)*
- [x] Lazy graph fetch — `/graph/{snapshot_id}` trunca a 5 000 nodos y devuelve `truncated: true`; frontend muestra banner para elegir anchor de focus mode. `/graph/focus` hace BFS server-side (cap 1 000 nodos). Ya operativo desde v1.11.00. *(v2.02.00)*

### 2.6 Graph engine performance  ✅ COMPLETO (v2.01.00, 2026-07-20)
- [x] Lazy-load graph nodes on demand — SQL GROUP BY en `compute_node_metrics`.
- [x] Computed metrics persistidas en DB — `node_metadata` JSON en `graph_node`.
- [x] Index on `change_event(snapshot_to, object_identifier)` — migration `a1b2c3d4e5f6`.
- [ ] Cython / Rust para `compute_impact` — descartado por ahora; CTEs SQL son suficientes al escalar.

### 2.7 Frontend rendering  ✅ COMPLETO (v2.02.00, 2026-07-20)
- [x] Focus mode for /graph (v1.11.00).
- [x] Server-side infinite scroll on /changes — IntersectionObserver replaces Previous/Next; append mode wired to sentinel div. *(v2.02.00)*
- [x] Lazy graph fetch — truncation at 5 000 nodes + focus-mode BFS already in place since v1.11.00. *(v2.02.00)*

### 2.8 Production runtime  ✅ COMPLETO (v2.04.00, 2026-07-20)
- [x] `docker-compose.yml` — backend + frontend (production build) + nginx reverse proxy. Live on ps-ubuntu-0043 since v1.21.x. GHCR image publish wired.
- [x] Health check endpoints (`/healthz`, `/readyz`). *(v1.21.x)*
- [x] Linux systemd units — `deploy/systemd/scion.service` + `deploy/install_systemd.sh`. `docker/install.sh` paso 7 instala y habilita el unit automáticamente en Linux. Type=oneshot+RemainAfterExit; restart on-failure; EnvironmentFile desde `.env`. *(v2.04.00)*
- [x] Structured JSON logging — `backend/app/logging_config.py` (dictConfig JSON/text, controlado por `LOG_FORMAT` env var). `python-json-logger==2.0.7`. nginx `log_format json_access escape=json` + security headers. `main.py` migrado a `lifespan`, `print()→logger.info()`, CORS desde `ALLOWED_ORIGINS` env var. *(v2.04.00)*

### 2.16 Staging Layer  *(nuevo — arquitectura Jon Brightling, 2026-07-17)*  **Est: 5 días**  ✅ COMPLETO (v2.03.00, 2026-07-20)

**Origin:** Jon Brightling email 2026-07-17. La arquitectura formal de 3 capas es:
**Staging → Integration → Access**. El Staging Layer es el prerequisito directo del Integration
Model (§2.9) — los datos deben pasar por validación y normalización antes de entrar a la
capa de entidades persistentes.

**Qué hace:** Recibe los extracts crudos del cliente (`.dat`, `.json`), los valida, resuelve
conflictos cross-source, y los "promueve" al Integration Model cuando están limpios. Hoy SCION
persiste directo desde el import — el Staging Layer agrega una capa intermedia controlada.

**Componentes:**

#### 2.16.a — Tablas de staging + status tracking
- [x] Nuevas tablas: `staging_table_import`, `staging_column_import` — migration `b2c3d4e5f6a7`. *(v2.03.00)*
- [x] Campo `import_status` en `snapshot`: `pending → staged → committed → failed` — migration `b2c3d4e5f6a7` + `snapshot.validation_warnings` JSON field. *(v2.03.00)*
- [x] Alembic migration `b2c3d4e5f6a7` — revises `a1b2c3d4e5f6`. *(v2.03.00)*

#### 2.16.b — Pipeline de validación
- [x] Validar completitud: `schema_name` no-null, tipos de datos reconocidos — `staging_validator.py` rules: NULL_SCHEMA + UNKNOWN_TYPE. *(v2.03.00)*
- [x] Detectar y loggear duplicados cross-source — DUPLICATE_TABLE hard error; sets `import_status='failed'`. *(v2.03.00)*
- [x] Regla de resolución: mantener versión más reciente por `DDL_timestamp` (absorbe §2.4) — UNKNOWN_TYPE/NULL_SCHEMA as warnings, DUPLICATE_TABLE as hard error. §2.4 absorbed. *(v2.03.00)*
- [x] Resultado: reporte de import con filas aceptadas / rechazadas / resueltas — stored in `snapshot.validation_warnings` JSON + `staging_table_import.row_status`. *(v2.03.00)*

#### 2.16.c — UI: import status en Snapshots page
- [x] Mostrar estado `staged / committed / failed` por snapshot — badge column en tabla de snapshots (verde/azul/rojo). *(v2.03.00)*
- [ ] Detalle de conflictos resueltos (qué source ganó y por qué) — pendiente UI (datos ya están en `validation_warnings` JSON).

**Nota:** §2.4 DDL timestamp merge queda absorbido por §2.16.b — ya no es ítem separado.

---

### 2.9 Integration Model — Cross-Snapshot Entity Layer  *(Reunión 27 + Reunión 28)*  ✅ BACKEND COMPLETO (v2.03.00, 2026-07-20)

**Origin:** Jon Brightling (Data DNA team) identified in Reunión 27 (2026-07-15). Confirmed
in Reunión 28 by Rahul Kulkarni: this is the equivalent of the **Kalido BIM model** —
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
- [ ] UI: criticality trend chart — backend history endpoint ready; frontend component pendiente.
- [ ] UI: usage trend per object — same, pendiente frontend.

### 2.10 Reference Data Support  ✅ COMPLETO (v2.07.00, 2026-07-20)

**Origin:** Rahul Kulkarni, Reunión 28. Prerequisito: §2.9 Integration Model.

SCION hoy solo maneja metadata técnica (structure, lineage, usage). Los clientes necesitan
vincular esa metadata con su contexto de negocio: qué usuarios/equipos usan cada objeto,
qué aplicación de negocio "es dueña" de cada base de datos/tabla.

**Sub-ítems:**

#### 2.10.a — User hierarchy ingestion  ✅
- [x] Nuevas tablas: `user_entity`, `team_entity`, `department_entity` — migration `e5f6a7b8c9d0`. *(v2.07.00)*
- [x] Pipeline de ingest: upload Excel/CSV vía `POST /api/v1/reference-import/users` — headers flexibles, upsert idempotente. *(v2.07.00)*
- [x] Campo `username` nullable en `usage_event` — linkeo con `user_entity` listo en la DB. *(v2.07.00)*

> ⚠️ **Cambio en extractor pendiente:** hasta que el PDCR extractor provea `username` por fila,
> la columna `usage_event.username` queda NULL y el dashboard de teams muestra `—` en queries.
> El campo en DB ya existe — sólo requiere re-ingest cuando Rahul actualice el extractor.

#### 2.10.b — Business Application metadata  ✅
- [x] Nuevas tablas: `application_entity`, `database_application_mapping`, `table_application_mapping` — migration `e5f6a7b8c9d0`. *(v2.07.00)*
- [x] Pipeline de ingest: upload Excel/CSV vía `POST /api/v1/reference-import/applications`. *(v2.07.00)*
- [x] Linkeo via `schema_name`/`table_name` (no requiere cambio en extractor). *(v2.07.00)*

#### 2.10.c — UI dashboards  ✅
- [x] Página `/reference` — KPI row + import cards + tabs Org/Applications. *(v2.07.00)*
- [x] Dashboard "Teams" — tabla con dept, user count, queries, objects accessed; aviso ámbar cuando no hay per-user data. *(v2.07.00)*
- [x] Dashboard "Applications" — tabla con owner team, schema count, table count, query count. *(v2.07.00)*
- [x] API `/landscape/summary` enriquecida con `teams_count` + `applications_count`. *(v2.07.00)*
- [ ] Filtros por team/dept en páginas Usage e Intelligence — pendiente post-extractor upgrade
- [ ] TAISA: exponer user/app metadata en el contexto de Q&A — pendiente

---

### 2.11 Column-Level Lineage Navigation  ✅ COMPLETO (v2.05.00 — 2026-07-20)

**Origin:** Rahul Kulkarni, Reunión 28 (min 21-25). Jon Brightling lo mencionó múltiples
veces: column-to-column flow es más importante que table-to-table desde la perspectiva del
negocio.

**Implementación:**

- **Backend** `GET /api/v1/lineage/columns/traverse` — BFS desde una columna específica
  siguiendo `attribute_lineage`, hasta `max_depth=20` hops. Omite sentinelas `NOT APPLICABLE`.
  Devuelve `ColumnTraverseResponse` con `nodes[]` (depth, path[], transformation_type, tier).
- **Frontend API** — `traverseColumnLineage()` en `graph.ts`; tipos `TraverseNode` /
  `ColumnTraverseResponse` en `types.ts`.
- **Nav state** — `colNavStack: string[]` + `colNavHighlight: string | null` en `LineagePage`.
- **Navigate buttons** — cada fila de Sources/Feeds Into tiene `←/→` (violet) que llama a
  `navigateToColumn(tableKey, columnName)`: push al stack + jump.
- **Breadcrumb** — aparece con `colNavStack.length > 0`; cada paso es clicable, botón Back.
- **Column card highlight** — tarjeta del `colNavHighlight` resaltada en violeta.
- **Graph node ring** — `isNavPath: true` aplica anillo `#DDD6FE` sobre el nodo en ReactFlow.
- `focusOn()` limpia el nav stack al navegar manualmente.

**Tareas:**
- [x] Backend: `GET /api/v1/lineage/columns/traverse?snapshot_id=N&column_key=X&direction=downstream|upstream`
- [x] Frontend: columnas en el panel con botón `→` / `←`; breadcrumb de navegación
- [x] Estado de navegación en el componente (stack de columnas visitadas, "back")
- [x] Highlight del path completo en el ReactFlow graph principal

---

### 2.12 AI-Based Column Classification (PII)  ✅ COMPLETO (v2.06.00)

**Origin:** Rahul Kulkarni, Reunión 28 (min 25-28).

Usar AI (TAISA) para clasificar automáticamente columnas como **PII / non-PII** y asignar
un peso de importancia, basándose en: nombre de columna, data type, y (si disponible)
comentario/descripción de la columna desde el dict.

**Futura extensión (NO en este release):** Propagación por lineage — si ACCOUNT_ID es PII,
todas las columnas downstream heredan el tag. Rahul lo mencionó pero lo marcó como post-v2.

**Tareas:**
- [ ] Dict extractor: incluir `column_comment` / `column_title` si disponible (coordinar con Rahul)
- [ ] Alembic migration: agregar `pii_classification TEXT`, `pii_confidence REAL`, `importance_score REAL` a `column_snapshot`
- [ ] Backend: `POST /api/v1/columns/classify?snapshot_id=N` — batch AI classification usando TAISA; prompt con nombre + type + comentario
- [ ] Resultado cacheado en `column_snapshot` — no recalcula salvo `force=true`
- [ ] UI: badge PII/non-PII en col-lineage panel + column view del System Graph
- [ ] UI: filtro "Show PII columns only" en col-lineage

---

### 2.13 Manifest-Derived Timestamps  *(confirmado Reunión 28)*  **Est: 1 día** ✅ COMPLETO (v2.09.00, 2026-07-21)

**Origin:** Parked desde releases previos, confirmado como in-scope en Reunión 28.

En la pantalla de Snapshots (combined-snapshot view), los timestamps que se muestran hoy
vienen del momento de ingest en SCION, no del manifest que acompaña a los archivos `.dat`.
El manifest tiene el timestamp de cuando el extractor corrió en el cliente, que es el dato
relevante para el negocio.

- [x] Leer campo de timestamp del manifest — el prefijo UTC de `extract_run_id` (`YYYYMMDDTHHMMSSz`) ya contiene la hora del extractor; no requiere archivo separado.
- [x] Persistir `extract_timestamp` en tabla `snapshot` (migration `a7b8c9d0e1f2`).
- [x] UI: Snapshots page muestra "Extracted: {extract_timestamp}" con fallback a "ingest time" para snapshots sin `extract_run_id`.

---

### 2.14 Fixed Effort Buffer  *(Reunión 28)*  **5 días reservados (actualizado)**

Placeholder en la estimación para ítems de prioridad alta que surjan durante el desarrollo
de Phase 2. Rahul propuso explícitamente incluir ~1 semana como colchón.

No mapea a tareas específicas hoy.

---

### 2.15 Access Layer — Business-Friendly Views  *(Jon Brightling email, 2026-07-17)*  **Est: 4 días**  ✅ FASE 1 COMPLETA (v2.03.00, 2026-07-20)

**Origin:** Jon Brightling (Data DNA team), email formal 2026-07-17 a Rahul Kulkarni + Kindy
Flyvholm. Describió la arquitectura de 3 capas de DataDNA Lite 2.0: Staging → Integration
Layer → **Access Layer**.

**Prerequisitos obligatorios:** §2.9 Integration Model (entity IDs estables) + §2.10 Reference
Data (aplicaciones y jerarquía de usuarios existentes en la base de datos). Sin esos dos,
la Access Layer no tiene datos de negocio con qué construir sus vistas.

**El problema de SCION hoy:** Toda la navegación es técnica por naturaleza. El usuario debe
conocer qué es un snapshot, un schema, un graph_node. Jon lo describió como: *"users should
be able to discover and leverage metadata without requiring detailed technical knowledge of
the underlying source systems."*

**Diferencia con lo ya planificado:**

| Capa | Qué construye | Sección |
|------|--------------|---------|
| Integration Layer | Entidad unificada y persistente por objeto real | §2.9 |
| Reference Data | Contexto de negocio: aplicaciones, jerarquía de users | §2.10 |
| **Access Layer** | **Presentación business-friendly de todo lo anterior** | **§2.15** |

**La Access Layer NO elimina las vistas técnicas** — las complementa. Un DBA sigue usando
el System Graph; un VP de Finance usa la Access Layer.

---

#### 2.15.a — Business Discovery Entry Point
Reemplazar la home page centrada en snapshots por una vista centrada en el negocio:
- Resumen: "Your data landscape: 12 Applications · 8 Teams · 4 High-risk objects · 2 recent changes"
- Tres puntos de entrada: por **Aplicación de negocio** / por **Equipo** / por **Dominio**
- Búsqueda cross-source: "customer" encuentra `CUSTOMER_DIM`, `CUST_PROFILE`, `DIM_ACCOUNT`
  en todos los schemas, sin saber el schema name

- [x] `GET /api/v1/landscape/summary` — entity_count, active_entity_count, high_risk_count, recent_changes, top_risk_objects. *(v2.03.00)*
- [x] Página `/landscape` — nueva ruta con KPI cards, risk distribution bar, top critical objects, high-risk + recently changed panels. *(v2.03.00)*
- [x] Sidebar: entrada "Landscape" con Globe2 icon entre Intelligence y Timeline. *(v2.03.00)*
- [ ] Búsqueda cross-source via `object_entity.object_name LIKE` — pendiente UI input component.
- [ ] Alembic migration: ninguna (usa tablas de §2.9 + §2.10)

#### 2.15.b — Executive Summary Dashboard
Vista de alto nivel para stakeholders no técnicos:

- [x] `GET /api/v1/landscape/risk-overview` — risk distribution (HIGH/MEDIUM/LOW), top_critical, recently_changed_high_risk. *(v2.03.00)*
- [ ] Componente `ExecutiveSummaryDashboard` con portfolio health score — pendiente (requiere §2.10 para datos de aplicaciones).
- [ ] Widget "cambios de esta semana que afectan [X] aplicaciones" — bloqueado por §2.10.

#### 2.15.c — Entity-Centric Object View
- [ ] Refactor `ObjectDetailPage` — business context primero, technical details colapsables.
- [ ] Panel "Owned by / Used by" — bloqueado por §2.10 (application_entity + team_entity).
- [ ] Criticality trend chart — `/entity/{id}/history` endpoint listo; pendiente frontend chart component.
- [ ] Business name / alias: campo opcional en `object_entity` — pendiente.

#### 2.15.d — Progressive Disclosure UI (Reunión 29, 2026-07-30)  🔴 PENDIENTE
**Origen:** Reunión 29 (2026-07-30) — Kindy Flyvholm confirmó que la propuesta de valor real
de SCION es lo que ningún DBA puede hacer hoy: análisis aggregado por departamento/aplicación,
no la vista técnica de tablas y columnas. Chris Pilon: "it's not a race... but we are going to
try and drive each other to the best possible thing."

**El problema:** La UI actual es completamente técnica — el usuario debe conocer qué es un
snapshot, un graph_node, un schema. Esto bloquea la adopción por parte de consultores, sales
(Lydia's team), y stakeholders de negocio.

**Propuesta:** Profundidad progresiva sin switch de "modo". Las páginas hablan en lenguaje
de negocio por defecto; el detalle técnico aparece naturalmente al hacer drill-down. No es
una segunda UI ni un toggle — es una jerarquía de información donde la capa superior es
business-friendly y el DBA llega al nivel técnico haciendo click.

**Diferencia con §2.15.a/b/c:** Esos ítems añaden _datos_ de negocio. Este ítem cambia
el _lenguaje y la estructura de navegación_ de toda la UI para que una persona no técnica
pueda orientarse sin ayuda. Empieza por Landscape (ya tiene la infraestructura de criticality
y risk) y se extiende al resto si funciona como demo.

- [ ] **Rediseño Landscape como piloto** — home page habla en términos de "X objetos críticos
      en el esquema FINANCE — 3 cambiaron esta semana", no en "snapshot #12 · 847 objects".
      El DBA que hace click llega al SQL name, columnas, query count, lineage graph.
- [ ] **Validar con Chris/Ripley** — una demo de Landscape rediseñado como prueba de concepto
      antes de extender al resto de páginas.
- [ ] **Extender al resto de páginas** si la demo funciona — Changes, Intelligence, Timeline.

**Nota sobre terminología:** Jon usa "Access Layer" en sentido de data warehousing clásico
(Staging → Integration → Access = "data mart consumible"). En SCION lo implementamos como
capas de UI sobre el Integration Model, sin crear tablas separadas de "access" — la vista
se genera on-the-fly desde `object_entity` + `application_entity` + `team_entity`.

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
| 2026-06-26 | `graph_diff_linker.py` fallback: name-only match when exact `(object_type, name, snapshot_id)` fails | Lineage importer creates nodes with `object_type='UNKNOWN'` while ChangeEvent has `object_type='TABLE'`; fallback fixes zero-impact display for TEDW.EVENTS_V and similar objects | v1.21.57 |
| 2026-06-26 | Graph "Unclassified" nodes from lineage importer shown as TABLE | Lineage importer uses `node_uid=SCHEMA.NAME` (no colons); SCION now resolves these as TABLE instead of UNKNOWN | v1.21.58 |
| 2026-06-26 | DEPENDS_ON button hidden when `stats.dependsEdges === 0` | In lineage-only graphs (FEEDS edges only, no data dictionary), the button was always visible but non-functional | v1.21.58 |
| 2026-07-01 | `fragility` formula fixed: `outd / max_out_degree` (was `outd / total_edges` ≈ 0 at Transcend scale) | Old formula rounded to 0.0 for all nodes on 250k-node graphs; new formula normalises against the hub node so relative fragility is preserved | v1.21.72 |
| 2026-07-01 | `change_impact_summary.direct_count` = depth-1 downstream (was total downstream count) | Old semantics: direct=total downstream, indirect=upstream count. New: direct=depth-1, indirect=depth>1 — semantically correct and consistent with UI labels | v1.21.x |
| 2026-07-01 | `object_criticality` total denominator = `SnapshotMetrics.total_objects` (was `len(ObjectCriticality rows)`) | ObjectCriticality rowcount inflated by ~845 duplicates at Transcend scale; SnapshotMetrics.total_objects = schema+table+view count is authoritative | v1.21.72 |
| 2026-07-01 | Domain risk `impact_count` uses `change_ids_by_schema` reverse mapping (was querying by schema substring match) | Old approach over-counted objects from other schemas sharing a prefix; reverse mapping is exact | v1.21.72 |
| 2026-07-15 | Integration Model (§2.9) added to Phase 2 scope | Jon Brightling (Data DNA team, Reunión 27) identified SCION as a "landing area" not an integration model; without it cross-snapshot aggregate analytics are impossible | Reunión 27 |
| 2026-07-15 | Term "Impact Analysis" to be avoided in marketing / demos | Data DNA team recommendation — the term implies capabilities SCION does not yet have at scale; preferred: "impact of change at object level" | Reunión 27 |
| 2026-07-15 | SCION scope confirmed as Kalido + Click replacement | Rahul Kulkarni in Reunión 28: SCION already replaces both Kalido (metadata integration) and Click (visualization layer); Phase 2 expands toward full Data DNA parity | Reunión 28 |
| 2026-07-15 | Reference data sourced from customer Excel/CSV, not from extractors | User hierarchy and application metadata come from customer-provided spreadsheets; technical linkage via username (PDCR) and database name (dict) | Reunión 28 |
| 2026-07-15 | PDCR extractor must provide per-user rows (not aggregated user_count) for §2.10 | Today's extractor only gives user_count; user-level usage analytics require username per row; extractor change needed from Rahul's team | Reunión 28 |
| 2026-07-15 | Column PII propagation via lineage deferred post-Phase 2 | Rahul acknowledged the feature (Data DNA does it) but explicitly deferred; Phase 2 only includes initial AI classification, not downstream propagation | Reunión 28 |
| 2026-07-15 | Phase 2 revised estimate: 3 semanas / 30 dev-days (was 2 semanas pre-Reunión 28) | Entrega 1 (30d): §2.2, §2.8, §2.9 lite, §2.11, §2.12, §2.13, §2.14. Entrega 2 (31d adicionales): §2.10 ref data + trend UI + perf items. §2.10 bloqueado por cambio en extractor | Reunión 28 |
| 2026-07-17 | Access Layer (§2.15) added to Phase 2 Entrega 2 | Jon Brightling email (2026-07-17) to Rahul/Kindy formally described 3-layer architecture for DataDNA Lite 2.0: Staging → Integration → Access. Access Layer = business-friendly presentation of Integration Model — entry points by application/team/domain, executive summary, entity-centric view. Requires §2.9 + §2.10 as prerequisites. Entrega 2 total updated: 25d → 34d | Jon Brightling email 2026-07-17 |
| 2026-07-17 | SCION today = Landing Area (Jon Brightling's formal characterization) | Jon described DataDNA Lite 1.0 as a "Landing Area that stores multiple snapshots" — inherently limits capabilities. Phase 2 moves to Integration Layer (§2.9) + Access Layer (§2.15). This is a strategic endorsement of the §2.9 direction, communicated formally to Rahul Kulkarni and Kindy Flyvholm | Jon Brightling email 2026-07-17 |
| 2026-07-17 | Phase 2 restructured to single delivery; SQLite→Postgres promoted to first item | Post-Pilar meeting: removed Entrega 1/2 split; SQLite→Postgres is no longer conditional — it's the performance foundation needed before building Integration Model at scale; Graph engine perf + Frontend pagination become sub-tasks of §2.5 | Reunión Pilar 2026-07-17 |
| 2026-07-17 | Staging Layer (§2.16) added as prerequisite to Integration Model (§2.9) | Jon Brightling 3-layer architecture: Staging → Integration → Access; §2.16 adds validation + cross-source conflict resolution before data enters the entity layer; §2.4 DDL timestamp merge absorbed into §2.16.b | Reunión Pilar 2026-07-17 |
| 2026-07-17 | Time estimates revised (post-Pilar): §2.10 12d→5d, §2.15 9d→4d, §2.14 2d→5d, §2.11 4d→5d | Adjusted based on revised scope and Pilar feedback; §2.10 reduced significantly because dashboard scope was narrowed | Reunión Pilar 2026-07-17 |
| 2026-07-20 | §2.5a SQLite→Postgres migración completa en entorno lab | docker-compose.lab.yml + alembic/env.py + migrate_sqlite_to_postgres.py. 47 819 filas migradas, 12 secuencias reseteadas, API verificada en localhost:8080. Procedimiento documentado en §2.5a como template para producción. Gotchas capturados: permisos post-docker-cp, alembic version alignment, FK orphans (DISABLE TRIGGER ALL), sequence reset por transacción aislada | Lab 2026-07-20 |
| 2026-07-20 | §2.5b/§2.6 Graph engine perf — SQL GROUP BY en lugar de carga RAM de edges | `compute_node_metrics` cargaba todos los edges en Python RAM (~700 MB en Transcend). Reemplazado por dos `GROUP BY` SQL: solo los conteos de grado se transfieren. Dead code en `blast_radius` eliminado (cargaba todos los GraphNodes por snapshot pero nunca los usaba). Nuevo índice compuesto `ix_change_event_snapshot_to_object (snapshot_to, object_identifier)` via migration `a1b2c3d4e5f6` (también mergea los dos heads de Alembic) | v2.01.00 |
| 2026-07-20 | §2.11 Col-lineage navigation completo en v2.05.00 | Traverse BFS endpoint + nav state (colNavStack/colNavHighlight) + breadcrumb + ←/→ buttons + graph ring highlight. Navigate buttons usan el endpoint existente `getColumnLineage`; `traverse` endpoint disponible para features futuras (highlight multi-hop). `focusOn()` limpia el stack. | v2.05.00 |
| 2026-07-20 | §2.8 Production runtime completo en v2.04.00 | Systemd: `deploy/systemd/scion.service` + `install_systemd.sh`; `install.sh` paso 7 escribe unit al instalar. JSON logging: `logging_config.py` dictConfig JSON/text via `LOG_FORMAT`; `python-json-logger==2.0.7`; nginx `json_access` format + security headers; `main.py` migrado a lifespan + `logger.info()` + CORS env-driven. | v2.04.00 |
| 2026-07-30 | Progressive Disclosure UI añadida como §2.15.d — pendiente | Reunión 29 confirmó que el valor real es el análisis que ningún DBA puede hacer hoy (aggregado por dept/app). Kindy: "We never sell lineage — customers are always disappointed because it didn't solve anything." La UI debe hablar en lenguaje de negocio por defecto, con detalle técnico accesible via drill-down natural (sin switch de modo). Empieza como piloto en Landscape. | Reunión 29 (2026-07-30) |
| 2026-07-20 | §2.16 + §2.9 + §2.15 Architecture Layers implementados en v2.03.00 | Staging Layer: migration `b2c3d4e5f6a7` agrega `import_status`+`validation_warnings` a `snapshot`, crea `staging_table_import`/`staging_column_import`. Pipeline hook en `run_post_ingest_pipeline` llama `validate_import()` → `committed`/`failed`. Integration Model: migration `c3d4e5f6a7b8` agrega `object_entity` (unique on entity_type+object_name) + FK nullable `entity_id` en 4 tablas. `resolve_entities()` wired como último step del pipeline. `backfill_entities.py` para snapshots existentes. APIs `/entity/` + `/landscape/`. Access Layer: nueva página `/landscape` con KPI cards + risk distribution bar + top critical objects. Sidebar entry "Landscape" agregado. | v2.03.00 |

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
