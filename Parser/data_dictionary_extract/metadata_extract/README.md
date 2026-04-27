# Metadata Extract SQL Templates

This folder contains full and incremental extraction SQL for:
1. `DBC.DatabasesV`
2. `DBC.TablesV` (without `RequestText`)
3. `DBC.ColumnsV`
4. `DBC.IndicesV`
5. `DBC.PartitioningConstraintsV`
6. `DBC.TableTextV`

Template layout:
1. Standard relational templates are in `scripts/metadata_extract/standard/`.
2. Export-ready templates are in `scripts/metadata_extract/` and use the `_export.sql` suffix.

## Placeholder Parameters
Use your SQL runner/template engine to substitute:
1. `?source_system_name_literal`
2. `?extract_run_id_literal`
3. `?watermark_ts` in `YYYY-MM-DD HH24:MI:SS` format
4. `?delimiter_literal` for export variants
5. `?escaped_delimiter_literal` for export variants
6. `?record_terminator_literal` for export variants

Example values:
1. `?source_system_name_literal` -> `'TD_PROD'`
2. `?extract_run_id_literal` -> `'2026-04-22T12:00:00Z'`
3. `?watermark_ts` -> `2026-04-21 00:00:00`
4. `?delimiter_literal` -> `'§'`
5. `?escaped_delimiter_literal` -> `'\§'`
6. `?record_terminator_literal` -> `'ENDREC'`

## Technical Field Behavior
1. `extract_run_id` should be generated once per orchestration run and reused across every rendered query in that run.
2. Recommended generation method: UTC timestamp plus UUID, for example `20260422T141530Z_550e8400e29b41d4a716446655440000`.
3. Deleted-row comparison/derivation is intentionally not included in these templates and should be performed by the downstream consumer.

## Notes
1. Column names can vary slightly by Teradata release. Adjust optional columns where needed.
2. `TableTextV` sequence/text column names may differ; verify your system catalog.
3. All text should be stored as UTF-8 in landing/curated stores.
4. The orchestration script can build `extract_run_id` automatically when you do not pass one.

## Orchestration Script
Use [run_metadata_extracts.py](c:/Users/rk186009/lineage-parser/scripts/metadata_extract/run_metadata_extracts.py) to render all templates for one run.

Example: render standard full extracts

```bash
python scripts/metadata_extract/run_metadata_extracts.py \
	--source-system-name TD_PROD \
	--mode full \
	--variant standard
```

Example: render export-ready full and incremental extracts

```bash
python scripts/metadata_extract/run_metadata_extracts.py \
	--source-system-name TD_PROD \
	--mode both \
	--variant export \
	--watermark-ts "2026-04-21 00:00:00"
```

Example: render and execute with an external runner

```bash
python scripts/metadata_extract/run_metadata_extracts.py \
	--source-system-name TD_PROD \
	--mode full \
	--variant export \
	--execute-command-template "bteq < \"{sql_file}\" > \"{log_file}\""
```

Export variant behavior:
1. Export templates emit one delimiter-safe record column per row.
2. Records end with the configured terminator token, default `ENDREC`.
3. These templates are intended for BTEQ/TPT-style flat-file delivery where multiline text may exist inside object definitions.
