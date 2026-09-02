# SCION Ingestion Pipelines

**Status:** Architecture decision — Meeting #7 (Luis, Rahul, Kindy).
**Owner:** Guillermo Albella (SCION) + Rahul Kulkarni (Code Parser / Extractors).
**Last updated:** 2026-09-02

## Principle

SCION never connects directly to a customer database. **All inputs come from
offline extractors** owned by Rahul's team, delivered as flat files in
well-defined formats. SCION is a pure analytics layer on top of those files.

This was agreed in committee and re-confirmed in Meeting #7:

> "SCION should not be going directly [to the customer DB]. We should have
> one input to SCION that comes from the same source. All the connections
> are managed outside of the SCION interface."
> — Luis Ramadori

> "For data dictionary also, the spec I shared is primarily based on SCION
> requirements. The extraction will be based on what SCION needs."
> — Rahul Kulkarni

## The four pipelines

| # | Pipeline | Owner | Status | SCION consumer |
|---|----------|-------|--------|----------------|
| 1 | **BTEQ / SQL parser** | Rahul | ✅ Live (v1.04+) | `/api/v1/parser-import` |
| 2 | **Data dictionary** | Rahul | ✅ Live (v1.12+) | `/api/v1/dict-import` |
| 3 | **Usage statistics (PDCR)** | Rahul | ✅ Live (v1.21.6+) | `/api/v1/dict-import` (bundled) |
| 4 | **Raw code (BTX, shell, procs)** | Rahul | 🔴 Deferred | Future release |

All four share the same shape:

```
  [ customer DB ]   ──(offline extract)──▶   [ flat file ]   ──(HTTP upload)──▶   [ SCION ]
       |                                         |                                   |
       └─── Rahul's extractor ───────────────────┘                                   │
                                                                                     │
                                                 (never connects to customer DB) ────┘
```

## Pipeline 1 · BTEQ / SQL parser  *(live since v1.04)*

- **Input to extractor:** BTEQ / SQL scripts on customer filesystem.
- **Output:** JSON parse tree (one object per parsed statement). Tier-1/2/3
  lineage edges plus a consolidated `lineageFactAttribute` table.
- **SCION endpoint:** `POST /api/v1/parser-import/lineage`
- **What SCION does:** builds graph nodes + FEEDS edges from CREATE/INSERT
  dependencies, classifies objects by `datasetType`, persists
  `attribute_lineage` rows for column-level lineage. Supports dry-run mode.

## Pipeline 2 · Data dictionary  *(live since v1.12)*

- **Input to extractor:** `DBC.DatabasesV`, `DBC.TablesV`, `DBC.ColumnsV`,
  `DBC.IndicesV`, `DBC.PartitioningConstraintsV`, `DBC.TableTextV`.
- **Output format:** §-delimited, `ENDREC`-terminated ASCII flat files (6 files).
  Spec: `Parser/Data extract 2/README.md`.
- **SCION endpoint:** `POST /api/v1/dict-import` (multipart upload, 1–6 files).
- **What SCION does:** content-type detection per file, batch validation
  (same `source + run_id + temporal coherence`), idempotent snapshot keyed by
  `extract_run_id`. Tested end-to-end against Transcend-DevTest (10 716 schemas /
  240k tables / 9.8M columns).

## Pipeline 3 · Usage statistics (PDCR)  *(live since v1.21.6)*

- **Input to extractor:** PDCR `DBC.ObjectUsageV` (and related views).
- **Output format:** two file types, same §-delimited convention as Pipeline 2:
  - `pdcr_object_usage_<from>_<to>.dat` — per-object access counters (12 fields).
  - `pdcr_log_<from>_<to>.dat` — DBQL query log (10 fields, ENDREC-terminated,
    SQL text may span multiple rows via `SqlRowNo`).
- **SCION endpoint:** `POST /api/v1/dict-import` — PDCR files are auto-detected
  and routed into a separate pipeline; they never enter the dict snapshot pipeline.
- **What SCION does:**
  - `pdcr_object_usage_*` → `UsageEvent` rows; drives criticality scoring
    (60% usage weight + 40% graph fragility).
  - `pdcr_log_*` → `dbql_query` rows (reassembled SQL by QueryID);
    stores DBQL text for future DataDNA QueryID correlation.
  - Criticality recomputed after PDCR ingest with `usage_available=True`.
- **Validated against real data:** 77 619 / 78 049 = 99.45% object-usage rows
  inserted; 44 540 DBQL queries persisted; idempotency confirmed.

## Pipeline 4 · Raw code  *(deferred)*

- **Input:** BTEQ scripts, shell wrappers, stored procedure bodies, trigger
  text. Rahul's parser already reads these; pipeline 4 is about keeping the
  **raw text** alongside the parsed tree so SCION can show code diffs and
  semantic summaries via TAISA.
- **Status:** Deferred until at least one customer asks for it. Parsed tree
  from Pipeline 1 is sufficient for impact + lineage today.

## Why four separate pipelines, not one big one?

Discussed in Meeting #7:

1. **Independent release cadences.** Parser is stable; dict is still being
   specced; usage has legal/performance concerns in some customers.
2. **Independent security review.** A customer may approve parser extraction
   but not usage extraction — must be separable.
3. **Independent file formats.** Each source has its own schema; trying to
   union them would create a lowest-common-denominator format.
4. **Version skew tolerance.** Customer can re-send dict without re-running
   parser, and vice versa.

## Non-goals

- ❌ Direct JDBC / ODBC from SCION to customer DB. Ever.
- ❌ Streaming / real-time ingestion. Snapshots are discrete events.
- ❌ Write-back to customer DB. SCION is read-only analytics.
