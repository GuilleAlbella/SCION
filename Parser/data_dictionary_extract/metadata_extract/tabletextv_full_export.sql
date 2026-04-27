select
    oreplace(coalesce(cast(?source_system_name_literal as varchar(256)), ''), ?delimiter_literal, ?escaped_delimiter_literal) || ?delimiter_literal ||
    oreplace(coalesce(cast(?extract_run_id_literal as varchar(256)), ''), ?delimiter_literal, ?escaped_delimiter_literal) || ?delimiter_literal ||
    oreplace(coalesce(cast(current_timestamp(6) as varchar(64)), ''), ?delimiter_literal, ?escaped_delimiter_literal) || ?delimiter_literal ||
    oreplace(coalesce(cast(cast(current_timestamp as date) as varchar(32)), ''), ?delimiter_literal, ?escaped_delimiter_literal) || ?delimiter_literal ||
    oreplace(coalesce(cast(hashrow(tt.DatabaseName, tt.TableName, tt.TableKind, tt.RequestTextSeq, tt.RequestText) as varchar(64)), ''), ?delimiter_literal, ?escaped_delimiter_literal) || ?delimiter_literal ||
    oreplace(coalesce(cast(tt.DatabaseName as varchar(256)), ''), ?delimiter_literal, ?escaped_delimiter_literal) || ?delimiter_literal ||
    oreplace(coalesce(cast(tt.TableName as varchar(256)), ''), ?delimiter_literal, ?escaped_delimiter_literal) || ?delimiter_literal ||
    oreplace(coalesce(cast(tt.TableKind as varchar(64)), ''), ?delimiter_literal, ?escaped_delimiter_literal) || ?delimiter_literal ||
    oreplace(coalesce(cast(tt.RequestTextSeq as varchar(64)), ''), ?delimiter_literal, ?escaped_delimiter_literal) || ?delimiter_literal ||
    oreplace(coalesce(cast(tt.RequestText as varchar(32000)), ''), ?delimiter_literal, ?escaped_delimiter_literal) || ?record_terminator_literal as metadata_record
from DBC.TableTextV tt
order by tt.DatabaseName, tt.TableName, tt.RequestTextSeq;
