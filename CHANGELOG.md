# SCION Changelog

All notable changes to this project, newest first.
Format follows the existing convention used in the repository.

This file replaces the in-README changelog as of v1.14.04. The
`tools/bump_version.ps1` script writes new entries here.

---

### v1.21.36 (2026-06-24) — fix(col-lineage): filter bottom panel by srcColNames/tgtColNames instead of table_key

Root cause: the overlay's columnLineageMap (built once when overlay toggled on)
can have a partial/stale count of column pairs for a given edge, producing an
"8 cols" label while the fresh columnLineage fetch for the bottom panel sees
more pairs (16 unique source cols vs 8 label). The old filter used table_key
comparison against the full columnLineage data and returned more rows than
the popup showed.

Fix: store srcColNames and tgtColNames in clickedEdge (they are the exact
unique column names used to build the edge popup). Filter columnLineage.columns
by name match against that set — now filtered count == popup label count.

---

### v1.21.35 (2026-06-24) — debug(col-lineage): add snap/total/filtered counts to diagnostic overlay

---

### v1.21.34 (2026-06-24) — debug(col-lineage): add diagnostic overlay to trace srcObjKey/tgtObjKey on edge click

Yellow debug panel inside the edge popup showing `src:`, `tgt:`, `sel:`, and
`filter: ✓/✗` to diagnose why the "8 cols" edge does not filter correctly.
To be removed once root cause is confirmed.

---

### v1.21.33 (2026-06-24) — fix(col-lineage): merge filter into clickedEdge to eliminate race condition

**Definitively fixes "8 cols → unfiltered panel" bug**
The real cause: ReactFlow uses position-based hit testing internally, so
`event.stopPropagation()` does NOT prevent `onNodeClick` from also firing when
clicking an edge near a node. This means `selectedObject` changed, the useEffect
ran, and any separate `activeEdgeFilter` state was cleared.

Fix: remove `activeEdgeFilter` as an independent state. Instead, extend
`clickedEdge` (the popup state) with `srcObjKey` and `tgtObjKey`. Now:
- "popup is open" ↔ "filter is active" — same state, same lifecycle
- Nothing can clear the filter without also closing the popup
- No useEffect race window possible
- `filteredColLineage` reads from `clickedEdge` directly
- "× Clear filter" button closes the popup (setClickedEdge(null))

---

### v1.21.32 (2026-06-24) — fix(col-lineage): survive edge→node click race + bidirectional filter

**Root cause identified and fixed for the "8 cols → unfiltered panel" bug**
When the user clicked a purple col-lineage edge near a node, ReactFlow
could fire both `onEdgeClick` (setting `activeEdgeFilter`) AND `onNodeClick`
(changing `selectedObject`). The `useEffect` watching `selectedObject` then
immediately cleared `activeEdgeFilter`, leaving the popup visible but the
filter null.

Changes:
- `onEdgeClick`: adds `event.stopPropagation()` to prevent the click from
  bubbling to adjacent node handlers.
- `useEffect` on `[snapshotId, selectedObject]`: instead of unconditionally
  clearing `activeEdgeFilter`, it now keeps the filter when `selectedObject`
  navigates to EITHER end of the active edge (src or tgt). Only clears when
  the user moves to an unrelated object.
- `filteredColLineage` / badge: uses `filterIsActive` (true only when
  `selectedObject` is one of the two filter endpoints), so the badge and
  filtered count are never shown for unrelated objects.
- Bonus: filter now works bidirectionally — clicking COMPUTE_V and then
  navigating to COMPUTE_SUM_V keeps the filter active (panel shows upstream
  from COMPUTE_V).

---

### v1.21.30 (2026-06-24) — fix(col-lineage): filter by upstream/downstream table_key (Bug 1 real fix)

**Real fix for the "8 cols → 19 columns" panel mismatch**
The previous approach (v1.21.29) stored source/target column name lists in the
edge data and matched against them. This silently failed when `columnLineageMap`
hadn't loaded yet or when parser-generated `_COL` generic names didn't match
the actual column names in the bottom panel.

New approach: filter `columnLineage.columns` by checking whether each column
has a `downstream` (if selected = source) or `upstream` (if selected = target)
edge whose `table_key` matches the neighbor object of the clicked edge. Uses
data already present in `columnLineage` — no dependency on overlay edge data.

---

### v1.21.29 (2026-06-23) — fix(col-lineage): filter bottom panel to clicked edge pair (Bug 1)

**Column detail panel now filters to the clicked edge**
Clicking a col-lineage edge ("N cols") in the graph now filters the bottom
Column-Level Lineage panel to show only the columns involved in that specific
source→target pair. A purple badge shows the active filter with the neighbor
object name and a "× Clear filter" button. The count updates to "X filtered / Y columns".

Navigating to a different object automatically clears the stale filter.

No schema or API changes.

---

### v1.21.28 (2026-06-22) - Col-lineage: indirect edges + transform icons + step-ID popup

**Three column-lineage enhancements shipped together**
- NOT APPLICABLE rows from the parser now render as an amber "⊿ Indirect impacts" section
  inside each column card (join/filter predicates, not direct column mappings).
- `transformation_type` values map to Unicode glyphs (→ Σ ⊿ ≠ ƒ ⊞ ⊟) shown as
  `TransformBadge` chips with tooltips.
- Clicking a col-lineage edge opens a floating popup inside the graph canvas showing the
  `step_natural_key` (Query/Step ID) for each transformation involved.

Backend: new `IndirectEdge` + `ColumnEdge.step_natural_key` fields in `/api/v1/lineage`.
10 new tests in `test_lineage_indirect.py`, all passing.

---

### v1.21.27 (2026-06-22) - Col-lineage: indirect edges + transform icons + step-ID popup (part 1)

Internal build — superseded by v1.21.28.

---

### v1.21.26 (2026-06-18) - Import: already-imported detection before Import All

**Share scan now warns before a no-op import**
The `/share-import/scan` endpoint now peeks the first record of any dict file to
read `extract_run_id` + `source_system_name`, then cross-checks against existing
snapshots. If a match is found, the response carries `already_imported: true` and
`existing_snapshot_id`.

The frontend renders an amber warning banner ("Already imported — Snapshot #N")
between the file list and the Import All button, so the operator knows the result
before clicking. The backend duplicate-detection is unchanged — re-importing was
already a no-op; this makes it visible upfront.

No schema changes.

---

### v1.21.25 (2026-06-18) - Lineage graph: long object names now truncate correctly

**Node labels no longer overflow the card boundary**
Object names longer than ~22 chars (e.g. `SUBSET_AVAIL_METRICS_MIN_MAX_V`) were
breaking outside the 220px node card. Added `overflow: hidden`,
`text-overflow: ellipsis`, and `white-space: nowrap` to the label div in all three
node types (UpstreamNode, CenterNode, DownstreamNode). Full name still visible on
hover via the browser's native `title` attribute.

No backend changes, no schema changes.

---

### v1.21.24 (2026-06-18) - Fix column lineage duplicate edges

**122 identical edges per logical mapping reduced to 1**
The DataDNA parser stores one row in `attribute_lineage` per SQL step processed,
so the same column→column mapping can appear 122+ times (e.g.
`SUBSET_AVAIL_FINAL_MIN_V` showed 1,464 edges instead of ~11). The
`/lineage/columns` endpoint now deduplicates by `(source_key, target_key)` pair
using per-column dicts rather than lists. `total_edges` in the response now
reflects unique mappings.

The duplication in the DB is intentional — the parser preserves step-level
granularity for audit traceability. Deduplication happens at the API layer only.

No schema changes.

---

### v1.21.23 (2026-06-18) - Column view toggle in lineage graph

**Column strips and "N cols" edges in the graph**
A "Column view" pill button in the Lineage graph controls row now toggles column
mode. When active:
- All visible nodes expand to show their column names as purple dot pills (max 7,
  "+N more" overflow).
- Edges between tables that share column-level lineage are grouped and drawn as
  purple dashed lines with a compact "N cols" badge.
- Table-to-table edges are dimmed (opacity 0.3) to keep the column edges legible.
- Node heights are recomputed dynamically via dagre so the layout stays clean.

