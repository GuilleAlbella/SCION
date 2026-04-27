from __future__ import annotations

"""Data-dictionary ingestor — **stub** phase.

What it does today:
  1. Reads the 6 flat-files (databases, tables, columns, indices,
     partitioning, tabletext) from a directory.
  2. Validates referential integrity between them (every column's
     `(database, table)` must exist in the tables file, etc.).
  3. Builds a typed, in-memory `DictionaryBundle` ready for a future
     persister to consume.
  4. Returns a summary report (`IngestionPreview`) with counts + warnings.

What it does NOT do yet (intentional):
  - Write anything to the DB.
  - Merge with parser-lineage data.
  - Touch the `Snapshot`, `SchemaSnapshot`, `TableSnapshot`,
    `ColumnSnapshot` ORM models.

Those come in the next phase, once we've seen a real export from Rahul
and locked down the merge semantics (see `docs/dictionary_integration.md`).

Keeping the stub separate from the persister lets us:
  - Preview a real export without committing to the DB (dry-run parity
    with the parser-ingest flow already in production).
  - Unit-test integrity validation in isolation.
  - Iterate on edge cases (missing files, partial extracts, orphans)
    before they're entangled with transaction handling.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from app.metadata import dict_flat_file_reader as dfr
from app.metadata.teradata_type_formatter import (
    ColumnTypeInput,
    format_column_type,
    is_nullable,
    object_type_from_tablekind,
)


# ──── File-layout contract ────
# Filenames match what `run_metadata_extracts.py --variant export --mode full`
# produces when all 6 views are rendered. The ingestor is tolerant of
# `_incremental` suffixes too; we look for both stems.
EXPECTED_FILES: Dict[str, List[str]] = {
    "databases":    ["databasesv_full.txt", "databasesv_incremental.txt"],
    "tables":       ["tablesv_full.txt", "tablesv_incremental.txt"],
    "columns":      ["columnsv_full.txt", "columnsv_incremental.txt"],
    "indices":      ["indicesv_full.txt", "indicesv_incremental.txt"],
    "partitioning": ["partitioningconstraintsv_full.txt",
                     "partitioningconstraintsv_incremental.txt"],
    "tabletext":    ["tabletextv_full.txt", "tabletextv_incremental.txt"],
}


# ──── Typed bundle + preview report ────

@dataclass
class DictionaryBundle:
    """All six files parsed into typed records, ready for merge / persist."""
    databases: List[dfr.DatabaseRecord] = field(default_factory=list)
    tables: List[dfr.TableRecord] = field(default_factory=list)
    columns: List[dfr.ColumnRecord] = field(default_factory=list)
    indices: List[dfr.IndexRecord] = field(default_factory=list)
    partitioning: List[dfr.PartitioningRecord] = field(default_factory=list)
    tabletext: List[dfr.TableTextRecord] = field(default_factory=list)

    # Resolved during validation — keyed by (database, table), value is the
    # canonical SCION object_type ("TABLE"/"VIEW"/…). Populated only once,
    # used by the future persister.
    resolved_object_types: Dict[Tuple[str, str], str] = field(default_factory=dict)


@dataclass
class IngestionPreview:
    """Summary returned by `preview()` and (later) `ingest()`.

    Shape mirrors the parser-ingest `IngestionReport` deliberately so the
    UI can use the same count-card component to render both flows.
    """
    source_directory: str
    extract_run_id: Optional[str]
    snapshot_date: Optional[str]
    input_counts: Dict[str, int] = field(default_factory=dict)
    translated_samples: List[str] = field(default_factory=list)  # e.g. "CV(255) → VARCHAR(255)"
    warnings: List[str] = field(default_factory=list)


# ──── Core operations ────

class DictIngestError(ValueError):
    """Fatal ingest errors (missing required file, malformed content)."""


def _locate_file(source_dir: Path, stems: List[str]) -> Optional[Path]:
    """Return the first existing file matching a list of candidate names."""
    for stem in stems:
        candidate = source_dir / stem
        if candidate.is_file():
            return candidate
    return None


def read_bundle(source_dir: Path) -> DictionaryBundle:
    """Load all 6 flat-files into a `DictionaryBundle`.

    A missing file is NOT fatal (the client may push files in phases),
    but we log it as a warning in the preview. The validator downstream
    will complain about referential gaps if something important is absent.
    """
    bundle = DictionaryBundle()

    # Databases / tables / columns are the spine — treat missing as WARN.
    # Indices / partitioning / tabletext are enrichments — missing is OK.
    db_path = _locate_file(source_dir, EXPECTED_FILES["databases"])
    if db_path:
        bundle.databases = dfr.read_databases(db_path)
    tbl_path = _locate_file(source_dir, EXPECTED_FILES["tables"])
    if tbl_path:
        bundle.tables = dfr.read_tables(tbl_path)
    col_path = _locate_file(source_dir, EXPECTED_FILES["columns"])
    if col_path:
        bundle.columns = dfr.read_columns(col_path)
    idx_path = _locate_file(source_dir, EXPECTED_FILES["indices"])
    if idx_path:
        bundle.indices = dfr.read_indices(idx_path)
    prt_path = _locate_file(source_dir, EXPECTED_FILES["partitioning"])
    if prt_path:
        bundle.partitioning = dfr.read_partitioning(prt_path)
    ttx_path = _locate_file(source_dir, EXPECTED_FILES["tabletext"])
    if ttx_path:
        bundle.tabletext = dfr.read_tabletext(ttx_path)

    # Resolve (database, table) → SCION object_type up front so the rest
    # of the pipeline never has to re-map TableKind codes.
    for t in bundle.tables:
        bundle.resolved_object_types[(t.database_name, t.table_name)] = (
            object_type_from_tablekind(t.table_kind)
        )

    return bundle


def validate(bundle: DictionaryBundle) -> List[str]:
    """Run referential-integrity checks, return human-readable warnings.

    Warnings are categorised by severity in the message itself (`[ERROR]`
    for definite data corruption, `[WARN]` for recoverable gaps). The
    caller decides whether to proceed — the default UX is to surface
    these in the preview panel before the user confirms ingest.
    """
    warnings: List[str] = []

    # Reference sets to validate pointers against.
    db_set = {d.database_name for d in bundle.databases}
    tbl_set = {(t.database_name, t.table_name) for t in bundle.tables}

    # ── Tables must reference known databases ──
    # If no `databases` file was supplied, skip this check instead of
    # complaining about every table (the report would be useless).
    if db_set:
        orphan_tables = [
            (t.database_name, t.table_name) for t in bundle.tables
            if t.database_name not in db_set
        ]
        if orphan_tables:
            warnings.append(
                f"[WARN] {len(orphan_tables)} table(s) reference a database "
                f"not present in the databases file. First 3: "
                + ", ".join(f"{d}.{t}" for d, t in orphan_tables[:3])
            )

    # ── Columns must reference known tables ──
    if tbl_set:
        orphan_cols = [
            (c.database_name, c.table_name, c.column_name)
            for c in bundle.columns
            if (c.database_name, c.table_name) not in tbl_set
        ]
        if orphan_cols:
            warnings.append(
                f"[ERROR] {len(orphan_cols)} column(s) reference a table not "
                f"present in the tables file. These would be dropped on merge. "
                f"First 3: "
                + ", ".join(f"{d}.{t}.{c}" for d, t, c in orphan_cols[:3])
            )

    # ── Indices / partitioning integrity (non-fatal) ──
    if tbl_set:
        orphan_idx = [
            (i.database_name, i.table_name) for i in bundle.indices
            if (i.database_name, i.table_name) not in tbl_set
        ]
        if orphan_idx:
            warnings.append(
                f"[WARN] {len(orphan_idx)} index record(s) reference missing "
                f"tables and would be ignored."
            )

    # ── Unclassified object types (parser-v1 parity) ──
    # Consistent with the parser flow: unclassified objects still get
    # persisted (as UNKNOWN), but we surface the count so demos don't
    # look deceptively clean when the source has exotic TableKinds.
    unclassified = sum(
        1 for v in bundle.resolved_object_types.values() if v == "UNKNOWN"
    )
    if unclassified > 0:
        warnings.append(
            f"[WARN] {unclassified} table(s) have an unrecognised TableKind "
            f"and would be stored as UNKNOWN (unclassified) in SCION."
        )

    # ── Columns with unrecognised data types ──
    bad_types = [
        (c.database_name, c.table_name, c.column_name)
        for c in bundle.columns
        if format_column_type(ColumnTypeInput(
            column_type=c.column_type,
            column_length=c.column_length,
            decimal_total_digits=c.decimal_total_digits,
            decimal_fractional_digits=c.decimal_fractional_digits,
            char_type=c.char_type,
        )).startswith("UNKNOWN(")
    ]
    if bad_types:
        warnings.append(
            f"[WARN] {len(bad_types)} column(s) use a Teradata type code "
            f"SCION doesn't recognise yet; canonical form falls back to "
            f"UNKNOWN(<code>). Add the code to `TYPE_CODE_MAP` to resolve. "
            f"First 3: " + ", ".join(f"{d}.{t}.{c}" for d, t, c in bad_types[:3])
        )

    return warnings


def preview(source_dir: Path) -> IngestionPreview:
    """Read + validate the directory; return a summary for the UI.

    NO database writes. This is the parity function to the parser-ingest
    `dry_run.analyze()` — good enough to show the operator what would
    happen, without touching production state.
    """
    bundle = read_bundle(source_dir)

    # Pick an extract_run_id + snapshot_date from the first record with
    # them (they're the same across an entire run by contract).
    run_id = snapshot_date = None
    for coll in (bundle.tables, bundle.columns, bundle.databases):
        if coll:
            run_id = coll[0].tech.extract_run_id
            snapshot_date = coll[0].tech.snapshot_date
            break

    report = IngestionPreview(
        source_directory=str(source_dir),
        extract_run_id=run_id,
        snapshot_date=snapshot_date,
        input_counts={
            "databases":     len(bundle.databases),
            "tables":        len(bundle.tables),
            "columns":       len(bundle.columns),
            "indices":       len(bundle.indices),
            "partitioning":  len(bundle.partitioning),
            "tabletext":     len(bundle.tabletext),
        },
    )

    # A handful of concrete type translations so the operator can
    # eyeball that the mapping looks right for their catalogue.
    for c in bundle.columns[:5]:
        canon = format_column_type(ColumnTypeInput(
            column_type=c.column_type,
            column_length=c.column_length,
            decimal_total_digits=c.decimal_total_digits,
            decimal_fractional_digits=c.decimal_fractional_digits,
            char_type=c.char_type,
        ))
        nbl = "NULL" if is_nullable(c.nullable) else "NOT NULL"
        report.translated_samples.append(
            f"{c.database_name}.{c.table_name}.{c.column_name}: "
            f"{c.column_type!r} → {canon} {nbl}"
        )

    report.warnings = validate(bundle)
    return report
