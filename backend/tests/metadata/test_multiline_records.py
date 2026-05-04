"""Regression test for multi-line records in 16-col flat-files.

Rahul's exporter terminates records with `\\n` and does NOT escape
literal newlines inside free-form fields. In Sample 1 that wasn't a
problem because no field had a newline. The first full
Transcend-DevTest extract (2.4 GB, sent 2026-05-04) tripped record
#15125 — `DBC.AccLogRule` (a system macro) has a multi-line
`CommentString`. The parser crashed with "got 12 fields" because the
record was split across multiple physical lines.

This test pins the recovery behaviour: the parser accumulates lines
until it has exactly 16 fields, then emits.
"""

from pathlib import Path

import pytest

from app.metadata.dict_flat_file_reader import (
    DictFlatFileError,
    read_tables,
)


# A single tables-view record where the CommentString contains an
# embedded newline. The 16 fields are:
#   1  source_system_name      = "Transcend-DevTest"
#   2  extract_run_id          = "RUN1"
#   3  extracted_at_utc        = "2026-05-04 08:20:40.000000-04:00"
#   4  snapshot_date           = "2026-05-04"
#   5  database_name           = "DBC"
#   6  table_name              = "AccLogRule"
#   7  table_kind              = "M"
#   8  creator_name            = "DBC"
#   9  create_timestamp        = "2026-04-11 12:55:20"
#   10 last_alter_name         = "DBC"
#   11 last_alter_timestamp    = "2026-04-11 12:55:20"
#   12 comment_string          = "Line 1 of comment\nLine 2 of comment"
#   13 protection_type         = "F"
#   14 journal_flag            = "NN"
#   15 check_opt               = "Y"
#   16 (blank filler)
_MULTILINE_RECORD = (
    "Transcend-DevTest§RUN1§2026-05-04 08:20:40.000000-04:00§"
    "2026-05-04§DBC§AccLogRule§M§DBC§2026-04-11 12:55:20§DBC§"
    "2026-04-11 12:55:20§Line 1 of comment\n"
    "Line 2 of comment§F§NN§Y§\n"
)

# A second record on the same file to verify the parser correctly
# resets state after emitting a multi-line record.
_NORMAL_RECORD = (
    "Transcend-DevTest§RUN1§2026-05-04 08:20:40.000000-04:00§"
    "2026-05-04§MYDB§my_table§T§MYDB§2026-04-11 12:55:20§MYDB§"
    "2026-04-11 12:55:20§Single-line comment§F§NN§Y§\n"
)


def test_read_tables_handles_embedded_newline_in_comment(tmp_path: Path) -> None:
    """The DBC.AccLogRule case from Rahul's full extract."""
    p = tmp_path / "tablesv_full.dat"
    p.write_text(_MULTILINE_RECORD + _NORMAL_RECORD, encoding="utf-8")

    rows = read_tables(p)

    assert len(rows) == 2

    first, second = rows
    assert first.database_name == "DBC"
    assert first.table_name == "AccLogRule"
    assert first.table_kind == "M"
    # The newline survives inside the comment — that's what the data
    # actually contained, and any downstream consumer that wants to
    # render single-line should normalise itself.
    assert first.comment_string == "Line 1 of comment\nLine 2 of comment"
    assert first.protection_type == "F"

    # Second record must come through cleanly — i.e. the parser reset
    # its buffer correctly after emitting the multi-line record.
    assert second.database_name == "MYDB"
    assert second.table_name == "my_table"
    assert second.comment_string == "Single-line comment"


def test_read_tables_rejects_truly_corrupt_record_too_many_fields(
    tmp_path: Path,
) -> None:
    """A record with > 16 fields is unrecoverable. Don't merge silently."""
    # 17 fields — one extra `§` smuggled in.
    bad_record = (
        "Transcend-DevTest§RUN1§2026-05-04 08:20:40.000000-04:00§"
        "2026-05-04§DBC§Tbl§T§DBC§2026-04-11 12:55:20§DBC§"
        "2026-04-11 12:55:20§Comment§F§NN§Y§§EXTRA\n"
    )
    p = tmp_path / "tablesv_bad.dat"
    p.write_text(bad_record, encoding="utf-8")

    with pytest.raises(DictFlatFileError) as exc:
        read_tables(p)
    msg = str(exc.value)
    assert "got 17" in msg or "17" in msg
    assert "tablesv_bad.dat" in msg


def test_read_tables_rejects_truncated_final_record(tmp_path: Path) -> None:
    """A short final record (file truncated) surfaces clearly, not silently."""
    # Only 8 fields, no trailing newline.
    truncated = "Transcend-DevTest§RUN1§2026-05-04 08:20:40.000000-04:00§2026-05-04§DBC§Tbl§T§DBC"
    p = tmp_path / "tablesv_truncated.dat"
    p.write_text(truncated, encoding="utf-8")

    with pytest.raises(DictFlatFileError) as exc:
        read_tables(p)
    msg = str(exc.value)
    assert "incomplete final record" in msg
    assert "tablesv_truncated.dat" in msg
