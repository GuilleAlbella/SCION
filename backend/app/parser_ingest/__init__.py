"""Parser Ingest — adapt external lineage feeds into SCION's data model.

This subsystem is separate from ``app.metadata.adapters`` which EXTRACTS
metadata from live databases.  Here we INGEST pre-processed lineage payloads
produced by external tools and normalise them into a single internal model.

Adapter architecture (Phase 2)
-------------------------------
Each source technology has its own adapter that implements ``BaseLineageParser``
(``base_parser.py``).  All adapters produce the same ``ParsedLineagePayload``,
so the pipeline below is reused unchanged for every source:

    Source technology          Adapter module
    ─────────────────────────  ──────────────────────────────
    Teradata / DataDNA parser  teradata_parser.TeradataLineageParser  ← in production
    Context Engine / OpenLineage  openlineage_parser  (Phase 2, pending sample)
    Informatica / generic ETL  informatica_parser    (Phase 2B, pending Jon)

Pipeline (same for all adapters):

    raw external payload
        │
        ▼
    <Adapter>.safe_parse()     → ParsedLineagePayload (validated, structured)
        │
        ▼
    noise_filter.apply()       → ParsedLineagePayload (placeholders removed)
        │
        ▼
    ingestor.ingest()          → writes Snapshot + schema/table/column +
                                 graph_edge + process + step + attribute_lineage
        │
        ▼
    (or) dry_run.analyze()     → returns stats without persisting

Backwards compatibility
-----------------------
The module-level ``teradata_parser.parse()`` function is unchanged.  All
existing callsites (``parser_import.py``, ``share_import.py``) continue to
work without modification.  The new ``TeradataLineageParser`` class is an
opt-in wrapper for code that wants to use the adapter interface.
"""
