"""Parser Ingest — adapt external parser JSON feeds into SCION's data model.

This subsystem is separate from `app.metadata.adapters` which EXTRACTS
metadata from live databases. Here we INGEST a pre-processed JSON payload
produced by the DataDNA parser (a separate Teradata team's tool) which
already did the heavy lifting of parsing SQL and resolving lineage.

Pipeline:

    raw JSON
        │
        ▼
    teradata_parser.parse()    → ParsedLineagePayload (validated, structured)
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

The entire chain is format-version aware: future parser versions can
extend the payload without forcing a rewrite of the ingestor.
"""
