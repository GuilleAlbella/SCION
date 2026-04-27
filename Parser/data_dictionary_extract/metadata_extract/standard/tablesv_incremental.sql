select
    ?source_system_name_literal as source_system_name,
    ?extract_run_id_literal as extract_run_id,
    current_timestamp(6) as extracted_at_utc,
    cast(current_timestamp as date) as snapshot_date,
    hashrow(
        t.DatabaseName,
        t.TableName,
        t.TableKind,
        t.TVMId,
        t.CreatorName,
        t.CreateTimeStamp,
        t.LastAlterName,
        t.LastAlterTimeStamp,
        t.ProtectionType,
        t.JournalFlag,
        t.CheckOpt
    ) as row_hash,
    t.DatabaseName,
    t.TableName,
    t.TableKind,
    t.TVMId,
    t.CreatorName,
    t.CreateTimeStamp,
    t.LastAlterName,
    t.LastAlterTimeStamp,
    t.CommentString,
    t.ProtectionType,
    t.JournalFlag,
    t.CheckOpt
from DBC.TablesV t
where coalesce(t.LastAlterTimeStamp, t.CreateTimeStamp) >=
      to_timestamp('?watermark_ts', 'YYYY-MM-DD HH24:MI:SS')
order by t.DatabaseName, t.TableName;
