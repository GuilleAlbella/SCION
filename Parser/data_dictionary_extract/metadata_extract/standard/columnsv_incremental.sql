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
        c.DatabaseName,
        c.TableName,
        c.ColumnName,
        c.ColumnId,
        c.ColumnType,
        c.ColumnLength,
        c.DecimalTotalDigits,
        c.DecimalFractionalDigits,
        c.Nullable,
        c.DefaultValue
    ) as row_hash,
    c.DatabaseName,
    c.TableName,
    c.ColumnName,
    c.ColumnId,
    c.ColumnType,
    c.ColumnLength,
    c.DecimalTotalDigits,
    c.DecimalFractionalDigits,
    c.Nullable,
    c.DefaultValue,
    c.Format,
    c.Title,
    c.CharType,
    c.CaseSpecific
from DBC.ColumnsV c
join changed_tables t
    on c.DatabaseName = t.DatabaseName
   and c.TableName = t.TableName
order by c.DatabaseName, c.TableName, c.ColumnId;