Also in this release:
- Descriptive intro text added below the Column-Level Lineage section title
  ("Column-level lineage shows, for each column in this object, which upstream
  columns feed it (SOURCES) and which downstream columns it feeds (FEEDS INTO).")
- Column edge labels changed from verbose text to compact "N cols" badge to
  eliminate the overlap/overlap problem seen in earlier screenshots.

No schema changes.

---

### v1.21.22 (2026-06-18) - Column-Level Lineage: new endpoint and panel

**Column-to-column lineage surfaced for the first time**
New `/api/v1/lineage/columns?snapshot_id=N&object=SCHEMA.TABLE` endpoint queries
the `attribute_lineage` table (populated by the DataDNA parser, Tier 1/2) and
returns per-column upstream/downstream edge lists. Groups results by column and
separates SOURCES (things that feed this column) from FEEDS INTO (things this
column feeds), with `transformation_type` and `expression` on each edge.

New full-width **Column-Level Lineage** panel at the bottom of the Lineage page
(visible when an object is selected). Shows a grid of per-column cards — each
card has a dark header, a red SOURCES section, and a green FEEDS INTO section
with colored transformation badges.

Backend changes: new file `backend/app/api/v1/lineage.py`; registered in
`backend/app/api/v1/__init__.py`.

No schema changes.

---

### v1.21.21 (2026-06-18) - Add per-change filter to impact screen

**Per-change drill-down now has a search box**
Section 4 (Per-change drill-down) on the Impact page now has a text filter
above the table. Typing any substring (e.g. `td.my_view` or just `td`)
instantly narrows the visible rows client-side. A `3 / 2302` counter shows
how many rows match. The filter resets automatically on each new analysis.

No backend changes, no schema changes.

---

### v1.21.20 (2026-06-18) - Fix case-sensitivity in graph, diff linker, usage and timeline

**Four case-insensitive fixes across the backend**

- **Graph focus resolver** (`api/v1/graph.py`): root-node lookup now uses
  `func.lower()` on both `schema_name` and `object_name`, so navigating to
  `td.my_view` and `TD.MY_VIEW` resolve to the same node.
- **Graph diff linker** (`graph/graph_diff_linker.py`): ChangeEvent → GraphNode
  key matching now lowercases both sides. Previously a dict-snapshot node stored
  as `"TD.my_view"` would not link to a change event whose identifier arrived as
  `"td.my_view"` from PDCR, silently zeroing out its impact count.
- **Usage criticality lookup** (`api/v1/usage.py`): `ObjectCriticality` is now
  queried with `func.lower(object_name) == qualified.lower()` to match across
  mixed-case object names.
- **Timeline** (`api/v1/timeline.py`): replaced `==` and `.contains()` (both
  case-sensitive in SQLite) with `.ilike()` for object_identifier filtering.

No schema changes.

---

### v1.21.19 (2026-06-17) - Fix PDCR orphan lookup

**PDCR object_usage rows now resolve correctly**
`build_node_index` in `pdcr_persister.py` was building lookup keys from
the raw `graph_node.object_name` column, which `graph_builder.py` stores
as the *qualified* name `"schema.table"`. PDCR records carry only the
bare `table_name`, so every lookup was a miss — 100% orphan rate.

Fixed by stripping the schema prefix from `object_name` when building the
in-memory index: `"UAT_NFL_COR_TED_TBL.my_table"` → key `"my_table"`,
which matches the PDCR `table_name` field. The correction is a one-liner
in `build_node_index`; no schema changes.

No schema changes.

---

### v1.21.18 (2026-06-17) - Share import progress + impact traversal indexes

**Share import progress restored**
`Import from Share` now reuses the existing dictionary import progress panel
instead of leaving the operator on a grey `Importing...` button. The frontend
generates the same `import_id`, stores it in session storage, opens the
`DictImportProgress` panel, and polls the existing `/dict-import/{id}/progress`
channel while the server reads files directly from the mounted share.

The backend now accepts that `import_id` on `/share-import`, passes it into the
dict-import pipeline, and only marks the progress complete after optional
lineage attachment has finished.

**Impact summary performance**
Added composite traversal indexes on `graph_edge(snapshot_id, source_node_id)`
and `graph_edge(snapshot_id, target_node_id)`. These match the recursive
upstream/downstream impact walks used during post-ingest impact summary
generation. On the Transcend-DevTest full extract this reduced the observed
post-ingest time from roughly 38 minutes to roughly 7 minutes.

**Lineage attach metadata fix**
Parser lineage attached to an existing dictionary snapshot no longer overwrites
the snapshot's dictionary `object_count` with the smaller parser payload count.

**Schema**
Adds Alembic revision `c5f8a2b7d901` for the new graph-edge traversal indexes.
The same migration also backfills the missing `ix_change_event_snapshot_to`
index on fresh Alembic-created databases so Alembic and ORM metadata stay in
sync.

---

### v1.21.17 (2026-06-17) - Share import startup hotfix

**Backend startup fix**
Added the missing `Optional` import in `share_import.py`. FastAPI/Pydantic
resolves endpoint annotations at application startup, so the v1.21.16 backend
image failed to boot when registering `/share-import/scan`.

No schema changes.

---

### v1.21.16 (2026-06-17) - Unified share import + AI test pack

**Snapshots: one production import path**
The Snapshots toolbar now keeps the production path focused on **Import from
Share** and leaves **Capture Live Snapshot** as the demo/local option. The old
standalone dict-batch and parser-import buttons were removed from the primary
toolbar because the share flow now covers dictionary, PDCR Object Usage, and
lineage together.

**Share import: server path override and manual file picker**
The share import panel now has two modes:

- **From server share** scans the mounted server path, defaulting to
  `SCION_SHARE_MOUNT_PATH`, with an editable override for alternate mount
  locations.
- **Manual file picker** lets the user choose `.dat` and `.json` files from any
  local or network folder. Dictionary/PDCR files create the snapshot first, and
  lineage JSON is attached to the same snapshot when available.

The backend exposes `/share-import/scan?path=...` and
`/share-import?force=false&path=...`, and parser lineage import can now accept
`snapshot_id` to attach lineage to an existing dictionary snapshot instead of
creating a separate parser snapshot.

**Share notifications**
Added a notification bell and `/notifications/share` endpoint so operators can
see when new files are available in the mounted share.

**AI-assisted integration test pack**
Added a SCION use-case document and an AI-assisted test suite scaffold with 29
test objects / 12 test types, covering ingest, diff, lineage, impact, usage,
criticality, and health checks.

---

### v1.21.15 (2026-06-16) — Self-referencing lineage visible in side panels

**Lineage: self-referencing tables now shown in "Where data comes from" / "Where data goes"**
Tables with `INSERT INTO T SELECT … FROM T` patterns (same table as both source
and target) now appear in both side panels with an amber *(self-referencing)* badge.
Previously these edges were deleted from the DB and invisible to users.

The dagre graph continues to exclude self-loop edges (to prevent layout crashes),
but they are preserved in the database and surfaced in the list panels. The noise
filter no longer drops self-loop dataset lineage edges during ingestion.

Self-loop edges were also restored in snapshots #2 and #4 via a one-time DB patch
(47 + 2 edges re-inserted).

---

### v1.21.14 (2026-06-10) — Fix lineage edges for UNKNOWN-schema datasets

**Ingestor: resolve UNKNOWN-schema references against known nodes**
The parser emits `UNKNOWN.<Name>` when it cannot infer the database context
for a dataset reference in a SQL statement. Previously these datasets were
dropped by the noise filter (correct) but the corresponding lineage edge was
also lost — the object would exist in the graph with no downstream links even
though the relationship was captured at attribute level.

New step 6.5 in the ingestor scans `attribute_lineage` for edges that touch
an `UNKNOWN.<Name>` endpoint and resolves the name against existing graph nodes
in the same snapshot. If exactly one node with that bare name exists (unambiguous
resolution), the `graph_edge` is emitted. Ambiguous names (same table in multiple
schemas) are skipped — better to show nothing than to show the wrong link.

This fixes the missing `BATCH_CREATE_UPDATE_V → COMPONENTDISCOVERY_STATE` edge
and the 4 other downstream objects in snapshot #4 that had the same issue.

---

### v1.21.13 (2026-06-09) — Intelligence cochange fast-exit + volatility-trend response cap

**cochange fast-exit on mass-refresh data**
Added COUNT(*) pre-filter per snapshot pair before loading rows. If every
pair has more raw changes than `max_basket_size`, the endpoint returns
immediately (0 pairs, <200 ms) without fetching 1.86M rows.

**volatility-trend top_n cap (default 200)**
With 10,877 schemas in production, the endpoint was returning a 6 MB JSON
response and spending ~3s on serialization. Added `top_n=200` parameter
that returns only the most actionable schemas (worsening + highest
current_volatility), reducing response from 6 MB to ~120 KB.

---

### v1.21.12 (2026-06-09) — Intelligence cochange + volatility-trend perf fix

**cochange and volatility-trend endpoints unblocked (#60 follow-up)**

Two additional performance issues on production data with 1.86M change_event rows:

1. **cochange infinite loop**: `combinations(N, 2)` on baskets of 245k+ objects
   = ~30 billion pairs → the endpoint never returned. Root cause: production
   deltas are mass-refresh events (full schema reloads) where every object
   changes at once. Fixed with `max_basket_size=500`: transactions where a
   single delta touches more than 500 unique table-level objects are skipped
   as "noisy" (they don't generate actionable co-change signal). Returns 0
   pairs when all deltas are mass-refreshes, which is the honest answer.

2. **volatility-trend loading 1.86M rows**: The bulk `SELECT * FROM change_event
   WHERE snapshot_to IN (...)` loaded all change rows into Python memory for
   string splitting/counting — several seconds just for the I/O. Replaced with
   a SQL GROUP BY aggregate that extracts schema name and collapses columns to
   parent tables server-side using SUBSTR/INSTR. Also replaced the
   `table_snapshot.schema_id IN (37k_ids)` large-IN query with a JOIN-based
   aggregate. Both queries now complete in <200 ms.

---

### v1.21.11 (2026-06-09) — Intelligence screen performance fix

**Intelligence screen 87s → <2s (#60)**
The Governance Report (Intelligence) screen was timing out (502 Bad Gateway)
on production data with 1.86M `change_event` rows. Root causes:

1. `domain_risk_index` loaded all ~252K `ChangeEvent` ORM objects into Python
   memory per request (SQLAlchemy ORM overhead: ~80 s). Replaced with a single
   SQL GROUP BY + SUBSTR aggregate that returns one row per schema.
2. The two COUNT queries in `governance_scorecard` each triggered a full table
   scan because the existing index `ix_change_event_snapshot_pair(snapshot_from,
   snapshot_to)` cannot service queries that filter only on `snapshot_to`.
   Added new index `ix_change_event_snapshot_to` to `change_event` — COUNT now
   runs in 15 ms instead of 2.4 s.
3. Combined the two separate COUNT/COUNT(is_breaking) queries into a single
   `COUNT + SUM(CASE …)` round-trip.

Total scorecard latency on snapshot with 252K change events: ~1.5 s (was >87 s).

---

### v1.21.10 (2026-06-09) — Lineage self-loop fix + edge deduplication + no-lineage UX

Three fixes from Ashish/Rahul integration testing (snapshot #4):

**Self-loop edges filtered at ingestion (#59)**
The parser emits edges where source == target for queries that read and
write the same table (e.g. `INSERT INTO T SELECT … FROM T`). These
self-loops were stored in `graph_edge` and caused the dagre layout to
crash or produce a blank graph when the focused object had one.
Fixed in `noise_filter.py`: self-loops are now dropped during ingestion
with a dedicated sample counter (`dataset_lineage_self_loop`).
Belt-and-suspenders guard also added in the frontend BFS so existing
snapshots imported before this fix also render correctly.

**Duplicate edges deduplicated at ingestion (#59)**
The parser emits one lineage edge per SQL step that uses a relationship,
so the same (source, target) pair appeared up to 196× in the DB for
high-traffic tables. The ingestor now tracks seen (source_node_id,
target_node_id) pairs per snapshot and skips duplicates, keeping only
the first occurrence. This reduces edge count significantly on real
Transcend-scale extracts and improves BFS performance.

**Clear UX when object has no lineage (#59)**
When an object exists in a snapshot but the parser captured no edges for
it, the lineage page previously showed a confusing blank canvas. It now
shows an amber info banner explaining that no relationships were recorded
for that object and why this can happen (standalone INSERT targets, out-
of-scope SQL, etc.).

---

### v1.21.9 (2026-06-03) — PDCR counter fix + Rahul testing bugs + import persistence

Three improvements from the first round of end-user testing with Rahul's team:

**PDCR usage counter mapping corrected (#55)**
Rahul confirmed the real field semantics (email 2026-06-02 / 8 May
README). The original mapping was provisional and wrong: we were using
FreqofUse as query_count and TypeOfUse as user_count. Now correctly:
- QueryCount → query_count, DistinctUserCount → user_count
- target_indicator is Y/N string (not numeric)
- object_num replaces the misnamed data_size
- DBQL (pdcr_log) ingestion disabled: Rahul confirmed DataDNA isn't
  joining against sql_text near-term; the reader and dbql_query table
  stay dormant (flip INGEST_DBQL = True to re-enable).
- object_usage idempotency: re-uploading the same file now produces
  skipped_duplicate instead of inserting duplicate rows.

**Four bugs from Rahul's R11 testing session (#56)**
- Lineage blocked after "Object not found" error: changing snapshot
  now resets the error and object state cleanly.
- Network error clicking downstream node: switched Promise.all to
  Promise.allSettled for the two directed BFS fetches so a failure
  in one direction doesn't kill the other.
- Usage filter not applied: section subtitles now explain the tables
  are the global ranking and point to the Object drill-down card.
- Visual Diff table count misleading: "(M of N tables changed)"
  instead of the confusing "(N tables, M changed)".

**Import progress survives page navigation (#57)**
Persists the active import_id in sessionStorage. Navigating away from
Snapshots and returning now automatically reopens the panel and
resumes the progress checklist via server-side polling.

No schema changes. Frontend tsc + eslint clean; backend 119 tests pass.

### v1.21.8 (2026-06-03) — Lineage navigation + usage drill-down + "Breaking" clarity

Reunion 11 (cross-team demo) follow-ups. Four UI/UX improvements that
make the structural-intelligence pages usable on real customer-scale
data and clearer for end-user testers:

- **Lineage: click-to-expand fix (#51).** Clicking a node in the
  Lineage diagram did nothing — the `<ReactFlow>` had no `onNodeClick`,
  even though the copy promised "click any node to jump to its lineage".
  Wired it to re-focus, mirroring the Graph page.
- **Lineage: depth control + direction filter + directed walk (#52).**
  A 1–5 hop depth stepper (reveal the graph step by step) and a
  Both/Upstream/Downstream filter. "Both" now does two *directed*
  fetches (up + down) and unions them instead of one undirected BFS —
  the undirected walk pulled in an upstream hub's siblings, flooding
  the 300-node cap with a spurious "too big" warning while only a
  couple of relevant nodes rendered. Also fixed a doubled identifier
  (`schema.schema.object`) coming from the objects-search endpoint and
  the node-click handler.
- **Usage: per-object drill-down (#53).** New
  `GET /usage/object/{snapshot_id}?object=Y` returns one object's full
  usage + criticality profile (resolves any object, even outside the
  top-N rankings; case-insensitive qualified/bare matching). The Usage
  page gained a drill-down card (queries, distinct users, last
  accessed, criticality, "View lineage" link), clickable rows, and a
  column→parent-table redirect mirroring Lineage. The Changes "Usage"
  button now focuses the object instead of opening the global screen.
- **"Breaking" clarity (#54).** Kept the standard "Breaking" label but
  made it self-explanatory after testers didn't know what it meant or
  what to do. Centralised the vocabulary and added an object-specific
  reason — e.g. "This column was removed (was VARCHAR(11)). Any view,
  report, or query that selects it will fail." — plus the expected
  tester action, surfaced on the Changes and Impact badges/headers.

No schema changes; no migrations. Frontend tsc + eslint clean; backend
117 tests pass.

### v1.21.7 (2026-05-31) — dev.ps1 brings schema to HEAD before launch

Bug fix surfaced while testing Pipeline 3 on a real Transcend
extract: uploading the 8-file batch (dict + PDCR) failed mid-import
with `sqlite3.OperationalError: no such table: dbql_query`.

Root cause: the FastAPI startup hook only verifies DB connectivity —
it never runs migrations. The Docker `entrypoint.sh` brings the
schema to HEAD via `db_init.py init`, but the local dev launcher
`dev.ps1` did not. So pulling code that adds a migration (here,
Pipeline 3's `dbql_query` table at revision b49e5f6c7d8e) left the
running DB one revision behind, and the first request to touch the
new table died.

Fix: `dev.ps1` now runs `backend/tools/db_init.py init` before
launching uvicorn when the DB file exists — the same idempotent
step the Docker entrypoint already runs (no-op when already at
HEAD, fails loudly on a legacy/inconsistent DB). Local dev and
container deploys now share one schema-upgrade contract.

No backend code changed; no migration added. Existing local DBs are
upgraded automatically on the next `dev.ps1` run.

### v1.21.6 (2026-05-29) — Pipeline 3: PDCR usage ingest end-to-end

Closes the planned-since-v1.0 gap on FR-1.3: SCION now ingests
Rahul's PDCR usage extracts (`pdcr_log_*.dat`,
`pdcr_object_usage_*.dat`) through the same `/dict-import` endpoint
that handles the 6 dictionary files. Six PRs landed in sequence:

- **PR-A (#43) — format detector.** Recognises PDCR layouts by
  ENDREC-aware arity counting: arity 10 → `USAGE_DBQL`, arity 12 →
  `USAGE_OBJECT`. Filename prefixes `pdcr_log_` and
  `pdcr_object_usage_` boost confidence to HIGH. Fixed a regression
  in `test_flat_file_unexpected_arity_returns_unknown` along the way.
- **PR-B (#44) — readers.** `iter_dbql_log` / `read_dbql_log` and
  `iter_object_usage` / `read_object_usage` in a new
  `app/metadata/pdcr_flat_file_reader.py`. Reuses the byte-level
  helpers from the dict reader (`_split_records`, `_split_fields`,
  `_parse_int`, `_nn`). Includes `reassemble_query()` that joins
  per-(QueryID, SqlRowNo) fragments back into full SQL — needed
  because SqlTextInfo carries multi-line statements.
- **PR-C (#45) — persisters + dbql_query table.** New
  `DBQLQuery` ORM model and Alembic migration
  `b49e5f6c7d8e_add_dbql_query_table.py` (idempotent, snapshot-
  independent, natural key `(query_id, collect_timestamp)`).
  `persist_dbql_log` reassembles SQL and writes one row per query;
  `persist_object_usage` maps 6 PDCR types to SCION vocabulary
  (`Col`→COLUMN, `Tab`→TABLE, `Viw`→VIEW, `Idx`→INDEX,
  `Mac`→MACRO, `Vol`→VOLATILE) and case-insensitively resolves
  identifiers against `graph_node` via `build_node_index`. 14 PDCR
  types skipped explicitly with per-type counters (FR-13
  graceful out-of-scope). End-to-end on the 2026-05-28 Transcend
  extract: 44 540 DBQL queries + 77 619 / 78 049 (99.45%) usage
  rows persisted.
- **PR-D (#46) — endpoint routing.** `/dict-import` partitions
  uploaded files into dict vs PDCR buckets by detected content
  type. Dict files flow through the existing snapshot pipeline
  untouched; PDCR files persist in their own session/transaction
  so a PDCR failure can't roll back the dict snapshot.
  `DictImportResponse` grows 9 optional fields (all default
  zero/empty) so dict-only clients see the same shape they always
  did. New `persist_pdcr` step in `DICT_IMPORT_STEPS` for UI
  progress.
- **PR-E (#47) — usage-weighted criticality.** After PDCR
  object_usage lands, re-runs `compute_criticality(force=True,
  usage_available=True)` so the cache reflects the 60/40 usage +
  graph fragility formula instead of the graph-only fallback the
  post-ingest pipeline writes. Gated on `obj_result.inserted > 0`;
  best-effort (failures logged, not fatal). Response surfaces the
  new HIGH/MEDIUM/LOW band counts.
- **PR-F (this one) — SPEC.md.** FR-1.3 moved from "planned" to
  "implemented (Pipeline 3, v1.21.6)"; FR-1.4 step 6 documents
  the two-pass criticality flow; data model inventory updated to
  20 tables (added `dbql_query`); §1.4 scope-boundary table
  reflects PDCR ingest landed; DataDNA boundary mnemonic updated
  to mention the QueryID correlation point.

Tests: 117 passed across the backend suite (+17 persister, +7 +1
endpoint-routing, +regression fix in format detector). Schema-
parity test still green: `Base.metadata.create_all()` produces a
schema identical to `alembic upgrade head`.

What's still open (post-Pipeline-3):

- `usage_event` has no unique key today, so re-uploading the same
  `pdcr_object_usage_*.dat` double-counts. Deferred to v1.22.
- `dbql_query` retention strategy not finalised (Rahul to confirm
  whether SCION keeps the full DBQL history or rolls daily).
- Object-type coverage: adding UDF + SP to the mapping would
  recover ~76 rows / 0.1% extra coverage on Transcend-scale data —
  not blocking, tracked in the persister docstring.

### v1.21.5 (2026-05-18) — partitioningconstraintsv 9-col + ENDREC layout fix

Helton Guedes landed two changes:

- **Reader fix.** `partitioningconstraintsv` was failing on the new
  Transcend exporter output because the `constraint_text` field can
  contain embedded newlines, breaking the standard 16-col `\n`-
  terminated layout. Realigned to the same 9-col + `ENDREC`
  terminator pattern that `tabletextv` already uses. Batches from
  2026-05-15 and 2026-05-26 now process cleanly; the 2026-05-21
  batch that arrived without `ENDREC` was reported back to the
  extraction team.
- **`tools/validate_only.py`.** Standalone pre-flight validator
  that reuses the official backend readers (`dict_flat_file_reader`,
  `dict_batch_validator`, `teradata_parser`) to verify files before
  upload without touching the DB. Emits TXT + JSON reports next to
  the files; multilingual (pt-br / es / en); covers the 6
  dictionary files + the parser-lineage JSON + heuristic checks
  for DBQL / Object Usage. Caught the 2026-05-21 layout regression
  exactly as designed.

Fixture and test alignment for the new partitioning layout shipped
separately in PR #38.

---

### v1.21.4 (2026-05-06) — security release: ~165 CVEs eliminated

Three Docker Scout scans surfaced an unmanageable backlog of
inherited CVEs (4 Critical, 16 High, plus tail) across backend,
frontend, and nginx, mostly from stale base layers and one
unmaintained sidecar. Cleared the whole pile in one cut.

- **Backend.** `apt-get upgrade -y` added in both build and runtime
  stages of `docker/backend.Dockerfile` so Debian patches roll in
  on every release rather than waiting for a base-image bump.
  Bumped `fastapi 0.115.0 → 0.115.6` to pull in `starlette ≥0.41`
  (fixes CVE-2024-47874, multipart DoS, HIGH).
- **Frontend.** `npm audit fix` cleared the axios CVE cluster.
  Added `overrides` block in `package.json` forcing
  `picomatch ≥4.0.4`, `brace-expansion ≥2.0.3`, `ip-address ≥10.1.1`,
  `postcss ≥8.5.10` so transitive deps land on patched versions.
  `npm audit` now reports zero vulnerabilities.
- **Infra.** nginx pinned tag bumped `1.27-alpine → 1.29-alpine`.
  The 1.27 pin had not been rebuilt by upstream in ~12 months and
  had accumulated 79 OS-level CVEs (3 Critical, 13 High); 1.29 is
  actively maintained.
- **Watchtower removed.** The `beatkind/watchtower` fork had also
  gone stale (31 CVEs including 1 Critical, all from old Go
  stdlib), and the auto-update only saved ~3 s vs running
  `update.ps1` / `update.sh` manually. Also dropped the
  `docker.sock` mount, which was a root-equivalent attack surface.
  Users now upgrade explicitly when the Sidebar version pill
  shows an update is available.
- **CI.** `publish-images.yml` now passes `pull: true` to
  `docker/build-push-action` so base layers are always re-fetched.
  New workflow `security-scan.yml` runs Docker Scout against the
  published images monthly (1st of every month, 09:00 UTC) and on
  demand, surfacing HIGH/CRITICAL findings without rebuilding.

---

### v1.21.3 (2026-05-06) — TAISA context bounds + scrub vendor name from public surface

Two fixes to the assistant and the deploy surface.

- **TAISA context overflow.** On Transcend-class data (10 716
  schemas) the `_build_scion_context` helper was emitting one line
  per schema in the EDW INVENTORY section unconditionally
  (~500 KB), plus listing every table when the question contained
  common words like *"what"*. Result: TAISA appeared to hang on
  every other question. Fixes: top-30 schemas in the always-on
  inventory, 25 schemas × 40 tables in the on-demand expansion,
  and a defensive 80 000-char total cap on the assembled context
  right before the LLM call. Measured: context dropped from
  363 KB → 48 KB on inventory questions, 328 KB → 13 KB on impact
  questions.
- **Public surface cleanup.** Removed `AI_PROVIDER`,
  `GROQ_API_KEY`, `GROQ_MODEL` env vars from `docker-compose.yml`
  and `.env.example` — TAISA config is baked into the backend
  image via `taisa_llm.yaml`, no runtime injection needed. Sweep
  removed all user-visible mentions of the upstream LLM vendor's
  name from installer prompts, scripts, and README.

---

### v1.21.2 (2026-05-06) — fix dockerised frontend backend connection

The v1.21.0 frontend image was built with the wrong env var name
(`NEXT_PUBLIC_API_URL` instead of `NEXT_PUBLIC_API_BASE_URL`) baked
into the standalone bundle. Since Next.js bakes `NEXT_PUBLIC_*`
vars at build time, the dockerised frontend always fell back to
the dev default `http://localhost:8000` and surfaced
*"Cannot connect to backend API"* on every page. Fix is build-time:
rename ARG + ENV in `docker/frontend.Dockerfile`, fix the build-arg
in `publish-images.yml`, fix the compose env vars in both repos.
Re-publishing produced a working frontend image.

---

### v1.21.1 (2026-05-06) — fix /metrics page hang on large snapshots

The `/api/v1/metrics/snapshot/{id}` endpoint was recomputing the
SHA-256 `structural_hash` from scratch on every call — streaming
all columns of the snapshot through hashlib. That's ~9.8M rows for
a Transcend-class snapshot, costing 30-60 s per call. The
Structural Metrics page fetches metrics for every snapshot in
series, so one slow recompute blocked the loading skeletons of
every snapshot fetched after it, and the page never finished
loading when any large snapshot was present.

`Snapshot.structural_hash` is already persisted at ingest time.
The endpoint now reads that column and only falls back to
recomputing + persisting when the value is NULL (legacy snapshots
ingested before the column existed).

Measured on demo + Transcend:

```
snap  1 (demo, ~600 cols)         0.16 s   was ~0.5 s
snap  5 (demo, ~600 cols)         0.09 s   was ~0.5 s
snap 10 (demo, ~600 cols)         0.13 s   was ~0.5 s
snap 11 (Transcend, 9.8M cols)    0.76 s   was ~30-60 s
```

---

### v1.21.0 (2026-05-06) — containerised deploy + one-liner installer + version banner

End-to-end Docker stack so SCION can be deployed on a fresh Linux
VM with a single `curl … | bash` command. Companion installer
`install.ps1` ships for Windows / Docker Desktop machines used by
the early testers. Confirmed in Reunion 9 that the deploy targets
are 8c/32GB CloudBolt for test environments and 8c/64GB Azure AKS
for the eventual production tier.

Three image-layer artefacts:

- `ghcr.io/guillealbella/scion-backend` — FastAPI + uvicorn,
  multi-stage Python 3.12-slim, ~350 MB. Idempotent `db_init.py
  init` runs in the entrypoint before uvicorn so fresh / managed /
  legacy DB states all converge to head.
- `ghcr.io/guillealbella/scion-frontend` — Next.js standalone
  build on `node:22-alpine`, ~285 MB.
- `nginx:1.27-alpine` — single public port; routes `/api/*` to the
  backend and everything else to the frontend.

Companion repo: a new **`GuilleAlbella/scion-deploy`** (public)
holds `docker-compose.yml`, `nginx.conf`, `.env.example`, and the
six installer / updater / uninstaller scripts. The application
source stays in the private SCION repo; the deploy artefacts are
public so the one-liner doesn't need authentication.

Read-only **version banner** added to the Sidebar footer:
`/api/v1/system/version` compares the local `APP_VERSION` against
the GitHub Releases API and the pill goes green when an upgrade is
available. The actual upgrade is user-driven (`update.sh` /
`update.ps1`) — the in-app "Update now" button arrives in v1.22.

Decisions worth recording for later readers:

- Compose project name pinned to `scion` so the named volume lands
  as `scion_data` (not `proyectokalido-lite_scion-data`) regardless
  of the parent directory's name.
- Watchtower introduced as a sidecar to auto-pull new images every
  6 h. **This was removed in v1.21.4** when the security cost was
  reassessed — the v1.21.0 design intent was "set and forget", the
  v1.21.4 conclusion was "let users opt in explicitly".
- `/system/version` is the only `/api/v1/*` route that is not
  gated by `X-API-Key`. The pill needs to render before the user
  authenticates and is also useful as an uptime probe.

---

### v1.20.00 (2026-05-05) — /graph: click-to-expand interactive subgraph exploration

The previous releases focused on making the graph readable at scale.
This one makes it explorable: from any rendered node the user can
pull one hop of neighbours (upstream / downstream / both) and merge
them into the current view, then keep going from a newly visible
neighbour. No page reload, no re-fetch of the whole graph.

#### What it does

- The node-detail side panel now opens with a small **Expand
  neighbours** tray at the top: three buttons (``Upstream``,
  ``Downstream``, ``Both``) that fire a ``GET /graph/focus`` around
  the selected node with ``hops=1``. The result is merged into the
  rendered subgraph. Dagre re-runs over the merged set so the layout
  stays sensible.
- Already-expanded nodes get a **thicker border + green ✓ EXPANDED
  badge** so the user can tell at a glance which roots have been
  pulled. Re-clicking is a safe no-op (server returns the same
  neighbours, the merge dedupes by ``node_id``).
- A green banner above the graph shows the running count of
  expansions and exposes a single **Clear expansions** button to
  revert to the original subgraph in one click.
- Snapshot change OR focus-anchor change wipes the expansion state
  automatically — anchoring expansions to one snapshot guarantees
  that a stale node from another can't silently 404 mid-walk.

#### Why it's useful

The pre-existing ``hops`` slider gave you the whole N-hop
neighbourhood at once, which becomes unreadable past 100 nodes. This
flow is the opposite shape: start tiny, follow the threads you
actually care about. Same backend (``/graph/focus``) under the hood,
no new endpoint.

#### Implementation notes

- Pure frontend change. Backend wasn't touched.
- Merge state lives in three pieces: ``expandedNodes:
  Map<node_id, GN>``, ``expandedEdges: GraphEdge[]``,
  ``expandedRoots: Set<node_id>``. The render pipeline merges them
  into ``baseRenderSource`` (which is whatever ``focusData`` /
  ``graphData`` last returned) inside a memo, so the original
  responses stay immutable.
- Edge dedup uses ``source|target|type``. Node dedup uses
  ``node_id``. Base rows always win on conflict — they carry metrics
  (in/out degree, fragility, hub flag) the focus-fetch occasionally
  omits.
- Direction handling: schema / database nodes don't have a parent
  schema, so for those types the root identifier passed to
  ``/graph/focus`` is bare ``object_name`` rather than
  ``schema.object_name``. Mirrors the resolver fallback the backend
  already supports.

---

### v1.19.00 (2026-05-05) — Round-trip scale audit: /impact paginated, /alerts pre-computed, /usage cached, /intelligence windowed, /simulation autocomplete, /lineage route fix

The previous releases (v1.15.00–v1.18.00) closed the headline scale
bugs one page at a time. This release is the systematic follow-up:
audit every remaining page that still touched a full snapshot's worth
of rows, and convert it to the same patterns we proved out in earlier
PRs — pre-aggregation in post-ingest, server-side bucket counts,
paginated endpoints, top-N reads with indexed scans, server-backed
autocomplete.

#### /impact

- **``POST /impact/batch`` is paginated.** Request accepts ``limit``
  (default 100, max 500) and ``offset``. ``changes`` is now the
  current page; ``changes_analyzed`` reflects the FULL filtered set;
  ``has_more`` drives the UI's "Load more" affordance. Mirrors the
  pattern landed in v1.16.00 for ``/diff/details``.

- **Server-side donut buckets.** ``summary`` now carries
  ``by_severity``, ``by_change_type``, ``by_schema``, ``by_breaking``,
  and ``total_query_count`` — all computed during the same per-change
  loop that already runs, at zero extra cost. The frontend stops
  iterating ``changes`` to build donut data (which froze the browser
  at 250k rows on Transcend); donuts read directly from the summary
  and stay accurate regardless of pagination state.

- **``affected_databases`` pre-grouped.** ``BlastRadius`` now exposes
  ``[{schema_name, tables: [...]}, ...]`` alongside the legacy flat
  arrays, so the "Affected objects, by database" section doesn't
  filter ``affected_tables`` once per schema — at 10k databases that
  was visibly slow.

- **Frontend rewrite.** Page consumes paginated ``items`` with a Load
  More button, reads donut buckets directly from ``summary``, and
  the legacy 4 client-side ``useMemo`` aggregations are gone. The
  "Touched databases" inline banner is capped at 10 chips with a
  ``+ N more`` overflow; the detail "Affected objects, by database"
  section is a search-driven accordion (top 50 by table count, type
  to filter past the cap, click to expand the per-database table
  list). The ``By database`` donut is capped at top 12 + an ``Other
  (N databases)`` slice — donuts past ~15 categories become
  unreadable.

#### /alerts

- **New ``proactive_alert`` table** (alembic ``a38d4e5f6c7d``). The
  three structural checks (broken lineage, orphan objects, hub-node
  changes) used to load every ``graph_node`` + ``graph_edge`` for the
  latest snapshot on every request — 337k+ rows on Transcend, walked
  in Python. They now run ONCE during ``run_post_ingest_pipeline``
  and persist to this table. Endpoint reads indexed rows. Lazy
  backfill on first request for legacy snapshots that predate the
  hook.

#### /usage

- **``/criticality/{snapshot_id}`` reads top-N via SQL.** New
  ``limit`` param (default 100, max 500). The cache-hit fast path
  now uses an indexed ``LIMIT`` query (the
  ``ix_object_criticality_snapshot_score`` composite added in
  v1.15.00) instead of materialising the full 337k-row criticality
  table. Counts (``total``, ``high_count`` etc.) come from a single
  ``GROUP BY`` query so KPIs stay accurate without scanning all
  rows. Cache-miss path falls through to the legacy
  ``compute_criticality`` (rare in v1.19+ because post-ingest always
  populates the cache).

#### /intelligence

- **History window caps on cochange and volatility-trend.**
  ``mine_cochange_pairs`` and ``compute_schema_volatility_trend``
  used to scan the entire ``change_event`` table on every request —
  fine on a demo, multi-second on Transcend. Both helpers now
  accept ``max_history_pairs`` / ``max_history_snapshots`` (default
  20) and use a pre-flight pair selection + indexed ``IN`` filter
  to bound the scan. The ``(snapshot_from, snapshot_to)`` index from
  v1.15.00 makes this cheap.

#### /simulation (formerly /what-if)

- **Server-backed object autocomplete.** Page used to call
  ``useGraph(snapshot_id)`` to populate the target picker — but
  ``/graph/{snapshot_id}`` returns ``truncated: true`` with empty
  nodes/edges above the v1.17 soft cap, so the dropdown was just
  empty on Transcend. Replaced with ``<ObjectAutocomplete
  source="graph" objectTypes="TABLE,VIEW">`` — types-restricted
  server search via the ``/objects/search`` endpoint added in
  v1.16.00. Picker is instant on any snapshot regardless of size.

- **``/objects/search`` accepts ``object_types``.** New query
  param, comma-separated, applies only when ``source=graph``.
  Hooks into the existing
  ``ix_graph_node_search`` composite index.

#### /lineage (Transcend regression hot-fix)

- **Route order in ``backend/app/api/v1/graph.py`` was wrong.** The
  ``/{snapshot_id}`` parametrised route was declared before the
  static ``/focus`` route added in v1.17.00. FastAPI matches in
  source order, so ``GET /graph/focus`` was being routed to
  ``get_graph`` which tried to parse the literal string ``"focus"``
  as ``int snapshot_id`` and rejected it with 422. Worked on the
  demo because the demo never hit ``/focus`` (small graphs use the
  full-graph endpoint). The Transcend lineage flow exposed it on
  the first picker click. Static route now declared first.

#### Caveats

- ``/impact`` numbers (``Impacted objects``, ``Max depth``,
  ``Weighted score``) are 0 on Transcend dict imports because the
  graph's edge set is sparse (the FK heuristic in ``graph_builder``
  needs column-naming conventions to infer ``FEEDS`` edges, and
  Transcend's dict feed doesn't expose them). This is data-side,
  not code-side; the parser feed (Tier 3 lineage) will populate
  them once Rahul's pipeline lands.

---

### v1.18.00 (2026-05-05) — /impact pre-aggregation: 5-minute hang → instant

Fourth and final leg of the Transcend-scale work. v1.15.00 indexed
hot tables; v1.16.00 paginated Changes/Timeline; v1.17.00 fixed
Graph/Lineage with focused subgraphs; this release unfreezes the
last broken page.

#### The problem

``POST /impact/batch`` used to compute downstream + upstream graph
walks for every change in a diff at request time. On the demo
(31 changes) it took ~600 ms; on a 250k-change Transcend extract
that math worked out to 500k recursive-CTE walks per request, and
the page hung the browser at 5+ minutes. Indexing the underlying
tables in v1.15.00 made each individual walk faster but didn't
change the O(N) loop.

#### The fix

Pre-aggregate per-change impact counts ONCE — during post-ingest —
and persist them. ``/impact/batch`` becomes a paginated read of the
pre-aggregated rows.

**New table ``change_impact_summary``**

One row per ``change_id``, holding ``direct_count``, ``indirect_count``,
``impact_score``, ``max_depth``, ``snapshot_id``, ``computed_at``.
Indexed on ``snapshot_id`` for the batch read path. Migration
``f27c3d4e5f6b`` is idempotent (skips when the table exists, which
covers fresh DBs that already have it via ``Base.metadata.create_all``).

**Pre-aggregation hook in ``run_post_ingest_pipeline``**

After ``_auto_diff_against_previous`` produces the new ChangeEvent
rows, the pipeline now walks each change once with ``max_depth=3``
(vs the legacy ``max_depth=10`` — anything past depth 3 contributes
≤0.33 to the inverse-depth score and rarely changes the qualitative
outcome) and persists a summary row. Progress is wired through to
the dict-import progress tracker so the user sees
``computing impact summaries: 4,800 / 250,000`` instead of a frozen
step.

**Lazy backfill in ``compute_batch_impact``** (with safety cap)

Snapshots ingested before v1.18 don't have summaries. The batch
endpoint detects missing rows and computes them on first read,
persisting for next time. To prevent the original freeze coming
back via the lazy path, missing-summary sets above 5,000 changes
are skipped with a logged warning — those callers should re-import
the snapshot (post-ingest auto-computes) or run a dedicated
precompute. Below the cap the lazy path runs synchronously; the
cap was chosen to keep request time under ~30 s on a typical dev
machine.

**``compute_downstream_impact`` / ``compute_upstream_impact``**

Unchanged. Still used by the single-change drill-down endpoint
(``POST /impact/{change_id}``) and by the new pre-aggregation
helper, just with different ``max_depth`` values for each.

#### Numbers

On the user's environment (demo data, 31 changes, 9 pairs):

- Cold call (lazy backfill): ~600 ms (populates summary table)
- Warm call (reads summary): **12 ms**
- Same response shape; no UI changes needed

For Transcend (250k changes, projection): post-ingest adds time to
import (one-time, with progress UI). Subsequent ``/impact/batch``
reads are sub-second regardless of warehouse size.

#### Caveats

- ``BlastRadius.total_impacted_nodes`` previously deduplicated
  impacted nodes across all changes. The new implementation
  approximates it as the sum of direct counts — the deduplication
  would require either keeping the per-impact node detail (defeats
  the purpose of pre-aggregation) or a global SQL aggregate. For
  the UI's "blast radius" framing the sum is the more useful
  number anyway.
- ``affected_schemas`` / ``affected_tables`` now reflect the
  changed objects themselves rather than the impacted neighbours.
  The neighbour-level enumeration moved entirely to the per-change
  drill-down endpoint where it belongs.

---

### v1.17.00 (2026-05-05) — Focused subgraph for /graph and /lineage at warehouse scale

The third leg of the Transcend-scale work. v1.15.00 indexed the hot
tables; v1.16.00 paginated the Changes/Timeline endpoints. This
release moves the dependency-graph pages — which used to crash the
browser on a 337k-node extract by trying to dagre-layout the full
graph in JS — to a server-side BFS subgraph model.

#### Backend

- **New ``GET /graph/focus``** — server-side BFS around an anchor
  object. Parameters: ``snapshot_id``, ``root`` (accepts both
  ``schema.object_name`` and bare ``object_name`` forms), ``hops``
  (1–5, default 2), ``max_nodes`` (10–1000, default 200),
  ``edge_types`` (optional CSV whitelist), ``direction`` (up / down
  / both, default both). BFS is bounded by ``max_nodes``: when the
  cap is reached before exhausting hops we surface ``capped: true``
  so the UI can warn. Per-hop edge fetches use the
  ``ix_graph_edge_snapshot`` index; root resolution uses
  ``ix_graph_node_search`` (both added in v1.15.00) — typical focus
  lookup is sub-100 ms even on the 337k-node Transcend graph.

- **``GET /graph/{snapshot_id}`` adds a soft cap.** When the
  snapshot has more than ``FULL_GRAPH_NODE_CAP`` (5000) nodes, the
  endpoint short-circuits and returns
  ``{ truncated: true, total_nodes: N, nodes: [], edges: [] }``.
  The pre-flight ``COUNT(*)`` is sub-millisecond thanks to the
  same v1.15.00 index. Below the cap, behaviour is unchanged so the
  demo and small-customer flows are not affected.

#### Frontend

- **``/lineage`` rewritten.** No longer fetches the full graph;
  uses ``<ObjectAutocomplete source="graph">`` (introduced in
  v1.16.00) for the object picker and calls ``/graph/focus`` with
  ``edge_types=FEEDS`` directly. The 5-lane upstream / center /
  downstream layout is still computed in the browser, but from a
  ~200-node BFS neighbourhood instead of a 337k-node soup. Surfaces
  a "BFS hit cap" hint when the server reports ``capped: true``.

- **``/graph`` is dual-mode.** Snapshots under the soft cap render
  the full graph as before. Above it, the page shows an
  amber "this graph has N nodes — pick an anchor" banner and the
  autocomplete; once the user picks an anchor the page calls
  ``/graph/focus`` (with the user's edge-filter and hops slider)
  and dagre-lays out the resulting subgraph. Switching snapshots
  resets focus state so a stale anchor from one snapshot can't
  silently 404 against another.

- The legacy ``ObjectPicker`` component (which required a
  pre-loaded list of objects) is no longer wired into ``/graph``
  or ``/lineage``. It still exists in the codebase for any caller
  that genuinely wants a client-side filtered list of a small
  bounded set; the autocomplete-via-API replaces it everywhere
  the bounded-set assumption breaks at scale.

#### Numbers

On the user's environment with the Transcend extract loaded:

- ``/graph``: previously hung the browser entirely; now shows the
  truncation banner instantly, and a focused subgraph renders in
  ~1 s after picking an anchor.
- ``/lineage``: previously hung at the wire-transfer + dagre
  layout phase; now lands in <1 s for any object, regardless of
  warehouse size.

#### Caveats / not in this release

- ``/impact`` is still slow on the Transcend extract — that's a
  separate architectural problem (250k changes × 2 recursive
  CTEs each). The proper fix is pre-aggregating per-change impact
  summaries during ``run_post_ingest_pipeline``, planned for the
  next release.

---

### v1.16.00 (2026-05-05) — Pagination + server-backed object autocomplete + Changes/Timeline scale fix

The frontend half of the Transcend-scale work. PR-A (v1.15.00)
indexed the hot tables so the backend stopped doing 9.8M-row scans
on every diff. This release does the equivalent on the wire: instead
of shipping 250k changes to the browser in one JSON blob, we
paginate, filter server-side, and replace the giant native ``<select>``
widgets with a real typeahead.

#### Backend

- **``/diff/{from}/{to}/details``** is paginated. Accepts ``limit``,
  ``offset``, ``severity``, ``is_breaking``, and ``object_q``;
  returns ``{ summary, changes, limit, offset, has_more }``. The
  ``summary`` is computed by a single ``GROUP BY severity, is_breaking``
  query — at most ~6 buckets regardless of how many millions of
  changes match — so the KPI cards always reflect the full filtered
  set without paying for a full result download. Filter pushdown
  uses ``OR``-of-equality pairs over ``(snapshot_from, snapshot_to)``
  rather than ``tuple_(...).in_(...)`` because SQLite's planner is
  more reliably able to pick up the composite index from the former.
  ``compute_diff`` is now only redispatched on ``offset==0`` so
  paginating doesn't redo idempotency probes per page.

- **``/timeline``** is paginated. Same envelope (``{ events, total,
  limit, offset, has_more }``). The legacy ``/timeline/objects`` is
  hard-capped at 1000 results and marked deprecated — new code
  should use the new search endpoint instead.

- **New ``GET /objects/search``** — generic, server-side autocomplete.
  Backed by either ``change_event.object_identifier`` (default —
  what Timeline uses) or ``graph_node`` (for Simulation/What-If
  later). Returns at most ``limit`` items + a ``has_more`` flag,
  computed via ``LIMIT limit+1`` so we don't pay for a separate
  ``COUNT(*)``. The composite ``(snapshot_id, schema_name,
  object_name)`` index added in v1.15.00 makes the graph-source
  variant a single seek even on 337k-node extracts.

#### Frontend

- **New shared ``<ObjectAutocomplete>``** (``components/shared/``).
  Replaces every place we used to ``<select>`` over an unbounded
  list of objects. Debounced (250 ms), AbortController-cancelled
  for in-flight requests when the user keeps typing, click-outside
  to close, Enter to pick the top match, Escape to dismiss. Works
  for both backing sources via the ``source`` prop.

- **``/changes`` rewrite.** Filters (severity, breaking, object name)
  are sent server-side; the table renders one page (default 100
  rows) with a ``Load next 100`` affordance, instead of the
  500-row hard cap the previous release shipped. KPI cards source
  off a separately-cached ``baseSummary`` (the very first
  unfiltered fetch for a pair) so toggling filters doesn't
  flicker the cards. ``ExpandableRow`` no longer owns its own
  ``useState``; expansion is a ``Set<change_id>`` in the parent —
  removes the React-hook explosion that killed the previous
  500-row render at 250k rows. SelectionContext hydration on
  navigate-back now skips the auto-refetch when the cache already
  has the active pair, restoring the pre-pagination instant feel
  for revisits.

- **``/timeline`` uses ``<ObjectAutocomplete>``** instead of the
  legacy two-input "search box + native ``<select>``" combo. The
  events list also paginates with a ``Load next 200`` button.

- **``DonutChart`` overlay fix.** Previously, hovering a slice
  dropped the floating tooltip card on top of the static centre
  ``Total`` label, producing unreadable stacked text on
  ``/usage``. Now the centre swaps to the active slice's name +
  value + share on hover (single positioned element, can't
  overlap), inactive slices fade to 0.45 opacity for visual
  feedback, and a small detail strip below the donut shows the
  optional ``detail`` field for callers that pass one.

#### Numbers

On the user's environment:

- ``/changes`` for the 9-pair demo (≈30 changes total): unchanged,
  still instant.
- ``/changes`` for snapshot 1→11 (where 11 is the 250k Transcend
  diff): previously hung the browser entirely; now lands in
  ~2 s with the first 100 rows visible and ``Load more`` for the
  rest.
- ``/timeline`` object selector: the 240k-identifier dropdown is
  gone; the autocomplete returns the top 20 matches per
  keystroke, debounced 250 ms.

#### Caveats / not in this release

- ``/impact`` and ``/graph`` are still slow on the Transcend
  extract — they need their own focused-subgraph and pre-aggregated
  summary work (planned for the next release).

---

### v1.15.00 (2026-05-05) — DB layer cleanup: indexes, schema-parity test, single canonical init script

Foundational cleanup of the persistence layer triggered by Rahul's
Transcend extract scaling pain (~250k changes / 9.8M columns / 337k
graph nodes). Symptom that surfaced it: a diff between snapshots #1
and #10 — sub-second on demo data — took **54 seconds** with
snapshot #11 (Transcend) loaded in the same DB. Root cause was
threefold: missing SQLite indexes on the hot tables, drift between
ORM models and Alembic migrations, and two parallel paths to schema
creation that could (and did) diverge.

#### Indexes added (migration ``d05a1b2c3d4e``)

Eight composite/single-column indexes on the tables every read path
touches:

- ``change_event(snapshot_from, snapshot_to)`` — used by every diff
  read AND by ``DiffEngine.compute_diff``'s idempotency probe. The
  killer one: previously, a diff over snapshots 1→10 ran 9 sequential
  full-table scans of 250k rows each. With the index, each lookup is
  a sub-millisecond seek.
- ``change_event(object_identifier)`` — backs ``/timeline`` and the
  new ``/objects/search`` autocomplete.
- ``schema_snapshot(snapshot_id)``, ``table_snapshot(schema_id)``,
  ``column_snapshot(table_id)`` — every ``DiffEngine`` invocation
  loaded both snapshots' schemas/tables/columns; without these
  indexes the column scan dominated diff time on a 9.8M-row extract.
- ``graph_node(snapshot_id)`` and ``graph_node(snapshot_id, schema_name,
  object_name)`` — first one for plain graph fetches, second for the
  upcoming ``/objects/search?source=graph`` autocomplete.
- ``graph_edge(snapshot_id)`` — same reason for edge fetches.

Migration is idempotent (uses ``inspect()`` to skip indexes that
already exist) so it's safe to re-run. SQLite ``CREATE INDEX`` is
online; on a 9.8M-row ``column_snapshot`` it took ~10–20 s of disk
I/O once. The payoff is permanent: every subsequent diff/graph fetch
uses the index instead of full-scanning.

#### Drift between ORM and Alembic — caught and fixed

A new test (``backend/tests/test_schema_parity.py``) compares the
schema produced by ``alembic upgrade head`` against the one produced
by ``Base.metadata.create_all()``. On its first run it found **9
real drift items** that had been latent for months:

**Columns in models but missing from migrations** — exactly the kind
of bug that caught Helton on day one (``alembic upgrade`` produced a
partial schema that crashed ``rich_seed`` later). Backfilled by
migration ``e16b2c3d4f5a``, idempotent so existing dev DBs (where
the columns already exist via ``create_all``) get a no-op:

- ``snapshot.structural_hash`` (String)
- ``snapshot.object_count`` (Integer)
- ``change_event.severity`` (String) — drives the Changes table KPIs
- ``change_event.is_breaking`` (Boolean) — drives the Breaking badge
- ``impact_event.impact_score`` (Float)

**Indexes in migrations but missing from models** — opposite drift:
fresh DBs created via ``Base.metadata.create_all`` (tests, new dev
machines) didn't get them. Added ``__table_args__`` declarations to
the affected models so ``create_all`` produces an identical schema:

- ``attribute_lineage`` (×2 lineage walks)
- ``index_snapshot`` (table+index_number lookup)
- ``object_criticality`` (snapshot+score top-N)
- ``partitioning_snapshot`` (table_id)
- ``process``, ``step`` (×3 — natural-key dedup)

CI will now fail on the next drift, before it reaches anyone.

#### Single canonical lifecycle script

Replaced the split between ``tools/bootstrap_sqlite_db.py``
(``create_all`` path) and bare ``alembic upgrade head`` with one
script: ``backend/tools/db_init.py``.

```
.venv\Scripts\python.exe backend\tools\db_init.py
```

With no arguments it shows an interactive menu (init / init+seed /
reset / reset+seed / seed-only / cancel). For scripted use:

```
db_init.py init              # idempotent; auto-stamps legacy DBs
db_init.py reset --yes       # wipe + recreate schema
db_init.py reset --with-seed
db_init.py seed              # demo data only
```

Three DB states are detected automatically: **fresh** (empty),
**managed** (alembic-tracked), **legacy** (tables exist but
``alembic_version`` is empty — the case Guillermo's local DB landed
in when ``create_all`` ran without a stamp). The legacy branch
verifies schema parity with ``Base.metadata`` before stamping at HEAD;
if it doesn't match, it refuses rather than silently entering an
inconsistent state.

The old ``bootstrap_sqlite_db.py`` is gone. README, ``docs/handover.md``
and ``dev.ps1`` updated to reference the new script (always with the
venv's Python — ``db_init.py`` itself prints a friendly hint when run
with the system interpreter and bails before the ImportError noise).

#### Breaking changes

None at the application level. The only operational change is that
DB setup goes through ``db_init.py`` now; the old bootstrap path
no longer exists. Existing dev DBs (``alembic_version`` populated)
are unaffected; legacy DBs (created via the now-removed bootstrap)
are auto-stamped on the next ``db_init.py init``.

---

### v1.14.16 (2026-05-05) — Live import UX: per-step progress, cancel, pre-flight summary, VACUUM on delete

This is the big UX round on top of the perf work. The dict-import
panel went from "drop files, click button, wait 6 minutes for a
toast" to a real-time checklist with per-step progress, an inline
cancel button, an up-front "what am I about to import" summary,
and an auto-VACUUM on delete that reclaims disk space.

#### Backend

- **Sync handler.** `import_dict_batch` was `async def`, which meant
  its multi-minute synchronous body (parse + persist + post-ingest)
  blocked the asyncio event loop end-to-end. While it ran, every
  parallel request — including the new `/progress` polls and the
  `/cancel` POST — timed out. Made the handler `def` so FastAPI
  dispatches it to the threadpool; the loop stays free for the
  small endpoints. `_stream_upload_to_disk` is now sync too
  (`upload.file.read()` instead of `await upload.read()`); same
  semantics, no async needed.

- **WAL mode globally.** Added an `event.listens_for(engine,
  "connect")` hook that sets `journal_mode=WAL` and
  `synchronous=NORMAL` on every new SQLite connection. With WAL,
  parallel readers (the polling) don't block the writer (the
  persist). Without it, polls every second stalled the writer
  behind their shared locks and the persist phase tripled in wall
  time (~12 min vs ~4 min). The persist transaction still relaxes
  to `synchronous=OFF` for max bulk-insert speed;
  `journal_mode=MEMORY` was REMOVED from the persist's PRAGMAs
  because it would have re-enabled writer-blocks-readers on this
  connection.

- **`/dict-import/{id}/progress` + `/cancel` endpoints.** Backed by
  a thread-safe in-memory dict (`import_progress.py`) that the
  handler updates at every step transition. The frontend opens the
  polling channel in parallel with the long POST and, when the user
  hits Cancel, fires a `POST /cancel` that flips a flag — the
  persist hot loop checks the flag at heartbeat boundaries (every
  250 k columns / 50 k indices) and raises `ImportCancelled`,
  rolling back the partial transaction.

- **Per-step progress captions.** `_log_persist_progress` and the
  post-ingest steps now also push their captions through to the
  in-memory state (`columns: 4 250 000 rows (39 k/s)`, `building
  lineage graph…`, `computing criticality scores…`) so the UI
  checklist updates live without us having to invent fake progress.

- **VACUUM after snapshot delete.** SQLite default
  `auto_vacuum = NONE` keeps deleted pages around as free space;
  the file never shrinks. After a 240 k-table cascade that's
  several GB stuck on disk. The delete handler now runs a VACUUM
  in autocommit right after the cascade commit and reports
  `bytes_freed` in the response so the toast can say "Freed 2.3 GB
  on disk". A failed VACUUM is non-fatal — the snapshot is already
  gone, the file just stays at its old size.

- **`.db-wal` / `.db-shm` ignored** in `.gitignore`. WAL mode
  creates these auxiliary files at runtime; they're not artefacts
  to commit.

#### Frontend

- **`accept=".dat"`** on the file picker so the OS dialog only
  shows extraction outputs. Drag-drop bypasses this filter (OS
  limitation), so the server-side format detector remains the
  source of truth — this just removes the click-to-pick foot-gun.

- **Pre-flight summary.** When files land in the dropzone, the
  browser samples the first 5 MB of each, counts newlines, and
  extrapolates to a total row estimate per view. Shown both in
  the COVERAGE block and the per-file list before any upload
  happens — the user knows they're about to import "10 712
  databases · 239 380 tables · 9.8 M columns" up front, not after
  six minutes of waiting.

- **Per-step checklist component.** Replaced the previous
  "indeterminate shimmer + time-based caption" with a real list
  of named steps (Upload / Parse files / Validate identity /
  Persist data / Build graph & metrics) that flip from pending →
  running → done as the server reports progress through the
  polling channel. Each step shows its own elapsed time and an
  optional caption — for the persist step that's the live row
  count rolling at ~6 second cadence.

- **Cancel button** wired through the new endpoint. Visible only
  while an import is in flight; click sets `cancel_requested`
  server-side and the persist rolls back at the next checkpoint
  (~6 s). The POST resolves with HTTP 499, which the frontend
  treats as a clean exit (toast: "Import cancelled. No data was
  persisted."). Includes a small retry loop for the 404 race
  during the upload window — if the user clicks Cancel before
  the server has registered the import, the helper retries every
  500 ms for 3 seconds rather than failing immediately.

- **Toast on delete** now includes the bytes freed by VACUUM:
  "Snapshot #11 deleted. 239 380 tables, 9 858 099 columns,
  0 changes removed. Freed 2.3 GB on disk."

#### Verified end-to-end

Same machine, same DB, same code, two environments side by side
(2.4 GB Transcend-DevTest extract):

| Setup                                   | Persist  | Total      |
|-----------------------------------------|---------:|-----------:|
| `dev.ps1` + browser open + DevTools     | 14m 18s  | 19m 47s    |
| Bare `uvicorn` + script poller (no GUI) |  4m 31s  |  6m 38s    |

SCION's code is fine. The dev-mode penalty is `next dev`
(Turbopack HMR) + browser DevTools competing for CPU/disk with the
SQLite fsyncs; production (Docker, `next start`, no `--reload`)
won't pay that overhead.

74/74 metadata + diff tests passing. No public API change beyond
the new `/progress` and `/cancel` endpoints + the `vacuum` block
in the delete response.

---

### v1.14.15 (2026-05-05) — Persist phase 3.5× faster + live progress in console

The 240k+ table import worked end-to-end after v1.14.13/14 but still
took 22 minutes on Rahul's full Transcend-DevTest extract — almost
all of it spent fsync-ing one bulk-insert batch at a time. This
release tackles the next layer of throughput plus the visibility gap
operators hit yesterday ("the UI says it's still working, the
backend console shows nothing for 17 minutes").

End-to-end on the same 2.4 GB / 9.8M-column extract:

| run                        | total      | persist    |
|----------------------------|-----------:|-----------:|
| yesterday                  | **22 min** | ~17 min    |
| this morning (PRAGMAs only)| 6 min 53 s | 4 min 40 s |
| now (this release)         | **6 min 21 s** | 4 min 11 s |

#### 1. `app.*` loggers actually appear in `dev.ps1`'s console

uvicorn configures only its own loggers, so every `logger.info()` in
the `app.*` namespace was silently dropped under the default config —
including the per-phase timing line `[persist] columns 9858099 rows
in 4m 11s` and every other ingest checkpoint. Added a one-shot
`logging.basicConfig(level=INFO, ...)` in `app/main.py` so the root
logger flushes to stdout at INFO. uvicorn's own access/error logs are
unaffected because their loggers are namespaced (`uvicorn`,
`uvicorn.access`) and configured separately.

#### 2. Mid-phase progress heartbeats during the columns / indices bulk insert

The bulk insert is one logical transaction; the previous code only
logged AFTER each phase completed. For 9.8M rows that meant ~4 minutes
of UI silence with no way to know the backend was making forward
progress vs. stalled.

`_bulk_insert_columns_streaming` and `_bulk_insert_indices_streaming`
now emit a heartbeat every 250 000 / 50 000 rows respectively:

```
[persist] columns      250000 seen /    250000 created (39628 rows/s,  6.31s elapsed)
[persist] columns      500000 seen /    500000 created (39994 rows/s, 12.50s elapsed)
[persist] columns      750000 seen /    750000 created (39818 rows/s, 18.84s elapsed)
... (one line every ~6 seconds, 40 total over the columns phase)
```

The heartbeat triggers regardless of whether a row was inserted (so
extracts heavy on orphaned-parent rows like DBC.* don't go quiet
either). Operator can now see throughput drift, stalls, or back-
pressure inside a single phase — the missing observability we
diagnosed yesterday afternoon.

#### 3. SQLite tuned for the bulk-insert transaction

A new context applies three PRAGMAs on the session connection right
before the `persist_batch` call and restores them on `finally`:

  - `journal_mode = MEMORY` — rollback journal in RAM instead of disk.
  - `synchronous = OFF` — no fsync after each commit.
  - `cache_size = -65536` — 64 MB page cache (default ~2 MB).

Trade-off: an OS-level crash mid-import can corrupt the DB. Acceptable
because the whole import is one logical transaction — a crash means
"no snapshot was created" semantically and the user re-runs.
Production durability is the deployment story's problem (Postgres /
WAL replication / backups), not SQLite's.

Effect on the columns persist alone: ~9.6k rows/s → ~41k rows/s
(**~4.3× speedup on the dominant phase**, measured against the
identical 9.8M-row workload).

#### 4. Tables persist on the bulk_insert_mappings hot path (33 s → 2.3 s)

The tables loop was still using `session.add()` + `session.flush()`
per row to recover the autogenerated `table_id` — necessary for the
columns FK lookup but ~33 s on 240k rows. Replaced with the same
pattern we already use for `graph_builder`:

  1. Build a list of dicts.
  2. `bulk_insert_mappings(TableSnapshot, ...)` in batches of 5 000.
  3. Single SELECT joining `table_snapshot` to `schema_snapshot`
     (filtered by snapshot_id) recovers the
     `(database_name, table_name) → table_id` map for downstream FK
     planning.

**~14× speedup on the tables phase** (33.7 s → 2.3 s). Measured on the
same 240k-table workload.

#### 5. `compute_structural_hash` streamed instead of buffered

The original implementation materialised every row into a list of
formatted strings, called `"\n".join(parts)` to build a single ~1 GB
string for 9.8M columns, encoded that string to UTF-8 bytes, and
hashed it. Now we feed the hasher directly from a `yield_per`
cursor. Memory peak drops from ~2 GB to a few MB; wall time drops
modestly (~50 s → ~42 s) since the dominant cost at this scale is the
SQL `ORDER BY` across 9.8M rows, not Python.

The hash format is **byte-identical** to the previous implementation —
explicit `f"{prefix}C:..."` reproduces the exact same byte sequence
the old `"\n".join(parts)` produced. Critical because
`Snapshot.structural_hash` is persisted across runs; a different
serialisation here would invalidate every existing fingerprint.
Verified end-to-end against snapshot 11: same digest before and
after (`149a66eb5db8a5a8...`).

74/74 metadata + diff tests still passing. No public API change.

---

### v1.14.14 (2026-05-04) — Snapshot delete cascade made viable at 240k+ tables (hot-fix)

The `DELETE /snapshots/{id}` endpoint manually cascaded by materialising
every dependent ID and feeding it to `IN (?, ?, ?, ...)`. Same SQLite
host-parameter cap that bit `compute_snapshot_metrics` in v1.14.13 —
on the full Transcend-DevTest extract (239k tables, 9.8M columns) the
DELETE blew up with the same shape of error. SCION just let you finish
your first big import with no way to undo it.

This is a **hot-fix** to the existing manual-cascade approach:

- All `IN(big_list)` clauses replaced with scalar subqueries. Each
  DELETE now ships a single SQL statement with a constant number of
  host parameters, regardless of how many rows match.
- Cascade extended to cover the v1.14.02 sub-tables (`index_snapshot`,
  `partitioning_snapshot`, `ddl_text_snapshot`) and the v1.13 parser
  tables (`process`, `step`, `attribute_lineage`) plus
  `object_criticality` — all of which were silently leaking orphan
  rows on every snapshot delete in prior versions.
- Counts computed up front via `func.count()` aggregates so the
  response body still reports per-table row counts to the UI.

Verified end-to-end on snapshot 11 (the Transcend-DevTest one):

```
STATUS 200 in 28.02s
cascade = {
  schemas:        10 712
  tables:        239 380
  columns:     9 858 099
  indices:       337 817
  partitioning:   17 140
  ddl_text:        6 829
  graph_nodes:   250 092
  graph_edges:   426 243
  criticality:   250 092
}
```

~11.5M rows deleted in 28 s, no crash, all dependent tables clean.

This is a hot-fix to keep the current manual-cascade architecture
working at scale; the architecturally correct fix is to declare
`ON DELETE CASCADE` on the FKs and let SQLite/Postgres handle it
server-side. Tracked as a follow-up — see issue planned for the
post-ingest hardening epic.

74/74 metadata + diff tests still passing. No public API change
beyond the new `indices`, `partitioning`, `ddl_text`, and
`criticality` fields in the response's `cascade` object.

---

### v1.14.13 (2026-05-04) — Post-ingest pipeline made viable at 240k+ table scale

The streaming refactor in v1.14.09 made it possible to *finish* the
upload + persist for Rahul's full Transcend-DevTest extract (240k
tables, 9.8M columns). But the moment the post-ingest pipeline kicked
in, it ran for 30+ minutes without completing. Three of its six steps
were architecturally unsuited to that scale and one of them
**crashed outright**.

This release rewrites those three steps with the same `bulk_insert /
bulk_update` pattern we already use in `dict_persister`, plus fixes
the crash. End-to-end post-ingest now completes in **~1m 44s** for
the same dataset (vs. never finishing before).

#### 1. `compute_snapshot_metrics` — crash fix

Previous code did:

```python
table_ids = session.scalars(select(...).where(snapshot_id == ...)).all()
column_count = session.scalar(
    select(func.count())
    .where(ColumnSnapshot.table_id.in_(table_ids))   # ← 240k IDs
)
```

SQLite caps host parameters per statement at 32 766 (newer builds) or
999 (older), so the `IN (?, ?, ...)` over every table_id was either a
hard error (`OperationalError: too many SQL variables`) or a badly
fragmented plan. Rewrote both queries (tables + columns counts) as
JOIN-based aggregates so the work stays server-side and the parameter
count stays at 1.

Verified: 9.8M-column snapshot metrics now compute in **~1.2 s** (vs
the previous "didn't compile the SQL"). Regression test in
`tests/metadata/test_snapshot_metrics_scale.py` synthesises a
1500-table snapshot to pin the fix.

#### 2. `build_graph_for_snapshot` — bulk insert + idempotency seed

Previous code created nodes one at a time:

```python
session.add(GraphNode(...))
session.flush()                       # round-trip per node
node_id = node.node_id
```

…and verified each edge with a SELECT before insert:

```python
def _ensure_edge(...):
    exists = session.query(GraphEdge).filter(...).first()  # round-trip per edge
    if exists is None:
        session.add(GraphEdge(...))
```

For 240k tables that's ~500 000 DB round-trips before the FEEDS-edge
heuristic even starts. Wall time on Transcend-DevTest: 30+ min, never
completed.

Rewrote to:

- Pre-load existing nodes + edges into Python sets / dicts (2 SELECTs
  total). Every "does row X already exist" check is now an O(1) hash
  lookup instead of a DB round-trip.
- Collect new nodes / edges into lists of dicts and ship them via
  `bulk_insert_mappings` in batches of 5 000 — same pattern as
  `dict_persister`.
- Re-fetch the snapshot's nodes once after insert to recover
  `node_id` values for downstream edge planning.

Same correctness contract (idempotent at the natural-key level for
both nodes and edges), three orders of magnitude fewer round-trips.

**Wall time: 30+ min → 33.5 s.**

#### 3. `persist_node_metrics` — bulk update + transaction fix

Previous code did `session.get(GraphNode, nid)` + ORM update per node
= 1 SELECT + 1 UPDATE per row. For 240k nodes that's ~480 000
round-trips and the operation never finished.

Rewrote to:

- Pre-load existing `node_metadata` for the whole snapshot in one
  SELECT.
- Compute the merged JSON in Python.
- Ship updates via `bulk_update_mappings` in batches of 5 000 — one
  UPDATE statement per batch via `executemany`.

A first attempt opened a transaction implicitly via the SELECT and
then tried to nest a `with session.begin()` for the writes, which
SQLAlchemy 2.0 rejects with "A transaction is already begun on this
Session". Fixed by wrapping read + write in a single
`with session.begin()` block.

**Wall time: never finished → 12.2 s.**

#### 4. `compute_criticality` — bulk insert + force-recompute from pipeline

Step 5 of the engine added one ObjectCriticality row at a time via
`session.add` inside a single transaction. At 240k objects the
identity map grew linearly and the trailing flush was effectively
quadratic. Rewrote to collect dicts and call `bulk_insert_mappings`
in batches of 5 000.

Also fixed a stale-cache bug surfaced during testing: the engine's
"if any rows already exist for this snapshot, return them as cache"
short-circuit silently skipped recomputation when a previous post-
ingest run had written rows that were later orphaned (failed
mid-pipeline, demo seeder leftovers, etc.). The post-ingest pipeline
now passes `force=True` so a fresh run always recomputes against the
just-rebuilt graph.

**Wall time: never finished → 6.95 s.**

#### Final post-ingest breakdown on the full Transcend-DevTest extract

```
[post-ingest] structural_hash   in 50.14s
[post-ingest] snapshot_metrics  in  1.18s
[post-ingest] build_graph       in 33.51s
[post-ingest] node_metrics      in 12.19s
[post-ingest] criticality       in  6.95s
[post-ingest] auto_diff         in     3 ms
COMPLETED in 104.06s
```

```
snapshot 11 final state:
  graph nodes:          250 092
  graph edges:          426 243
  nodes with metrics:   250 092   ← every node populated
  criticality rows:     250 092   ← every object scored
```

74/74 metadata + diff tests passing. No behaviour change in the
public API; only pipeline internals changed.

---

### v1.14.12 (2026-05-04) — Per-phase timing logs for the dict-import pipeline

Now that the streaming refactor lets us actually finish a 2.4 GB
import, the obvious next question is "where's the time going". This
release adds INFO-level timing instrumentation at every phase of the
ingest so we can answer that without guessing — and so any future
optimisation has a concrete baseline to beat.

What gets logged (all at INFO, prefix `[ingest]` / `[persist]` /
`[post-ingest]`):

```
[ingest] ───────────── dict-import started — 6 file(s) ─────────────
[ingest] uploaded databases       2.7 MB in 0.4s  (databasesv_full_export.rendered.dat)
[ingest] uploaded tables         55.2 MB in 1.8s  (tablesv_full_export.rendered.dat)
[ingest] uploaded columns        1.9 GB in 33.4s  (columnsv_full_export.rendered.dat)
... etc
[ingest] parsed databases     10712 rows in 0.31s
[ingest] parsed tables       239380 rows in 5.83s
[ingest] parsed partitioning  17140 rows in 0.64s
[ingest] parsed tabletext     12428 rows in 19.20s
[ingest] identity validation passed in 5 ms — Transcend-DevTest @ 20260504T...
[persist] schemas       8543 rows in 12.30s
[persist] tables      239380 rows in 1m 07.40s
[persist] columns    9858099 rows in 4m 12.30s  (9858099 seen, 0 skipped → orphan parent)
[persist] indices     337817 rows in 14.20s     (337817 seen, 0 skipped)
[persist] partition    17140 rows in 1.20s
[persist] ddl_text     12428 rows in 0.80s
[ingest] session.commit() took 8.40s
[ingest] persist (...)  6m 57.40s
[post-ingest] structural_hash   in 1.20s
[post-ingest] snapshot_metrics  in 0.40s
[post-ingest] build_graph       in 45.20s
[post-ingest] node_metrics      in 12.30s
[post-ingest] criticality       in 8.40s
[post-ingest] auto_diff         in 22.10s
[ingest] post-ingest pipeline 1m 29.60s
[ingest] ───────────── summary ─────────────
[ingest]   snapshot_id=42  source=Transcend-DevTest  run=20260504T122005Z_65dde0...
[ingest]   persisted: schemas=8543 tables=239380 columns=9858099 ...
[ingest]   1_upload                  35.40s  ( 7.4%)
[ingest]   2_parse_small_files       26.00s  ( 5.4%)
[ingest]   3_validate_identity        5 ms  ( 0.0%)
[ingest]   4_persist_total          6m 57.40s  (87.0%)
[ingest]   5_post_ingest            1m 29.60s  (-)
[ingest]   TOTAL                    7m 58.00s
[ingest] ────────────────────────────────────
```

The summary line is the headline number — the rest is the breakdown
to know where to optimise next. Numbers above are illustrative; real
ones depend on the machine + extract size.

No production-affecting change beyond the new log lines. Levels are
INFO so they show up in the existing `dev.ps1` console without any
configuration change.

---

### v1.14.11 (2026-05-04) — Tolerate non-UTF-8 bytes in dict extracts

The full Transcend-DevTest extract has a stray `0xA0` byte (CP1252
non-breaking space) inside one of the table comments — almost certainly
a comment that was originally pasted into Teradata from Word or
Outlook. Rahul's contract says UTF-8 but the Windows-side TPT exporter
doesn't actually re-encode existing comment text, so whatever encoding
the data was stored in survives end-to-end. Strict UTF-8 decoding
crashed the entire 2.4 GB import on a single byte.

Fix: open the file with `errors="replace"`. Bad bytes become U+FFFD
(replacement char) instead of raising `UnicodeDecodeError`. Same
treatment for the `tabletext` reader's `path.read_text` call, since
DDL fragments routinely contain text pasted from external sources.

We lose at most a couple of glyphs per affected comment — strictly
better than aborting a multi-million-row ingest. Genuinely
catastrophic encoding mismatches (e.g. UTF-16 misdetected as UTF-8)
will still surface downstream as an arity error since nothing useful
will split on `§`.

End-to-end smoke test against the full Transcend-DevTest extract on
this machine:

| view         | rows         | wall time |
|--------------|--------------|-----------|
| databases    | 10 712       | 0.31 s    |
| tables       | 239 380      | 5.83 s    |
| partitioning | 17 140       | 0.64 s    |
| indices      | 337 817      | 5.85 s    |
| columns      | 9 858 099    | 3 min 6 s |
| tabletext    | 12 428       | 19.20 s   |

All 6 files detected at high confidence. Zero exceptions.

New regression test in `test_multiline_records.py` covers the bad-byte
case explicitly.

---

### v1.14.10 (2026-05-04) — Tolerate multi-line CommentString in dict tables.dat

The 16-col reader assumed every record was exactly one physical line.
That held in Sample 1 but not in Rahul's first full Transcend-DevTest
extract: record #15125 (`DBC.AccLogRule`, a system macro) has a
`CommentString` with an embedded `\n`. The exporter terminates records
with `\n` and does not escape literal newlines inside fields, so what
should be one record gets read as two — the first short by 4 fields,
the second corrupt — and the import bombed out with
"got 12 fields (16-col layout)".

Fix: `_parse_standard` now accumulates raw lines into a buffer and
emits a record only when its parsed field count hits exactly 16. Lines
that take the buffer over 16 fields (real corruption / layout drift)
still fail loudly with a precise locator. Lines that leave the file
ending mid-record surface as a clear "incomplete final record" error
rather than silently dropping data. Same record-recovery pattern
RFC-4180 CSV uses for quoted multi-line fields, except our boundary
discriminator is field count rather than a closing quote.

New regression tests in `tests/metadata/test_multiline_records.py`:
embedded-newline comment, > 16 fields, truncated final record.

No format change required from Rahul's side — this was an SCION-side
assumption that didn't survive contact with system tables.

---

### v1.14.09 (2026-05-04) — Streaming dict import for production-scale extracts

The dict-import pipeline used to read every uploaded file into memory
(`await upload.read()`), parse it into a `List[Record]`, then call
`session.add()` per row. That worked for Sample 1 (~145k rows total)
but melted down on Rahul's first full Transcend-DevTest extract
(2.4 GB across 6 files, 9.8M columns alone). This release rebuilds
the path to be O(memory) constant regardless of extract size, with
clear two-phase progress feedback in the UI.

Backend changes:
- **Streaming uploads.** `dict_import.py` now writes each multipart
  part to a `NamedTemporaryFile` in 4-MiB chunks instead of buffering
  the body in RAM. A 2 GB upload uses one chunk's worth of memory at
  any moment.
- **Streaming readers.** `dict_flat_file_reader.py` exposes
  `iter_databases / iter_tables / iter_columns / iter_indices`
  generators that yield records one at a time. The internal
  `_parse_standard` helper now opens the file with a line iterator
  rather than `path.read_text()`, so we never hold the whole file as
  a string either. Existing `read_*` list-returning shims are kept
  for tests and the small-extract path (just `list(iter_*(...))`).
- **Bulk-insert persister.** `dict_persister.persist_batch` accepts
  `Iterable[ColumnRecord]` / `Iterable[IndexRecord]` (lists still
  work) and pushes records through `session.bulk_insert_mappings` in
  5 000-row batches. Per-row overhead drops by ~5-10× because we
  bypass ORM object construction and identity-map insertion.
- **Streaming validator.** `peek_first_record(path, iter_fn)` lets
  the endpoint check `(source_system, extract_run_id)` identity on
  the large views by sampling the first record only — Rahul's
  contract guarantees identity is uniform within a file, so walking
  9.8M rows just to confirm it would be wasteful. Mid-file
  corruption is still caught at ingest time by parser-side arity
  validation.
- **Removed `len(columns)` / `len(indices)` from `snapshot.description`.**
  Those values are reported in the API response and PersistResult;
  computing them up-front would consume the streaming iterators.

Frontend changes:
- **Two-phase progress bar.** New `DictImportProgress` component
  renders:
    1. **Uploading**: real bytes-on-the-wire % from axios's
       `onUploadProgress`, with live readouts for sent / total /
       speed / ETA.
    2. **Server processing**: indeterminate shimmer bar +
       elapsed-time counter + stage-aware caption that escalates as
       wait grows ("Parsing files…" → "Bulk-inserting columns in
       5 000-row batches…" → "Running the post-ingest pipeline…").
       After 60 s we add a reassurance line so users don't think
       the request is frozen.
- **Axios body-size + timeout caps removed** for the dict-import
  call (`maxBodyLength: Infinity`, `timeout: 0`). Without these,
  axios's defaults silently aborted multi-GB uploads partway
  through.

Tested: `pytest backend/tests/metadata/` 41/41 passing,
`tsc --noEmit` clean. Local end-to-end with Sample 1 still works
(idempotent re-import, force re-import). The full Transcend-DevTest
extract is now feasible on a laptop.

---

### v1.14.08 (2026-05-04) — Backfill missing Alembic migration for usage tables

`usage_event` and `object_criticality` are runtime-required tables
(populated by the post-ingest pipeline since v1.07) but never had an
Alembic migration. The dev DB worked because `tools/bootstrap_sqlite_db.py`
calls `Base.metadata.create_all()`, which creates everything registered
on `Base` regardless of migration history. A fresh `alembic upgrade head`
from an empty DB produced a partially functional schema — `rich_seed.py`
then crashed on `DELETE FROM object_criticality`.

This was reported by Helton on his first day setting up his local
environment. The workaround was to use the bootstrap script instead of
Alembic; this migration removes the workaround.

The new revision `c94d0e6a7b23` (after `b83c9d5e6f12`) creates both
tables exactly as defined in `app/usage/usage_models.py`, plus a
composite index `(snapshot_id, combined_score)` on `object_criticality`
that matches the engine + TAISA + export query patterns. Verified end
to end: `alembic upgrade head` against an empty DB produces the full
18-table schema; downgrade `-1` cleanly removes both tables.

This also unblocks the Docker work — the entrypoint can now rely on
`alembic upgrade head` and we don't need to ship `bootstrap_sqlite_db.py`
inside the container image.

---

### v1.14.07 (2026-04-29) — Auto-diff dict snapshots against the previous one

When a new dict batch is ingested, the post-ingest pipeline now
automatically diffs the new snapshot against the most-recent prior
snapshot from the same `source_system`. This was the obvious next
step after v1.13.03 (post-ingest pipeline) — without it, the user
has to navigate to `/changes` and run the diff manually every time
they import an extract, even though the most natural workflow is
"import this week's data, see what moved since last week".

Mechanics:
- New step 6 in `run_post_ingest_pipeline`. Late-imports the
  `DiffEngine` (avoiding circular imports via `app.diff.__init__`).
- Looks up the prior snapshot by `source_system_name` ordered by
  `snapshot_time DESC`, excluding the current snapshot.
- Calls `DiffEngine.compute_diff(prev_id, curr_id)`. The engine
  itself persists `change_event` rows idempotently — re-runs are
  no-ops, no duplicates.
- Logs the result count at INFO level so operators see it during
  development without checking `/changes`.
- Failures swallowed per the pipeline's existing pattern: a bad
  diff doesn't kill the import, just logs a warning. The user can
  re-run the diff by hand.

What this means for the demo flow:
- Re-import the Sample 1 batch → idempotent skip (no diff).
- Import a *modified* extract from the same source → snapshot
  created + change_event rows for every TABLE_ADDED / COLUMN_TYPE_CHANGED
  / etc., visible immediately in `/changes` and `/impact`.

### v1.14.04 (2026-04-29) — Split CHANGELOG.md from README

The README's changelog grew past 970 lines and was crowding out the
actual reference content. Split out into a dedicated `CHANGELOG.md`
at the repo root; README keeps a one-line pointer in its former
changelog section.

- Existing changelog content moved verbatim — no edits beyond the
  new file header.
- `release_policy.md` already listed this as a tracked cleanup
  ("CHANGELOG.md separated from README"); this closes that item.
- `tools/bump_version.ps1` will be updated in a later patch to
  write into `CHANGELOG.md` instead of `README.md` (kept separate
  so this PR is doc-only and clearly diffable).

### v1.14.03 (2026-04-29) — Tooling: version bump + ingest benchmark

Two scripts under `tools/` that internalise common operations we
were doing by hand or not doing at all.

**`tools/bump_version.ps1 <version> "<summary>"`**
Single-command version bump. Updates
`frontend/src/lib/constants.ts::APP_VERSION` and the
`**Version:** BETA vX.Y.Z` line in `README.md`, then injects an
empty changelog stub at the top of the Changelog section so we
just have to fill in the body before committing. Solves the
recurring "I forgot to bump the README" problem.

**`tools/benchmark_ingest.py --sample-dir <path>`**
End-to-end ingest benchmark. Runs parse → validate → persist →
post-ingest pipeline against a fresh temp DB and reports the
metrics we care about for the SQLite-vs-Postgres / VM-sizing
decision (per `docs/internal_roadmap.md` §1.1):

  - Wall time per stage (parse / validate / persist / post-ingest)
  - Peak RSS RAM (POSIX `resource` or Windows `psutil`)
  - `.db` size on disk
  - Persisted counts (schemas / tables / columns / indices / partitioning / DDL)
  - Final graph node + edge counts after post-ingest

Designed to be re-runnable against any sample as Rahul ships
larger extracts, so we can tell early when SQLite stops being
enough. Sample 1 today: ~135ms total, 96 KB DB.

### v1.14.02 (2026-04-29) — Persist indices, partitioning, and DDL text

The dict ingest pipeline parsed all 6 files but only persisted 3 of
them (databases / tables / columns) into dedicated tables. Indices,
partitioning and DDL text were "seen but not persisted" — counted in
the response and discarded.

This release wires up the missing 3:

- **New tables** (Alembic migration `b83c9d5e6f12`):
  - `index_snapshot` — one row per (index, column) pair from
    `DBC.IndicesV`. Multi-column indexes appear as multiple rows
    with same `index_number` and ascending `column_position`.
  - `partitioning_snapshot` — one row per partitioning constraint.
    `ConstraintText` stored verbatim (no parsing — Teradata's grammar
    is variable across versions and customers want to see exactly
    what the catalog reported).
  - `ddl_text_snapshot` — one row per object with the full
    reconstructed CREATE statement (assembled from `DBC.TableTextV`
    fragments). Single row per `table_id` (unique) so re-imports
    overwrite cleanly. `request_text_fragments` keeps the original
    chunk count for diagnostics.

- **Persister updated** — `dict_persister.py` now populates all 3
  sub-tables alongside databases/tables/columns. Records that
  reference parents we didn't ingest (e.g. an index on a system
  table) are skipped silently with a counter, never aborting the
  ingest.

- **Endpoint response** gains 3 new fields:
  `indices_created`, `partitioning_created`, `ddl_text_created`
  alongside the existing `*_seen` counts. Drift between `_created`
  and `_seen` indicates the parent-not-found case.

All 3 sub-tables FK to `table_snapshot` so they participate in the
existing snapshot-deletion cascade. No FK to `snapshot` directly —
going through `table_snapshot.schema_id → schema_snapshot.snapshot_id`
keeps a single source of truth for "which snapshot does this row
belong to."

### v1.14.01 (2026-04-29) — GitHub Actions CI

`.github/workflows/ci.yml` runs on every PR against `main` and every
push to `main`. Two parallel jobs:

- **Backend (pytest)** — runs `pytest backend/tests/metadata/` on
  Python 3.11. Scoped to metadata (the test set we know is stable
  post-isolation in v1.13.05); the diff/snapshot/graph/api/taisa
  suites have pre-existing fixture issues tracked as a separate
  cleanup task.
- **Frontend (TypeScript strict)** — runs `npx tsc --noEmit` on
  Node 20.

Both must succeed for a PR to merge. `concurrency` cancels in-flight
runs when a new commit lands on the same branch, saving minutes on
rapid amends without losing coverage of the final state.

### v1.14.00 (2026-04-29) — Liveness / readiness probe endpoints

Two new endpoints under the existing `/api/v1/health` router for
orchestrator integration:

- **`GET /api/v1/healthz`** — liveness probe. Returns 200 with
  `{"status": "ok"}` as long as the process is responsive. Does NOT
  touch the DB or any other dependency. If a load balancer or
  Docker `HEALTHCHECK` sees this fail, the process is hung — restart.
- **`GET /api/v1/health/ready`** — readiness probe. Returns 200 if
  the backend can serve real requests (SQLAlchemy `SELECT 1` succeeds
  AND the engine registry's `database_ready` flag is true), 503
  otherwise. Used by orchestrators to decide whether to route
  traffic — a transient DB hiccup pulls the pod out of rotation
  without restarting it.

The existing `/api/v1/health` endpoint is unchanged — it remains
the verbose, human-friendly engine-status view.

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

