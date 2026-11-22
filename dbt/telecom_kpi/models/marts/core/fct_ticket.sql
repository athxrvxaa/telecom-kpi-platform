-- Grain: one support ticket.
-- is_sla_breached: closed tickets -> resolution time over target;
--                  still-open tickets -> time open at the end of the data window over target.
{%- set end_ts = "timestamp(date_add(date('" ~ var('data_end_date') ~ "'), interval 1 day))" %}
select
    t.ticket_id,
    t.customer_id,
    t.opened_ts,
    t.closed_ts,
    date(t.opened_ts)                                           as opened_date,
    cast(format_date('%Y%m%d', date(t.opened_ts)) as int64)     as opened_date_key,
    t.category,
    t.priority,
    t.channel,
    t.status,
    t.csat_score,
    t.resolution_hours,
    s.sla_hours,
    case
        when t.status = 'Closed' then t.resolution_hours > s.sla_hours
        else timestamp_diff({{ end_ts }}, t.opened_ts, minute) / 60.0 > s.sla_hours
    end as is_sla_breached
from {{ ref('stg_tickets') }} as t
left join {{ ref('dim_sla_target') }} as s
    on t.priority = s.priority
