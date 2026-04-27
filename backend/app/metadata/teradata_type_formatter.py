from __future__ import annotations

"""Teradata internal type-code → canonical SQL string.

Rahul's data-dictionary feed exposes `ColumnType` as a 2-character
Teradata internal code (`"CV"` = varchar, `"I"` = integer, `"DA"` = date,
etc.) plus the size/decimal fields separately. SCION stores `data_type`
as a single canonical string like `"VARCHAR(255)"` or `"DECIMAL(18,2)"`
so the diff engine can compare snapshots textually and the UI can render
them directly.

This module is the translation layer. Pure functions, no I/O, no global
state — testable in isolation. The mapping comes from the Teradata SQL
Data Types and Literals reference (Teradata 17.x–20.x); adding a new
type is a single-line addition to `TYPE_CODE_MAP`.

Design notes:
- `CharType` (1=Latin, 2=Unicode, 3=KanjiSJIS, 4=Graphic, 5=Kanji1) refines
  the char-family types; we only surface Latin/Unicode for the canonical
  string because they're the 99.9% case in banking/telecom warehouses.
- Interval types embed their own precision in the `ColumnType` code itself
  (e.g. `"YR"` = INTERVAL YEAR, `"YM"` = INTERVAL YEAR TO MONTH) — we
  don't look at ColumnLength for them.
- If a code is unknown we return `UNKNOWN(<code>)` so the data still flows
  into SCION without blowing up the ingest pipeline; the Graph page will
  display it as "unclassified" (amber-dashed), same behaviour we already
  have for parser-only imports.
"""

from dataclasses import dataclass
from typing import Optional


# ──── Type-code → human family lookup ────
# Organized so additions are trivial. The tuple is (family, base_name):
#   - family tells the formatter how to assemble size/scale info
#   - base_name is what ends up in the canonical string
TYPE_CODE_MAP: dict[str, tuple[str, str]] = {
    # Integer family — size is fixed, no parentheses
    "I1": ("fixed", "BYTEINT"),
    "I2": ("fixed", "SMALLINT"),
    "I":  ("fixed", "INTEGER"),
    "I8": ("fixed", "BIGINT"),

    # Decimal / numeric — (precision, scale)
    "D":  ("decimal", "DECIMAL"),
    "N":  ("decimal", "NUMBER"),

    # Floating point — fixed, no size
    "F":  ("fixed", "FLOAT"),
    "R":  ("fixed", "REAL"),  # Teradata historically uses F for REAL, R is fallback
    "FD": ("fixed", "DOUBLE PRECISION"),

    # Character family — VARCHAR(n) / CHAR(n), length in ColumnLength
    "CV": ("charlen", "VARCHAR"),
    "CF": ("charlen", "CHAR"),
    "CO": ("charlen", "CLOB"),  # Character LOB — length is in char units

    # Binary family
    "BV": ("charlen", "VARBYTE"),
    "BF": ("charlen", "BYTE"),
    "BO": ("charlen", "BLOB"),

    # Date / time — fixed
    "DA": ("fixed", "DATE"),
    "AT": ("timewithprec", "TIME"),
    "TS": ("timewithprec", "TIMESTAMP"),
    "TZ": ("timewithprec", "TIME WITH TIME ZONE"),
    "SZ": ("timewithprec", "TIMESTAMP WITH TIME ZONE"),

    # Intervals — no size in ColumnLength (encoded in the code itself)
    "YR": ("fixed", "INTERVAL YEAR"),
    "YM": ("fixed", "INTERVAL YEAR TO MONTH"),
    "MO": ("fixed", "INTERVAL MONTH"),
    "DY": ("fixed", "INTERVAL DAY"),
    "DH": ("fixed", "INTERVAL DAY TO HOUR"),
    "DM": ("fixed", "INTERVAL DAY TO MINUTE"),
    "DS": ("fixed", "INTERVAL DAY TO SECOND"),
    "HR": ("fixed", "INTERVAL HOUR"),
    "HM": ("fixed", "INTERVAL HOUR TO MINUTE"),
    "HS": ("fixed", "INTERVAL HOUR TO SECOND"),
    "MI": ("fixed", "INTERVAL MINUTE"),
    "MS": ("fixed", "INTERVAL MINUTE TO SECOND"),
    "SC": ("fixed", "INTERVAL SECOND"),

    # Period types — precision embedded
    "PD": ("fixed", "PERIOD(DATE)"),
    "PT": ("timewithprec", "PERIOD(TIME)"),
    "PZ": ("timewithprec", "PERIOD(TIME WITH TIME ZONE)"),
    "PS": ("timewithprec", "PERIOD(TIMESTAMP)"),
    "PM": ("timewithprec", "PERIOD(TIMESTAMP WITH TIME ZONE)"),

    # Complex / structured
    "JN": ("fixed", "JSON"),
    "XM": ("fixed", "XML"),
    "UT": ("fixed", "USER_DEFINED_TYPE"),
    "A1": ("fixed", "ARRAY"),
    "AN": ("fixed", "ARRAY"),  # Multi-dimensional
    "++": ("fixed", "TD_ANYTYPE"),
    "BO ": ("charlen", "BLOB"),  # trailing-space variant seen in some TD versions

    # Geospatial (Teradata 16+) — often represented as UDT but SCION wants
    # the explicit canonical for DDL generation.
    "GE": ("fixed", "ST_GEOMETRY"),
}


