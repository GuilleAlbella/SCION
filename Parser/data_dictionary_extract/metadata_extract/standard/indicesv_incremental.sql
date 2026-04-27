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
        i.DatabaseName,
        i.TableName,
        i.IndexNumber,
        i.ColumnPosition,
        i.IndexType,
        i.UniqueFlag,
        i.PrimaryKeyFlag,
        i.ColumnName
    ) as row_hash,
    i.DatabaseName,
    i.TableName,
    i.IndexName,
    i.IndexNumber,
    i.IndexType,
    i.UniqueFlag,
    i.PrimaryKeyFlag,
    i.ColumnName,
    i.ColumnPosition,
    i.Ordering,
    i.ConstraintName
from DBC.IndicesV i
join changed_tables t
    on i.DatabaseName = t.DatabaseName
   and i.TableName = t.TableName
order by i.DatabaseName, i.TableName, i.IndexNumber, i.ColumnPosition;
