-- Grain: one row per customer, snapshotted at as_of_date:
--   churned customers -> their disconnect date (so we see behaviour BEFORE they left)
--   active customers  -> end of the data window
-- Used for churn-driver analysis in Power BI.
with base as (
    select
        customer_id, segment, circle, plan_id, age_band, device_type, tenure_band,
        signup_date, is_churned, disconnect_date,
        coalesce(disconnect_date, date('{{ var("data_end_date") }}')) as as_of_date
    from {{ ref('dim_customer') }}
),

usage as (
    select
        b.customer_id,
        sum(if(u.usage_date >= date_sub(b.as_of_date, interval 29 day), u.data_mb, 0))       as data_mb_last_30d,
        sum(if(u.usage_date <  date_sub(b.as_of_date, interval 29 day), u.data_mb, 0))       as data_mb_prev_30d,
        sum(if(u.usage_date >= date_sub(b.as_of_date, interval 29 day), u.voice_minutes, 0)) as voice_min_last_30d,
        sum(if(u.usage_date <  date_sub(b.as_of_date, interval 29 day), u.voice_minutes, 0)) as voice_min_prev_30d
    from base as b
    inner join {{ ref('fct_usage_daily') }} as u
        on u.customer_id = b.customer_id
    where u.usage_date between date_sub(b.as_of_date, interval 59 day) and b.as_of_date
    group by 1
),

recharge as (
    select
        b.customer_id,
        max(r.recharge_date) as last_recharge_date,
        count(*)             as paid_recharges_total
    from base as b
    inner join {{ ref('fct_recharge') }} as r
        on r.customer_id = b.customer_id
    where r.is_paid and r.recharge_date <= b.as_of_date
    group by 1
),

tickets as (
    select
        b.customer_id,
        countif(t.opened_date >= date_sub(b.as_of_date, interval 29 day))                         as tickets_last_30d,
        countif(t.opened_date >= date_sub(b.as_of_date, interval 29 day) and t.is_sla_breached)   as sla_breaches_last_30d
    from base as b
    inner join {{ ref('fct_ticket') }} as t
        on t.customer_id = b.customer_id
    where t.opened_date <= b.as_of_date
    group by 1
)

select
    b.*,
    coalesce(u.data_mb_last_30d, 0)   as data_mb_last_30d,
    coalesce(u.data_mb_prev_30d, 0)   as data_mb_prev_30d,
    round(safe_divide(u.data_mb_last_30d - u.data_mb_prev_30d, u.data_mb_prev_30d), 4) as data_usage_change_pct,
    coalesce(u.voice_min_last_30d, 0) as voice_min_last_30d,
    coalesce(u.voice_min_prev_30d, 0) as voice_min_prev_30d,
    r.last_recharge_date,
    date_diff(b.as_of_date, r.last_recharge_date, day) as days_since_last_recharge,
    coalesce(r.paid_recharges_total, 0)   as paid_recharges_total,
    coalesce(t.tickets_last_30d, 0)       as tickets_last_30d,
    coalesce(t.sla_breaches_last_30d, 0)  as sla_breaches_last_30d
from base as b
left join usage    as u on u.customer_id = b.customer_id
left join recharge as r on r.customer_id = b.customer_id
left join tickets  as t on t.customer_id = b.customer_id
