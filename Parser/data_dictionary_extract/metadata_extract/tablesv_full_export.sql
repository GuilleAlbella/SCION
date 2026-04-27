select
    oreplace(coalesce(cast(?source_system_name_literal as varchar(256)), ''), ?delimiter_literal, ?escaped_delimiter_literal) || ?delimiter_literal ||
    oreplace(coalesce(cast(?extract_run_id_literal as varchar(256)), ''), ?delimiter_literal, ?escaped_delimiter_literal) || ?delimiter_literal ||
    oreplace(coalesce(cast(current_timestamp(6) as varchar(64)), ''), ?delimiter_literal, ?escaped_delimiter_literal) || ?delimiter_literal ||
    oreplace(coalesce(cast(cast(current_timestamp as date) as varchar(32)), ''), ?delimiter_literal, ?escaped_delimiter_literal) || ?delimiter_literal ||
    oreplace(coalesce(cast(hashrow(t.DatabaseName, t.TableName, t.TableKind, t.TVMId, t.CreatorName, t.CreateTimeStamp, t.LastAlterName, t.LastAlterTimeStamp, t.ProtectionType, t.JournalFlag, t.CheckOpt) as varchar(64)), ''), ?delimiter_literal, ?escaped_delimiter_literal) || ?delimiter_literal ||
    oreplace(coalesce(cast(t.DatabaseName as varchar(256)), ''), ?delimiter_literal, ?escaped_delimiter_literal) || ?delimiter_literal ||
    oreplace(coalesce(cast(t.TableName as varchar(256)), ''), ?delimiter_literal, ?escaped_delimiter_literal) || ?delimiter_literal ||
    oreplace(coalesce(cast(t.TableKind as varchar(32)), ''), ?delimiter_literal, ?escaped_delimiter_literal) || ?delimiter_literal ||
    oreplace(coalesce(cast(t.TVMId as varchar(64)), ''), ?delimiter_literal, ?escaped_delimiter_literal) || ?delimiter_literal ||
    oreplace(coalesce(cast(t.CreatorName as varchar(256)), ''), ?delimiter_literal, ?escaped_delimiter_literal) || ?delimiter_literal ||
    oreplace(coalesce(cast(t.CreateTimeStamp as varchar(64)), ''), ?delimiter_literal, ?escaped_delimiter_literal) || ?delimiter_literal ||
    oreplace(coalesce(cast(t.LastAlterName as varchar(256)), ''), ?delimiter_literal, ?escaped_delimiter_literal) || ?delimiter_literal ||
    oreplace(coalesce(cast(t.LastAlterTimeStamp as varchar(64)), ''), ?delimiter_literal, ?escaped_delimiter_literal) || ?delimiter_literal ||
    oreplace(coalesce(cast(t.CommentString as varchar(2000)), ''), ?delimiter_literal, ?escaped_delimiter_literal) || ?delimiter_literal ||
    oreplace(coalesce(cast(t.ProtectionType as varchar(64)), ''), ?delimiter_literal, ?escaped_delimiter_literal) || ?delimiter_literal ||
    oreplace(coalesce(cast(t.JournalFlag as varchar(64)), ''), ?delimiter_literal, ?escaped_delimiter_literal) || ?delimiter_literal ||
    oreplace(coalesce(cast(t.CheckOpt as varchar(64)), ''), ?delimiter_literal, ?escaped_delimiter_literal) || ?record_terminator_literal as metadata_record
from DBC.TablesV t
order by t.DatabaseName, t.TableName;
