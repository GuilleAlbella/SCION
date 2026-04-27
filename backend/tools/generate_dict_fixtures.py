"""Generate realistic data-dictionary flat-file fixtures from SCION seed.

Why this exists: we need to test the dictionary-ingest pipeline end-to-end
without waiting for Rahul's team to land a real production export. This
script reads the most recent snapshot from our own SQLite demo DB and
writes 6 files in the exact `§`/`ENDREC` export format the production
runtime will emit (per `Parser/data_dictionary_extract/.../*_export.sql`).

The fixtures are semantically plausible — Teradata type codes derived
from our canonical string (`"VARCHAR(255)"` → `CV`, length 255), realistic
hashrow values, etc. — but NOT byte-identical to a real Teradata run.
Good enough to exercise the reader contract and the merge logic.

Usage (backend running or not — it only reads the SQLite file):
    cd backend
    ../.venv/Scripts/python.exe tools/generate_dict_fixtures.py
"""

from __future__ import annotations

import hashlib
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Tuple
from uuid import uuid4

# ── Path setup ──
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, os.pardir, os.pardir))
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from sqlalchemy.orm import Session

from app.db.engine import engine
from app.db.models.snapshot import Snapshot
from app.db.models.schema_snapshot import SchemaSnapshot
from app.db.models.table_snapshot import TableSnapshot
from app.db.models.column_snapshot import ColumnSnapshot


# ── Export format constants (must match Rahul's defaults) ──
DELIM = "§"
ESCAPE = "\\"
TERMINATOR = "ENDREC"

# Where to write the fixtures
FIXTURES_DIR = Path(BACKEND_DIR) / "tests" / "fixtures" / "dict_extracts"


# ──────────────────────────────────────────────────────────────────────
# Reverse-translation: SCION canonical data_type string → Teradata codes.
# This is the inverse of `teradata_type_formatter.format_column_type`.
# We only need to cover what rich_seed actually produces, not every
# imaginable type.
# ──────────────────────────────────────────────────────────────────────

