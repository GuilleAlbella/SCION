# SCION Ingestion Pipelines

**Status:** Architecture decision — Meeting #7 (Luis, Rahul, Kindy).
**Owner:** Guillermo Albella (SCION) + Rahul Kulkarni (Code Parser / Extractors).

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
| 1 | **BTEQ / SQL parser** | Rahul | ✅ Live (v1) | `/api/v1/parser-import` |
| 2 | **Data dictionary** | Rahul | 🟡 Spec delivered, extractor pending | `/api/v1/dict-import` (stub) |
| 3 | **Usage statistics** | Rahul | 🔴 Not started | Future `/api/v1/usage-import` |
| 4 | **Raw code (BTX, shell, procs)** | Rahul | 🔴 Roadmap | Future release |

All four share the same shape:

```
  [ customer DB ]   ──(offline extract)──▶   [ flat file ]   ──(HTTP upload)──▶   [ SCION ]
       |                                         |                                   |
       └─── Rahul's extractor ───────────────────┘                                   │
                                                                                     │
                                                 (never connects to customer DB) ────┘
```

## Pipeline 1 · BTEQ / SQL parser  *(live)*

- **Input to extractor:** BTEQ / SQL scripts on customer filesystem.
- **Output:** JSON parse tree (one object per parsed statement).
- **SCION endpoint:** `POST /api/v1/parser-import` (file upload → snapshot).
- **What SCION does:** builds graph nodes + FEEDS edges from CREATE/INSERT
  dependencies, classifies objects by `datasetType`.

## Pipeline 2 · Data dictionary  *(next)*

- **Input to extractor:** `DBC.TABLES`, `DBC.COLUMNS` views (and equivalents).
- **Output format:** §-delimited, `ENDREC`-terminated ASCII flat file.
  Spec doc: `docs/dictionary_integration.md`.
- **SCION endpoint:** `POST /api/v1/dict-import` *(stubbed, waiting on real sample)*.
- **What SCION does:** enriches parser-sourced nodes with real column lists,
  data types, table kinds. Without this, column-level lineage depends on
  parser inference alone.

## Pipeline 3 · Usage statistics  *(planned)*

- **Input to extractor:** `DBC.AMPUsageV` / query log / DBQL.
- **Output format:** TBD — follows same §-delimited convention as dict.
- **SCION endpoint:** Future `POST /api/v1/usage-import`.
- **What SCION does:** drives criticality scoring, anomaly detection,
  "unused object" reports. Today SCION falls back to a synthetic
  `usage_available=false` flag when no real usage is loaded.

> **Meeting #7 decision:** Rahul will build the usage extractor. SCION does
> *not* query the customer DB for usage — same reason as dict, same
> architecture.

## Pipeline 4 · Raw code  *(future release)*

- **Input:** BTEQ scripts, shell wrappers, stored procedure bodies, trigger
  text. Rahul's parser already reads these; pipeline 4 is about keeping the
  **raw text** alongside the parsed tree so SCION can show code diffs and
  semantic summaries via TAISA.

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

## Open questions

- Usage volume per customer (Chris / Kindy to scope).
- Do we store raw code in SCION's SQLite, or just a hash + pointer?
- Incremental vs full dict re-import — today we replace everything.
