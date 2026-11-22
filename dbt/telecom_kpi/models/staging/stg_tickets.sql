-- Grain: one row per support ticket.
-- Fixes (rows excluded): null / orphan customer_id, closed_ts earlier than opened_ts.
-- Timestamps are wrapped in TIMESTAMP() because Parquet naive timestamps load as DATETIME.
with typed as (

    select
        t.ticket_id,
        t.customer_id,
        timestamp(t.opened_ts) as opened_ts,
        timestamp(t.closed_ts) as closed_ts,
        t.category,
        t.priority,
        t.channel,
        t.status,
        t.csat_score
    from {{ source('raw', 'tickets') }} as t
    inner join {{ ref('stg_customers') }} as c
        on t.customer_id = c.customer_id

)

select
    *,
    timestamp_diff(closed_ts, opened_ts, minute) / 60.0 as resolution_hours
from typed
where closed_ts is null or closed_ts >= opened_ts
