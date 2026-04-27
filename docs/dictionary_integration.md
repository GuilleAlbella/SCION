# Data-Dictionary Integration Design

**Status:** draft — pre-implementation (v1.08 scope)
**Authors:** SCION team
**Context:** the Code Parser team (Rahul) is delivering a **separate** metadata-extract feed (`DBC.DatabasesV`, `DBC.TablesV`, `DBC.ColumnsV`, `DBC.IndicesV`, `DBC.PartitioningConstraintsV`, `DBC.TableTextV`) as flat-files. The Code Parser feed itself (lineage) stays unchanged. SCION consumes **both**.

The parser feed carries `process` / `step` / `attribute_lineage`. It does **not** carry `datasetType`, `dataType`, `nullable`, `ordinalPosition` — those come from the data-dictionary feed. Merging the two is what produces a complete snapshot.

---

## Goal

Produce a single SCION snapshot that:

- Is **dictionary-complete**: every object has its canonical `object_type`, every column has its real `data_type` + `nullable` + `ordinal_position`. No more `UNKNOWN` leaking through to the UI.
- Preserves **all parser-produced lineage artefacts**: `process`, `step`, `attribute_lineage` with expressions and transformation types.
- Is **deterministic** and **reproducible**: given the same two input files, re-running ingestion yields the same snapshot (modulo timestamps). Needed for drift detection + audit.

---

## Inputs

| Feed | Source | Primary-key shape | Notes |
|------|--------|-------------------|-------|
| **Dictionary** | Rahul's `export` SQL outputs (6 flat-files, `§`-delimited) | `(database_name, table_name)` at table level; `(..., column_name)` at column level | "Truth" for structure |
| **Lineage** | Parser JSON (`Parser/lineage-mvp.json` format) | `container_natural_key` / `dataset_natural_key` / `attribute_natural_key` — 2- or 3-level dotted string (`DB.TABLE.COLUMN`) | "Truth" for lineage |

Both feeds use the same `database.table[.column]` addressing convention → merge key is straightforward: **dotted natural-key match**.

---

## Merge policy: **dictionary-first**

```
  ┌──────────────────┐                       ┌──────────────────┐
  │ Dictionary feed  │                       │ Parser (lineage) │
  │ (flat files)     │                       │ (JSON)           │
  └────────┬─────────┘                       └────────┬─────────┘
           │ 1. read + validate                        │
           ▼                                           │
  ┌──────────────────┐                                 │
  │  DictionaryBundle│                                 │
  │  (in-memory)     │                                 │
  └────────┬─────────┘                                 │
           │ 2. create SCION snapshot (dict-complete)  │
           ▼                                           │
  ┌──────────────────┐                                 │
  │   Snapshot #N    │                                 │
  │  — schemas       │                                 │
  │  — tables        │                                 │
  │  — columns       │                                 │
  └────────┬─────────┘                                 │
           │ 3. attach lineage ◀─────────────────────── │
           ▼                                      (re-use existing parser_ingest.ingest)
  ┌──────────────────┐
  │ Snapshot #N      │
  │  + process       │
  │  + step          │
  │  + attr_lineage  │
  │  + graph_edges   │
  └──────────────────┘
```

### Why dictionary-first (and not lineage-first)

| Argument | Dict-first | Lineage-first |
|----------|-----------|----------------|
| UI never shows `UNKNOWN` in the demo happy-path | ✅ | ❌ until the dictionary arrives |
| Lineage edges that point to objects not in the dict can be flagged as **orphaned** deterministically | ✅ | ⚠️ we'd have to reconcile after the fact |
| Matches business ordering: catalog is usually captured BEFORE the release that shipped the lineage | ✅ matches cadence | ❌ |
| Handles **dict-only** case (no parser feed yet) cleanly — snapshot is valid without lineage | ✅ | ❌ lineage-first requires dummy dict |

**Decision:** dictionary-first.

### Parser-only fallback

