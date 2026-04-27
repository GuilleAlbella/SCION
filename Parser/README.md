# DBQL / PDCR Export Bundle

This folder contains a unified export implementation for two source modes:

- Driver script: PowerShell and POSIX shell
- TPT script: reusable job definition
- TPT job variables file: configurable settings
- SQL templates: one per source mode

## Files

- `scripts/dbql_export/run_dbql_export.ps1`: Windows driver script
- `scripts/dbql_export/run_dbql_export.sh`: POSIX driver script
- `scripts/dbql_export/dbql_export.tpt`: TPT job
- `scripts/dbql_export/dbql_export.jobvars`: job-level configuration
- `scripts/dbql_export/dbql_export-base.sql`: Teradata DBQL template
- `scripts/dbql_export/pdcr_export-base.sql`: Teradata PDCR template

## Source Modes

- `pdcr`: extracts from Teradata 17.20-compatible PDCR objects and requires `--platform-name`
- `dbql`: extracts from Teradata 17.20-compatible DBQL objects and requires `--platform-name`

All three modes emit the same logical column order:

`Platform_Name|LogDate|ProcID|CollectTimestamp|QueryID|SqlRowNo|SqlTextInfo|DefaultDatabase|QB_JobName|QB_ProcName|ENDREC`

## How It Works

1. The driver receives an overall start and end timestamp.
2. The driver selects the SQL template for the requested source.
3. The driver splits the period into consecutive sub-period windows (`WindowHours`).
4. For each sub-period:
   - The driver injects the timestamps, source-specific objects, platform name, delimiter, and escape character into the selected SQL template.
   - The driver wraps the base query into a single-row text projection where fields are joined by `Delimiter` and terminated with `EndOfRecord`.
   - The driver writes a temporary TPT vars file with `SelectStmt` and `OutputFile`.
   - The driver invokes `tbuild` with the shared TPT job file.
   - The driver appends checkpoint and manifest rows after successful completion.
   - The driver optionally compresses the completed export with gzip.
5. Output file names include the source name and exact sub-period boundaries. The native database time zone is implied and not rendered in the file name.

## Character Set & Encoding

The TPT job uses LATIN character set without BOM for maximum compatibility with downstream text processing tools. Output is delimited and terminated as configured, allowing reliable round-trip handling of multi-byte characters.

## Why EndOfRecord Is Included

`sqltextinfo` may contain newline characters. Exporting one logical DBQL row as a single text payload terminated by `EndOfRecord` lets downstream consumers reliably reconstruct row boundaries even when newlines appear inside SQL text.

The base SQL templates also escape any delimiter characters that appear inside `SqlTextInfo` by prefixing them with the configured `EscapeCharacter`.

## Configurable Job Variables

Default values in `dbql_export.jobvars` include:

- `Delimiter='|'`
- `EscapeCharacter='\\'`
- `EndOfRecord='ENDREC'`
- `OutputDirectory='./output/dbql'`

Source-specific object settings are also defined there:

- `TeradataPdcrDatabase='PDCRInfo'`
- `TeradataDbqlLogView='QryLogV'`
- `TeradataDbqlSqlView='QryLogSQLV'`
- `TeradataDbqlDatabase='DBC'`
- `TeradataPdcrLogTable='DBQLogTbl_Hst'`
- `TeradataPdcrSqlTable='DBQLSQLTbl_Hst'`

Connection settings are sourced from environment variables through the job vars file defaults:

- `TDATA_HOST`
- `TDATA_USER`
- `TDATA_PASS`

Authentication is controlled by `LogonMech` in the job vars file and now defaults to `LDAP`.
Set `LogonMech='TD2'` only if local Teradata authentication is required.

The drivers validate that those values resolve before invoking TPT.

## Usage

### PowerShell

```powershell
./scripts/dbql_export/run_dbql_export.ps1 \
  -StartTimestamp "2026-03-01 00:00:00" \
  -EndTimestamp "2026-03-08 00:00:00" \
   -Source pdcr \
   -PlatformName PROD_TD \
  -WindowHours 24
```

For DBQL mode with gzip:

```powershell
./scripts/dbql_export/run_dbql_export.ps1 \
   -StartTimestamp "2026-03-01 00:00:00" \
   -EndTimestamp "2026-03-08 00:00:00" \
   -Source dbql \
   -PlatformName PROD_TD \
   -WindowHours 24 \
   -GzipOutput
```

### POSIX

```bash
./scripts/dbql_export/run_dbql_export.sh \
  --start "2026-03-01 00:00:00" \
  --end "2026-03-08 00:00:00" \
   --source pdcr \
   --platform-name PROD_TD \
  --window-hours 24
```

On restart, rerunning the same command reuses the per-run checkpoint file and skips already completed windows whose delivered files still exist.

## Output

Each sub-period produces one file:

- `output/dbql/<source>_YYYYMMDD_HHMMSS_to_YYYYMMDD_HHMMSS.dat`

If gzip is enabled, the delivered file becomes `.dat.gz`.

Each exported logical record is:

`Platform_Name|LogDate|ProcID|CollectTimestamp|QueryID|SqlRowNo|SqlTextInfo|DefaultDatabase|QB_JobName|QB_ProcName|ENDREC`

where `|` and `ENDREC` are configurable.

Failed statements are excluded by filtering on `coalesce(ErrorCode, 0) = 0`.
Statement scope is currently limited to:

- `INSERT`
- `CREATE TABLE`
- `REPLACE TABLE`
- `CREATE VIEW`
- `REPLACE VIEW`

`UPDATE`, `MERGE`, and `DELETE` are intentionally out of scope for current lineage derivation and are excluded. They are expected to be added in a future release.
The interval semantics are start-inclusive and end-exclusive by design.

Each run also writes:

- `<source>_<run>.checkpoint.csv`: completed windows for restart, with expected vs actual row counts
- `<source>_<run>.manifest.csv`: delivered files with source row counts, expected counts (via reconciliation query), SHA-256 hashes, and size

The expected row count is computed before export by querying the source objects with the same time-window, error-code, and statement-type filters. This enables validation of export completeness by comparing delivered row count against expected row count.
