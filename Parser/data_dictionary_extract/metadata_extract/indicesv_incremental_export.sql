with changed_tables as (
    select
        t.DatabaseName,
        t.TableName
    from DBC.TablesV t
    where coalesce(t.LastAlterTimeStamp, t.CreateTimeStamp) >=
          to_timestamp('?watermark_ts', 'YYYY-MM-DD HH24:MI:SS')
)
select
    oreplace(coalesce(cast(?source_system_name_literal as varchar(256)), ''), ?delimiter_literal, ?escaped_delimiter_literal) || ?delimiter_literal ||
    oreplace(coalesce(cast(?extract_run_id_literal as varchar(256)), ''), ?delimiter_literal, ?escaped_delimiter_literal) || ?delimiter_literal ||
    oreplace(coalesce(cast(current_timestamp(6) as varchar(64)), ''), ?delimiter_literal, ?escaped_delimiter_literal) || ?delimiter_literal ||
    oreplace(coalesce(cast(cast(current_timestamp as date) as varchar(32)), ''), ?delimiter_literal, ?escaped_delimiter_literal) || ?delimiter_literal ||
    oreplace(coalesce(cast(hashrow(i.DatabaseName, i.TableName, i.IndexNumber, i.ColumnPosition, i.IndexType, i.UniqueFlag, i.PrimaryKeyFlag, i.ColumnName) as varchar(64)), ''), ?delimiter_literal, ?escaped_delimiter_literal) || ?delimiter_literal ||
    oreplace(coalesce(cast(i.DatabaseName as varchar(256)), ''), ?delimiter_literal, ?escaped_delimiter_literal) || ?delimiter_literal ||
    oreplace(coalesce(cast(i.TableName as varchar(256)), ''), ?delimiter_literal, ?escaped_delimiter_literal) || ?delimiter_literal ||
    oreplace(coalesce(cast(i.IndexName as varchar(256)), ''), ?delimiter_literal, ?escaped_delimiter_literal) || ?delimiter_literal ||
    oreplace(coalesce(cast(i.IndexNumber as varchar(64)), ''), ?delimiter_literal, ?escaped_delimiter_literal) || ?delimiter_literal ||
    oreplace(coalesce(cast(i.IndexType as varchar(64)), ''), ?delimiter_literal, ?escaped_delimiter_literal) || ?delimiter_literal ||
    oreplace(coalesce(cast(i.UniqueFlag as varchar(64)), ''), ?delimiter_literal, ?escaped_delimiter_literal) || ?delimiter_literal ||
    oreplace(coalesce(cast(i.PrimaryKeyFlag as varchar(64)), ''), ?delimiter_literal, ?escaped_delimiter_literal) || ?delimiter_literal ||
    oreplace(coalesce(cast(i.ColumnName as varchar(256)), ''), ?delimiter_literal, ?escaped_delimiter_literal) || ?delimiter_literal ||
    oreplace(coalesce(cast(i.ColumnPosition as varchar(64)), ''), ?delimiter_literal, ?escaped_delimiter_literal) || ?delimiter_literal ||
    oreplace(coalesce(cast(i.Ordering as varchar(64)), ''), ?delimiter_literal, ?escaped_delimiter_literal) || ?delimiter_literal ||
    oreplace(coalesce(cast(i.ConstraintName as varchar(256)), ''), ?delimiter_literal, ?escaped_delimiter_literal) || ?record_terminator_literal as metadata_record
from DBC.IndicesV i
join changed_tables t
    on i.DatabaseName = t.DatabaseName
   and i.TableName = t.TableName
order by i.DatabaseName, i.TableName, i.IndexNumber, i.ColumnPosition;