# Ordered regex table so "VARCHAR" wins before any generic match.
_REVERSE_PATTERNS: list[tuple[re.Pattern, str, str]] = [
    # (pattern, family, base_code)
    (re.compile(r"^BYTEINT$",                re.I), "fixed",   "I1"),
    (re.compile(r"^SMALLINT$",               re.I), "fixed",   "I2"),
    (re.compile(r"^INTEGER$",                re.I), "fixed",   "I"),
    (re.compile(r"^BIGINT$",                 re.I), "fixed",   "I8"),
    (re.compile(r"^DECIMAL\((\d+),(\d+)\)$", re.I), "decimal", "D"),
    (re.compile(r"^DECIMAL\((\d+)\)$",       re.I), "decimal", "D"),
    (re.compile(r"^NUMERIC\((\d+),(\d+)\)$", re.I), "decimal", "D"),
    (re.compile(r"^NUMBER\((\d+)\)$",        re.I), "decimal", "N"),
    (re.compile(r"^FLOAT$",                  re.I), "fixed",   "F"),
    (re.compile(r"^REAL$",                   re.I), "fixed",   "F"),
    (re.compile(r"^DOUBLE PRECISION$",       re.I), "fixed",   "FD"),
    (re.compile(r"^VARCHAR\((\d+)\)$",       re.I), "charlen", "CV"),
    (re.compile(r"^CHAR\((\d+)\)$",          re.I), "charlen", "CF"),
    (re.compile(r"^CLOB(?:\((\d+)\))?$",     re.I), "charlen", "CO"),
    (re.compile(r"^LONG VARCHAR$",           re.I), "charlen", "CV"),
    (re.compile(r"^VARBYTE\((\d+)\)$",       re.I), "charlen", "BV"),
    (re.compile(r"^BYTE\((\d+)\)$",          re.I), "charlen", "BF"),
    (re.compile(r"^BLOB(?:\((\d+)\))?$",     re.I), "charlen", "BO"),
    (re.compile(r"^DATE$",                   re.I), "fixed",   "DA"),
    (re.compile(r"^TIME(?:\((\d+)\))?$",     re.I), "time",    "AT"),
    (re.compile(r"^TIME\((\d+)\) WITH TIME ZONE$", re.I),          "time", "TZ"),
    (re.compile(r"^TIME WITH TIME ZONE$",    re.I),                "time", "TZ"),
    (re.compile(r"^TIMESTAMP(?:\((\d+)\))?$", re.I),               "time", "TS"),
    (re.compile(r"^TIMESTAMP\((\d+)\) WITH TIME ZONE$", re.I),     "time", "SZ"),
    (re.compile(r"^TIMESTAMP WITH TIME ZONE$", re.I),              "time", "SZ"),
    (re.compile(r"^INTERVAL YEAR TO MONTH$", re.I), "fixed", "YM"),
    (re.compile(r"^INTERVAL YEAR$",          re.I), "fixed", "YR"),
    (re.compile(r"^INTERVAL MONTH$",         re.I), "fixed", "MO"),
    (re.compile(r"^INTERVAL DAY TO HOUR$",   re.I), "fixed", "DH"),
    (re.compile(r"^INTERVAL DAY TO MINUTE$", re.I), "fixed", "DM"),
    (re.compile(r"^INTERVAL DAY TO SECOND$", re.I), "fixed", "DS"),
    (re.compile(r"^INTERVAL DAY$",           re.I), "fixed", "DY"),
    (re.compile(r"^INTERVAL HOUR TO MINUTE$", re.I), "fixed", "HM"),
    (re.compile(r"^INTERVAL HOUR TO SECOND$", re.I), "fixed", "HS"),
    (re.compile(r"^INTERVAL HOUR$",          re.I), "fixed", "HR"),
    (re.compile(r"^INTERVAL MINUTE TO SECOND$", re.I), "fixed", "MS"),
    (re.compile(r"^INTERVAL MINUTE$",        re.I), "fixed", "MI"),
    (re.compile(r"^INTERVAL SECOND$",        re.I), "fixed", "SC"),
    (re.compile(r"^PERIOD\(DATE\)$",         re.I), "fixed", "PD"),
    (re.compile(r"^PERIOD\(TIMESTAMP(?:\((\d+)\))?\)$", re.I), "time", "PS"),
    (re.compile(r"^JSON$",                   re.I), "fixed", "JN"),
    (re.compile(r"^XML$",                    re.I), "fixed", "XM"),
    (re.compile(r"^ST_GEOMETRY$",            re.I), "fixed", "GE"),
    (re.compile(r"^ARRAY$",                  re.I), "fixed", "A1"),
    (re.compile(r"^BOOLEAN$",                re.I), "fixed", "I1"),  # TD stores as BYTEINT
]


def canonical_to_td_type(
    data_type: str,
) -> Tuple[str, int | None, int | None, int | None]:
    """Inverse of `format_column_type`. Returns (code, length, total, frac).

    Unrecognised types fall back to ("??", None, None, None) — the reader
    will translate this back to "UNKNOWN(??)" which is the same loss-of-
    information path the real system would take. This closes the loop
    and lets us prove round-trip stability on the fixtures.
    """
    for pattern, family, code in _REVERSE_PATTERNS:
        m = pattern.match(data_type)
        if not m:
            continue
        if family == "fixed":
            return code, None, None, None
        if family == "decimal":
            groups = m.groups()
            total = int(groups[0]) if groups and groups[0] else None
            frac = int(groups[1]) if len(groups) > 1 and groups[1] else None
            return code, None, total, frac
        # `groups()` is safer than `group(1)` because some patterns have
        # zero capturing groups (e.g. bare `^LONG VARCHAR$`) — group(1)
        # would raise IndexError on those.
        if family == "charlen":
            g = m.groups()
            n = int(g[0]) if g and g[0] else 0
            return code, n, None, None
        if family == "time":
            g = m.groups()
            n = int(g[0]) if g and g[0] else 0
            return code, n if n > 0 else None, None, None
    return "??", None, None, None


# ──────────────────────────────────────────────────────────────────────
# Field-level encoding per the export SQL contract
# ──────────────────────────────────────────────────────────────────────

def _escape(val: str | int | None) -> str:
    """Escape a single field exactly as `oreplace(value, §, \\§)` would.

    Empty / None → empty string (BTEQ convention). We also coerce ints
    to their string form so the caller can pass raw values without
    sprinkling str() everywhere.
    """
    if val is None:
        return ""
    s = str(val)
    if DELIM in s:
        s = s.replace(DELIM, ESCAPE + DELIM)
    return s


