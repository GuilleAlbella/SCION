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
4. `?delimiter_literal` for `TableTextV` export variants
5. `?record_terminator_literal` for `TableTextV` export variants

Example values:
1. `?source_system_name_literal` -> `'TD_PROD'`
2. `?extract_run_id_literal` -> `'2026-04-22T12:00:00Z'`
3. `?watermark_ts` -> `2026-04-21 00:00:00`
4. `?delimiter_literal` -> `'§'`
5. `?record_terminator_literal` -> `'ENDREC'`

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

Execution behavior:
1. The script executes with BTEQ by default.
2. BTEQ logon settings are read from `scripts/metadata_extract/metadata_extract.jobvars` by default.
3. The following values must resolve from that job vars file or its referenced environment variables: `TdpId`, `UserName`, `UserPassword`.
4. `LogonMech` and `WorkingDatabase` are also honored when present.
5. Use `--job-vars-path` if you need to point to a different Teradata credential file.
6. Default export field delimiter is `§`.
7. `--sample N` appends a Teradata `SAMPLE N` clause to the rendered extract query.
8. For high-volume export, use `--execution-engine tpt` with the provided TPT job template(s).

Default metadata job vars file:
1. `scripts/metadata_extract/metadata_extract.jobvars` is a separate copy for metadata extraction.
2. It follows the same variable pattern as the DBQL export job vars file so the two flows can be configured independently.

Example: render and execute standard full extracts (default behavior)

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

Example: render only (skip BTEQ execution)

```bash
python scripts/metadata_extract/run_metadata_extracts.py \
	--source-system-name TD_PROD \
	--mode full \
	--variant export \
	--render-only
```

Example: render only with sampling

```bash
python scripts/metadata_extract/run_metadata_extracts.py \
	--source-system-name TD_PROD \
	--mode full \
	--variant export \
	--views databasesv \
	--sample 100 \
	--render-only
```

Example: high-volume export using TPT

```bash
python scripts/metadata_extract/run_metadata_extracts.py \
	--source-system-name TD_PROD \
	--mode full \
	--variant export \
	--execution-engine tpt \
	--tpt-job-path scripts/metadata_extract/metadata_extract_export.tpt \
	--tpt-output-dir scripts/metadata_extract/rendered
```

If TPT returns `EM_NOHOST` for `TdpId`, set a COP alias explicitly:

```bash
python scripts/metadata_extract/run_metadata_extracts.py \
	--source-system-name TD_PROD \
	--mode full \
	--variant export \
	--execution-engine tpt \
	--tpt-tdp-id TDPROD
```

Export variant behavior:
1. Standard export templates (`DatabasesV`, `TablesV`, `ColumnsV`, `IndicesV`, `PartitioningConstraintsV`) render one column per logical output field.
2. In TPT mode, those standard exports use `scripts/metadata_extract/metadata_extract_export.tpt`, which writes delimited rows via the DataConnector consumer.
3. For those standard exports, the field delimiter is applied by the TPT writer configuration, not by SQL concatenation inside the rendered `.sql` file.
4. `TableTextV` remains a special case because object text can contain embedded newlines. Its export templates still build a single concatenated record column and terminate each record with the configured token, default `ENDREC`.
5. In TPT mode, `TableTextV` uses `scripts/metadata_extract/metadata_extract_export_tabletextv.tpt` so it can stay on the single-record-column path.
6. TPT mode writes `.dat` files and keeps execution logs beside rendered SQL output.
7. The default field delimiter remains `§`; change it only if downstream tooling and TPT character-set handling are compatible with the replacement character.

## Extract Structures

The full and incremental variants for a given extract share the same output structure; only the filter logic differs.

### Standard extracts (multi-column, delimited in TPT)

These exports use a fixed 16-column layout (`col_01`..`col_16`) to match `metadata_extract_export.tpt`.

Common header fields:
1. `col_01` = `source_system_name`
2. `col_02` = `extract_run_id`
3. `col_03` = `current_timestamp(6)`
4. `col_04` = `cast(current_timestamp as date)`

`DatabasesV` (`databasesv_*_export.sql`):
1. `col_05` = `DatabaseName`
2. `col_06` = `OwnerName`
3. `col_07` = `CreatorName`
4. `col_08` = `CreateTimeStamp`
5. `col_09` = `LastAlterName`
6. `col_10` = `LastAlterTimeStamp`
7. `col_11` = `CommentString`
8. `col_12` = `PermSpace`
9. `col_13` = `SpoolSpace`
10. `col_14` = `TempSpace`
11. `col_15`..`col_16` = blank fillers

`TablesV` (`tablesv_*_export.sql`):
1. `col_05` = `DatabaseName`
2. `col_06` = `TableName`
3. `col_07` = `TableKind`
4. `col_08` = `CreatorName`
5. `col_09` = `CreateTimeStamp`
6. `col_10` = `LastAlterName`
7. `col_11` = `LastAlterTimeStamp`
8. `col_12` = `CommentString`
9. `col_13` = `ProtectionType`
10. `col_14` = `JournalFlag`
11. `col_15` = `CheckOpt`
12. `col_16` = blank filler

`ColumnsV` (`columnsv_*_export.sql`):
1. `col_05` = `DatabaseName`
2. `col_06` = `TableName`
3. `col_07` = `ColumnName`
4. `col_08` = `ColumnId`
5. `col_09` = `ColumnType`
6. `col_10` = `ColumnLength`
7. `col_11` = `DecimalTotalDigits`
8. `col_12` = `DecimalFractionalDigits`
9. `col_13` = `Nullable`
10. `col_14` = `DefaultValue`
11. `col_15` = `CharType`
12. `col_16` = `UpperCaseFlag`

`IndicesV` (`indicesv_*_export.sql`):
1. `col_05` = `DatabaseName`
2. `col_06` = `TableName`
3. `col_07` = `IndexName`
4. `col_08` = `IndexNumber`
5. `col_09` = `IndexType`
6. `col_10` = `UniqueFlag`
7. `col_11` = `ColumnName`
8. `col_12` = `ColumnPosition`
9. `col_13`..`col_16` = blank fillers

`PartitioningConstraintsV` (`partitioningconstraintsv_*_export.sql`):
1. `col_05` = `DatabaseName`
2. `col_06` = `TableName`
3. `col_07` = `ConstraintType`
4. `col_08` = `ConstraintText`
5. `col_09` = `CreateTimeStamp`
6. `col_10`..`col_16` = blank fillers

### TableTextV extract (single record column)

`TableTextV` (`tabletextv_*_export.sql`) is emitted as a single concatenated `metadata_record` field in this order:
1. `source_system_name`
2. `extract_run_id`
3. `current_timestamp(6)`
4. `cast(current_timestamp as date)`
5. `DatabaseName`
6. `TableName`
7. `TableKind`
8. `LineNo`
9. `RequestText` (trimmed to configured length)
10. `record_terminator_literal` (default `ENDREC`)

This is intentionally separate from the standard 16-column layout to preserve record boundaries when SQL text contains embedded newlines.
