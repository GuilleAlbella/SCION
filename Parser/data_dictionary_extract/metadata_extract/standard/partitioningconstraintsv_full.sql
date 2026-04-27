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
order by p.DatabaseName, p.TableName, p.ConstraintName;