def _record(fields: list) -> str:
    """Assemble one record: fields joined by `§`, closed with `ENDREC\\n`."""
    return DELIM.join(_escape(f) for f in fields) + TERMINATOR + "\n"


def _row_hash(*parts) -> str:
    """Approximation of Teradata's `hashrow()`.

    Since we don't have access to TD's actual hashrow implementation, we
    use SHA-1 truncated to 16 hex chars — enough entropy for fixtures,
    and it changes exactly when any input changes (same property as
    hashrow). The production reader doesn't care about the hash value,
    only that it's stable across the same row.
    """
    material = "|".join("" if p is None else str(p) for p in parts)
    return hashlib.sha1(material.encode("utf-8")).hexdigest()[:16]


# ──────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────

def main() -> int:
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)

    # Pick the most recent snapshot — that's the "live" state to export.
    with Session(engine) as session:
        snap = session.query(Snapshot).order_by(Snapshot.snapshot_id.desc()).first()
        if snap is None:
            print("[fixtures] No snapshots found — run rich_seed.py first.")
            return 1

        schemas = session.query(SchemaSnapshot).filter(
            SchemaSnapshot.snapshot_id == snap.snapshot_id
        ).all()

        tables_by_schema = {
            s.schema_id: session.query(TableSnapshot).filter(
                TableSnapshot.schema_id == s.schema_id
            ).all()
            for s in schemas
        }

        columns_by_table = {}
        for tables in tables_by_schema.values():
            for t in tables:
                columns_by_table[t.table_id] = session.query(ColumnSnapshot).filter(
                    ColumnSnapshot.table_id == t.table_id
                ).order_by(ColumnSnapshot.ordinal_position).all()

    # Shared header values — one run_id for all six files, matching the
    # cadence promise in the README ("extract_run_id should be generated
    # once per orchestration run and reused across every rendered query").
    run_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{uuid4().hex}"
    extracted_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.000000+00:00")
    snapshot_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    source_system = "TD_DEMO"

    def tech_header(row_hash_val: str) -> list:
        return [source_system, run_id, extracted_at, snapshot_date, row_hash_val]

    # ── 1. databasesv_full_export.txt ──
    db_path = FIXTURES_DIR / "databasesv_full.txt"
    with db_path.open("w", encoding="utf-8") as f:
        for s in schemas:
            row_hash = _row_hash(s.schema_name, "DBC", "rich_seed")
            f.write(_record(
                tech_header(row_hash) + [
                    s.schema_name,              # DatabaseName
                    "DBC",                      # OwnerName (realistic default)
                    "rich_seed",                # CreatorName
                    "2026-01-15 10:00:00",      # CreateTimeStamp
                    None,                       # LastAlterName
                    None,                       # LastAlterTimeStamp
                    f"Banking EDW: {s.schema_name}",  # CommentString
                    "1048576000", "524288000", "209715200",  # Perm/Spool/Temp
                    "8388608", "33554432",      # CurrentPerm / PeakPerm
                ]
            ))

    # ── 2. tablesv_full_export.txt ──
    # Mapping TABLE/VIEW/... back to the TableKind single-letter code.
    kind_map = {"TABLE": "T", "VIEW": "V", "MACRO": "M",
                "STORED_PROCEDURE": "P", "FUNCTION": "F", "TRIGGER": "I"}
    tbl_path = FIXTURES_DIR / "tablesv_full.txt"
    with tbl_path.open("w", encoding="utf-8") as f:
        tvm = 1000
        for s in schemas:
            for t in tables_by_schema[s.schema_id]:
                kind = kind_map.get(t.object_type, "T")
                row_hash = _row_hash(s.schema_name, t.table_name, kind, tvm)
                f.write(_record(
                    tech_header(row_hash) + [
                        s.schema_name, t.table_name, kind, str(tvm),
                        "rich_seed", "2026-01-15 10:00:00",
                        None, None,
                        f"Seeded {t.object_type} {t.table_name}",
                        "F",      # ProtectionType — Fallback
                        "N",      # JournalFlag
                        "N",      # CheckOpt
                    ]
                ))
                tvm += 1

    # ── 3. columnsv_full_export.txt ──
    col_path = FIXTURES_DIR / "columnsv_full.txt"
    with col_path.open("w", encoding="utf-8") as f:
        for s in schemas:
            for t in tables_by_schema[s.schema_id]:
                for c in columns_by_table[t.table_id]:
                    code, length, td, fd = canonical_to_td_type(c.data_type)
                    row_hash = _row_hash(
                        s.schema_name, t.table_name, c.column_name,
                        c.ordinal_position, code, length, td, fd, c.nullable,
                    )
                    f.write(_record(
                        tech_header(row_hash) + [
                            s.schema_name, t.table_name, c.column_name,
                            str(c.ordinal_position),
                            code, length, td, fd,
                            "Y" if c.nullable else "N",
                            None,    # DefaultValue
                            None,    # Format
                            None,    # Title
                            "1" if code.startswith("C") else None,  # CharType (Latin)
                            None,    # CaseSpecific
                        ]
                    ))

    # ── 4. indicesv_full_export.txt ──
    # We synthesise a PK on the first column of each TABLE — covers the
    # most common pattern (id-column PI). Views don't get indices.
    idx_path = FIXTURES_DIR / "indicesv_full.txt"
    with idx_path.open("w", encoding="utf-8") as f:
        for s in schemas:
            for t in tables_by_schema[s.schema_id]:
                if t.object_type != "TABLE":
                    continue
                cols = columns_by_table[t.table_id]
                if not cols:
                    continue
                first_col = cols[0]
                row_hash = _row_hash(
                    s.schema_name, t.table_name, 1, 1, "P", "Y", "Y", first_col.column_name
                )
                f.write(_record(
                    tech_header(row_hash) + [
                        s.schema_name, t.table_name,
                        None,       # IndexName (anonymous PI)
                        "1",        # IndexNumber
                        "P",        # IndexType — Primary
                        "Y",        # UniqueFlag
                        "Y",        # PrimaryKeyFlag
                        first_col.column_name,
                        "1",        # ColumnPosition
                        "A",        # Ordering (Asc)
                        None,       # ConstraintName
                    ]
                ))

    # ── 5. partitioningconstraintsv_full_export.txt ──
    # None of our seeded tables are partitioned; we emit an empty file so
    # the reader can prove it handles zero-row inputs gracefully.
    part_path = FIXTURES_DIR / "partitioningconstraintsv_full.txt"
    part_path.write_text("", encoding="utf-8")

    # ── 6. tabletextv_full_export.txt ──
    # We emit a plausible CREATE statement for each VIEW; tables don't have
    # RequestText in DBC.TableTextV (they're defined by ColumnsV + IndicesV).
    ttx_path = FIXTURES_DIR / "tabletextv_full.txt"
    with ttx_path.open("w", encoding="utf-8") as f:
        for s in schemas:
            for t in tables_by_schema[s.schema_id]:
                if t.object_type != "VIEW":
                    continue
                cols = columns_by_table[t.table_id]
                col_list = ",\n    ".join(c.column_name for c in cols) or "*"
                ddl = (
                    f"REPLACE VIEW {s.schema_name}.{t.table_name} AS\n"
                    f"  LOCKING ROW FOR ACCESS\n"
                    f"  SELECT\n    {col_list}\n"
                    f"  FROM {s.schema_name}.{t.table_name}_base;\n"
                )
                row_hash = _row_hash(s.schema_name, t.table_name, "V", 1, ddl)
                # Real TableTextV chunks at 12500 chars; our DDLs are small,
                # so seq=1 is enough. Multi-chunk is stressed in a unit test.
                f.write(_record(
                    tech_header(row_hash) + [
                        s.schema_name, t.table_name, "V", "1", ddl,
                    ]
                ))

    # ── Summary ──
    print("[fixtures] Snapshot used:", snap.snapshot_id, "—", snap.description)
    print("[fixtures] Output directory:", FIXTURES_DIR)
    for p in (db_path, tbl_path, col_path, idx_path, part_path, ttx_path):
        size = p.stat().st_size
        print(f"  {p.name:45s}  {size:>7d} bytes")
    print("[fixtures] extract_run_id:", run_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
