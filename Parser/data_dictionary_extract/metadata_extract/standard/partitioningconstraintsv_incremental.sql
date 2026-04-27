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
        p.DatabaseName,
        p.TableName,
        p.ConstraintName,
        p.ConstraintType,
        p.ConstraintText,
        p.CreateTimeStamp,
        p.LastAlterTimeStamp
    ) as row_hash,
    p.DatabaseName,
    p.TableName,
    p.ConstraintName,
    p.ConstraintType,
    p.ConstraintText,
    p.CreateTimeStamp,
    p.LastAlterTimeStamp
from DBC.PartitioningConstraintsV p
join changed_tables t
    on p.DatabaseName = t.DatabaseName
   and p.TableName = t.TableName
order by p.DatabaseName, p.TableName, p.ConstraintName;
