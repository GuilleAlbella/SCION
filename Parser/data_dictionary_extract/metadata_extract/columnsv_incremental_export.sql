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
    oreplace(coalesce(cast(hashrow(c.DatabaseName, c.TableName, c.ColumnName, c.ColumnId, c.ColumnType, c.ColumnLength, c.DecimalTotalDigits, c.DecimalFractionalDigits, c.Nullable, c.DefaultValue) as varchar(64)), ''), ?delimiter_literal, ?escaped_delimiter_literal) || ?delimiter_literal ||
    oreplace(coalesce(cast(c.DatabaseName as varchar(256)), ''), ?delimiter_literal, ?escaped_delimiter_literal) || ?delimiter_literal ||
    oreplace(coalesce(cast(c.TableName as varchar(256)), ''), ?delimiter_literal, ?escaped_delimiter_literal) || ?delimiter_literal ||
    oreplace(coalesce(cast(c.ColumnName as varchar(256)), ''), ?delimiter_literal, ?escaped_delimiter_literal) || ?delimiter_literal ||
    oreplace(coalesce(cast(c.ColumnId as varchar(64)), ''), ?delimiter_literal, ?escaped_delimiter_literal) || ?delimiter_literal ||
    oreplace(coalesce(cast(c.ColumnType as varchar(64)), ''), ?delimiter_literal, ?escaped_delimiter_literal) || ?delimiter_literal ||
    oreplace(coalesce(cast(c.ColumnLength as varchar(64)), ''), ?delimiter_literal, ?escaped_delimiter_literal) || ?delimiter_literal ||
    oreplace(coalesce(cast(c.DecimalTotalDigits as varchar(64)), ''), ?delimiter_literal, ?escaped_delimiter_literal) || ?delimiter_literal ||
    oreplace(coalesce(cast(c.DecimalFractionalDigits as varchar(64)), ''), ?delimiter_literal, ?escaped_delimiter_literal) || ?delimiter_literal ||
    oreplace(coalesce(cast(c.Nullable as varchar(64)), ''), ?delimiter_literal, ?escaped_delimiter_literal) || ?delimiter_literal ||
    oreplace(coalesce(cast(c.DefaultValue as varchar(4000)), ''), ?delimiter_literal, ?escaped_delimiter_literal) || ?delimiter_literal ||
    oreplace(coalesce(cast(c.Format as varchar(1000)), ''), ?delimiter_literal, ?escaped_delimiter_literal) || ?delimiter_literal ||
    oreplace(coalesce(cast(c.Title as varchar(1000)), ''), ?delimiter_literal, ?escaped_delimiter_literal) || ?delimiter_literal ||
    oreplace(coalesce(cast(c.CharType as varchar(64)), ''), ?delimiter_literal, ?escaped_delimiter_literal) || ?delimiter_literal ||
    oreplace(coalesce(cast(c.CaseSpecific as varchar(64)), ''), ?delimiter_literal, ?escaped_delimiter_literal) || ?record_terminator_literal as metadata_record
from DBC.ColumnsV c
join changed_tables t
    on c.DatabaseName = t.DatabaseName
   and c.TableName = t.TableName
order by c.DatabaseName, c.TableName, c.ColumnId;
