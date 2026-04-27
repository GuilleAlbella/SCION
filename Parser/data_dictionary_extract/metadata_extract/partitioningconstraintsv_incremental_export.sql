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
    oreplace(coalesce(cast(hashrow(p.DatabaseName, p.TableName, p.ConstraintName, p.ConstraintType, p.ConstraintText, p.CreateTimeStamp, p.LastAlterTimeStamp) as varchar(64)), ''), ?delimiter_literal, ?escaped_delimiter_literal) || ?delimiter_literal ||
    oreplace(coalesce(cast(p.DatabaseName as varchar(256)), ''), ?delimiter_literal, ?escaped_delimiter_literal) || ?delimiter_literal ||
    oreplace(coalesce(cast(p.TableName as varchar(256)), ''), ?delimiter_literal, ?escaped_delimiter_literal) || ?delimiter_literal ||
    oreplace(coalesce(cast(p.ConstraintName as varchar(256)), ''), ?delimiter_literal, ?escaped_delimiter_literal) || ?delimiter_literal ||
    oreplace(coalesce(cast(p.ConstraintType as varchar(64)), ''), ?delimiter_literal, ?escaped_delimiter_literal) || ?delimiter_literal ||
    oreplace(coalesce(cast(p.ConstraintText as varchar(64000)), ''), ?delimiter_literal, ?escaped_delimiter_literal) || ?delimiter_literal ||
    oreplace(coalesce(cast(p.CreateTimeStamp as varchar(64)), ''), ?delimiter_literal, ?escaped_delimiter_literal) || ?delimiter_literal ||
    oreplace(coalesce(cast(p.LastAlterTimeStamp as varchar(64)), ''), ?delimiter_literal, ?escaped_delimiter_literal) || ?record_terminator_literal as metadata_record
from DBC.PartitioningConstraintsV p
join changed_tables t
    on p.DatabaseName = t.DatabaseName
   and p.TableName = t.TableName
order by p.DatabaseName, p.TableName, p.ConstraintName;