@dataclass(frozen=True)
class ColumnTypeInput:
    """Minimal struct used to feed the formatter.

    Mirrors the columns we consume from Rahul's `columnsv_full_export.sql`.
    Using a dataclass (instead of raw kwargs) makes it obvious at call
    sites what the required fields are, and makes testing easier.
    """
    column_type: str                           # ColumnType (e.g. "CV")
    column_length: Optional[int] = None        # ColumnLength
    decimal_total_digits: Optional[int] = None # DecimalTotalDigits
    decimal_fractional_digits: Optional[int] = None  # DecimalFractionalDigits
    char_type: Optional[int] = None            # 1=Latin, 2=Unicode, 3=Kanji, etc.


def format_column_type(spec: ColumnTypeInput) -> str:
    """Return the canonical SQL string for one Teradata column.

    Examples:
        ColumnType="CV", ColumnLength=255         → "VARCHAR(255)"
        ColumnType="D", TotalDigits=18, Frac=2    → "DECIMAL(18,2)"
        ColumnType="TS"                           → "TIMESTAMP"
        ColumnType="TS", ColumnLength=6           → "TIMESTAMP(6)"
        ColumnType="DA"                           → "DATE"
        ColumnType="XX" (unknown)                 → "UNKNOWN(XX)"

    The formatter is deliberately permissive — if a size field is missing
    for a type that would normally have one, we fall back to the base
    name rather than raise. SCION prefers "best-effort data in" over
    "pipeline failure" because anomalous rows are findable later via the
    diff engine; a crashed ingest isn't.
    """
    code = (spec.column_type or "").strip()
    entry = TYPE_CODE_MAP.get(code)
    if entry is None:
        return f"UNKNOWN({code or '?'})"

    family, base = entry

    if family == "fixed":
        return base

    if family == "decimal":
        p = spec.decimal_total_digits
        s = spec.decimal_fractional_digits
        if p is None:
            return base
        if s is None:
            return f"{base}({p})"
        return f"{base}({p},{s})"

    if family == "charlen":
        n = spec.column_length
        if n is None or n <= 0:
            return base
        # CharType=2 (Unicode) sometimes doubles the byte length at the
        # catalog level. We report declared character units directly —
        # that's what the DDL would say. If we ever need the byte-level
        # view, we'd add a separate formatter.
        return f"{base}({n})"

    if family == "timewithprec":
        # TIMESTAMP / TIME store fractional-seconds precision in ColumnLength.
        # Default (no length) means "TIMESTAMP" with implicit precision 6.
        n = spec.column_length
        if n is None or n <= 0:
            return base
        # Handle the compound "TIMESTAMP WITH TIME ZONE(n)" form cleanly.
        if "WITH TIME ZONE" in base:
            head, _, tail = base.partition(" WITH")
            return f"{head}({n}) WITH{tail}"
        if base.startswith("PERIOD("):
            # "PERIOD(TIMESTAMP)" + n → "PERIOD(TIMESTAMP(n))"
            return base.replace(")", f"({n}))", 1)
        return f"{base}({n})"

    # Defensive: should not be reachable given the map above.
    return base


def is_nullable(flag: Optional[str]) -> bool:
    """Convert DBC.ColumnsV `Nullable` ('Y'/'N') to a Python bool.

    Keeping this as a named helper (instead of inlining `flag == "Y"`)
    means the single place to handle future quirks — e.g. Teradata sometimes
    returns a trailing space or lowercase — is here.
    """
    if flag is None:
        return True  # assume permissive in absence of info
    return str(flag).strip().upper() == "Y"


def object_type_from_tablekind(kind: Optional[str]) -> str:
    """Map DBC.TablesV `TableKind` code to SCION's `object_type` enum.

    Reference: Teradata catalog docs, TableKind column. Only the codes
    we actually populate into SCION snapshots are listed; anything else
    becomes UNKNOWN so the Graph "unclassified" path (amber-dashed node,
    v1.05 feature) handles it uniformly.
    """
    k = (kind or "").strip().upper()
    return {
        "T": "TABLE",          # permanent table
        "O": "TABLE",          # NoPI table (object-variant) — still a TABLE
        "Q": "TABLE",          # queue table
        "V": "VIEW",
        "M": "MACRO",
        "P": "STORED_PROCEDURE",
        "E": "STORED_PROCEDURE",  # external stored procedure
        "F": "FUNCTION",
        "R": "FUNCTION",       # table function
        "A": "FUNCTION",       # aggregate UDF
        "B": "FUNCTION",       # combined UDF
        "I": "TRIGGER",
        "G": "TRIGGER",        # trigger (pre-v14 code)
        "N": "SEQUENCE",       # hash index — ~sequence-ish role
        "J": "TRIGGER",        # journal table
        "X": "INDEX",          # authorization
    }.get(k, "UNKNOWN")
