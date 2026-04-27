select
    ?source_system_name_literal as source_system_name,
    ?extract_run_id_literal as extract_run_id,
    current_timestamp(6) as extracted_at_utc,
    cast(current_timestamp as date) as snapshot_date,
    hashrow(
        d.DatabaseName,
        d.OwnerName,
        d.CreatorName,
        d.CreateTimeStamp,
        d.LastAlterName,
        d.LastAlterTimeStamp,
        d.PermSpace,
        d.SpoolSpace,
        d.TempSpace
    ) as row_hash,
    d.DatabaseName,
    d.OwnerName,
    d.CreatorName,
    d.CreateTimeStamp,
    d.LastAlterName,
    d.LastAlterTimeStamp,
    d.CommentString,
    d.PermSpace,
    d.SpoolSpace,
    d.TempSpace,
    d.CurrentPerm,
    d.PeakPerm
from DBC.DatabasesV d
where coalesce(d.LastAlterTimeStamp, d.CreateTimeStamp) >=
      to_timestamp('?watermark_ts', 'YYYY-MM-DD HH24:MI:SS')
order by d.DatabaseName;
