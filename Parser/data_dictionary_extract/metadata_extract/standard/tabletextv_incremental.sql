with changed_tables as (
    select
        t.DatabaseName,
        t.TableName
    from DBC.TablesV t
    where coalesce(t.LastAlterTimeStamp, t.CreateTimeStamp) >=
          to_timestamp('?watermark_ts', 'YYYY-MM-DD HH24:MI:SS')
)
select
    ?source_system_name_literal as source_system_name,
    ?extract_run_id_literal as extract_run_id,
    current_timestamp(6) as extracted_at_utc,
    cast(current_timestamp as date) as snapshot_date,
    hashrow(
        tt.DatabaseName,
        tt.TableName,
        tt.TableKind,
        tt.RequestTextSeq,
        tt.RequestText
    ) as row_hash,
    tt.DatabaseName,
    tt.TableName,
    tt.TableKind,
    tt.RequestTextSeq,
    tt.RequestText
from DBC.TableTextV tt
join changed_tables t
    on tt.DatabaseName = t.DatabaseName
   and tt.TableName = t.TableName
order by tt.DatabaseName, tt.TableName, tt.RequestTextSeq;
