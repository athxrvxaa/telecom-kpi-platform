-- Grain: customer x day. Clustered by customer_id (date partitioning skipped in sandbox).
{{ config(cluster_by=['customer_id']) }}
select
    customer_id,
    usage_date,
    cast(format_date('%Y%m%d', usage_date) as int64) as date_key,
    data_mb,
    round(data_mb / 1024, 4) as data_gb,
    voice_minutes,
    sms_count,
    roaming_flag
from {{ ref('stg_usage_daily') }}