If only the parser feed exists (today's v1.07 behaviour): no change. We keep the existing `parser_ingest.ingest()` path, which creates a snapshot with `UNKNOWN` object_type on tables and `UNKNOWN` data_type on columns. The UI already handles this gracefully (amber dashed borders in the graph + "Structural snapshot incomplete — waiting for parser v2" banner). **The dict-first flow is additive, not a replacement.**

---

## Concretely: the merge step

A new function `metadata.dict_persister.ingest_dictionary(bundle, snapshot_id=None) -> snapshot_id`:

1. **Create or upsert the Snapshot row.** If `snapshot_id` is None → create a new one with `source_system="teradata_dict"` and `description="<extract_run_id>"`. If passed → reuse (supports "refresh dict for an existing snapshot" use-case Rahul raised).
2. **For each `DatabaseRecord`** → upsert `SchemaSnapshot(snapshot_id, schema_name=database_name)`.
3. **For each `TableRecord`** → upsert `TableSnapshot(schema_id, table_name, object_type=object_type_from_tablekind(table_kind))`.
4. **For each `ColumnRecord`** → upsert `ColumnSnapshot` with the **formatted** canonical data_type (via `teradata_type_formatter.format_column_type`), the resolved nullability, and the ordinal_position directly from `column_id`.
5. **Indices, partitioning, tabletext** → stored as JSON in `table_snapshot.metadata` (future `table_metadata` table if volume justifies it; not worth a migration now).
6. **Run `compute_structural_hash(snapshot_id)`** and `compute_snapshot_metrics` as we already do for the parser path.

Then, **if a parser feed is present in the same request**, call the existing `parser_ingest.ingest(payload, snapshot_id=<the one we just created>)` to attach lineage on top. The parser ingestor is extended to accept an existing `snapshot_id` instead of always creating one.

---

## Merge-time invariants and conflict handling

| Scenario | Resolution |
|----------|-----------|
| Parser lineage references `A.B.c` — A.B exists in dict but column c does not | **drop the lineage edge**, emit `[WARN] orphan attribute_lineage: referenced column missing from dictionary` |
| Parser lineage references `A.B` — A.B does not exist in dict at all | **drop the edge**, emit `[WARN] orphan process/step: table missing from dictionary` |
| Dict has table A.B with 10 columns, parser says A.B.c11 was transformed (column not in dict) | dict is authoritative; drop the column-level lineage, keep the table-level `process` |
| Dict row_hash changed since last snapshot but column names didn't → treat as **no schema change**, just timestamp drift | We already do this — `structural_hash` ignores timestamps by design |
| `UNKNOWN` TableKind → table still persists (amber-dashed in graph), warning surfaced in report | Same as today's v1.05 behaviour |

---

## Deleted-row detection

Rahul's README says deleted-row derivation is explicitly on the consumer. This is trivially handled by our existing snapshot-diff engine: if snapshot #N has table `A.B` and snapshot #N+1 (produced by the next dict extract) does not, the diff engine emits `TABLE_REMOVED`. **No new code required** — this is the Phase 1 state.

---

## API surface (v1.08)

Proposed endpoints (subject to tweaks once we see the first real extract):

- `POST /api/v1/dict-import/preview?source_dir=...` → runs `preview(source_dir)`, returns an `IngestionPreview` (counts + warnings + translation samples). Dry-run parity with `/parser-import/lineage?dry_run=true`.
- `POST /api/v1/dict-import/ingest?source_dir=...` → runs the full dict-first flow, returns `{snapshot_id, counts, warnings}`.
- `POST /api/v1/dict-import/ingest-combined?dict_dir=...&parser_file=...` → dict-first + attach lineage in one transaction. This is the primary path for the demo.

Upload via multipart file-set rather than `source_dir` is a UI concern; can be wired later. The server-side API takes paths to simplify local development.

---

## Criticality and the usage-in-scope question

If `usage` ships late (Chris-level decision still pending), we add a flag on `criticality_engine.compute_criticality(..., usage_available: bool = True)`. When `False`:

- Skip the usage aggregation step.
- `combined_score = graph_score` (single-component, no 60/40 blend).
- Thresholds stay at 0.6 / 0.3 for HIGH / MEDIUM / LOW.

This gives us a runtime escape hatch — no rework of the UI, no rework of the ORM, no data migration. Toggle lives in `app/config/runtime.yaml` once, and the whole Criticality page keeps working against graph data alone.

---

## Open questions for Rahul (tracked in email)

1. Confirm `attributeClass` is implicit (DBC.ColumnsV contains only real catalog columns). **Likely yes.**
2. Confirm the `export` variant is the canonical output for SCION (no direct DB connection per steering-committee policy). **Already communicated.**
3. Row-hash parity: are we OK to use our own SHA-1 approximation for validation fixtures, or does he want us to use `hashrow()` output byte-for-byte when validating? **Low priority — fixtures only.**

---

## Status

- [x] `teradata_type_formatter.py` — pure type-code → canonical string
- [x] `dict_flat_file_reader.py` — reads §/ENDREC export files
- [x] `tools/generate_dict_fixtures.py` — generates realistic fixtures from rich_seed
- [x] `dict_ingestor.py` — preview + validation (no persistence)
- [ ] `dict_persister.py` — writes to DB (blocked on real sample export from Rahul)
- [ ] `/api/v1/dict-import/*` endpoints
- [ ] Frontend: merge `/snapshots` import flow to accept dict + parser together
- [x] Criticality `usage_available` fallback flag
