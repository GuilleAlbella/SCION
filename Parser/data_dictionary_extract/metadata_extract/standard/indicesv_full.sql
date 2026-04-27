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
order by i.DatabaseName, i.TableName, i.IndexNumber, i.ColumnPosition;
