-- Grain: month x segment x circle.
select
    date_trunc(u.usage_date, month)                       as month_start,
    c.segment,
    c.circle,
    round(sum(u.data_gb), 2)                              as total_data_gb,
    round(sum(u.voice_minutes), 0)                        as total_voice_minutes,
    sum(u.sms_count)                                      as total_sms,
    count(*)                                              as subscriber_days,
    count(distinct u.customer_id)                         as active_users,
    round(safe_divide(sum(u.data_mb), count(*)), 1)       as avg_data_mb_per_sub_day,
    round(safe_divide(sum(u.voice_minutes), count(*)), 1) as avg_voice_min_per_sub_day,
    countif(u.roaming_flag)                               as roaming_days
from {{ ref('fct_usage_daily') }} as u
inner join {{ ref('dim_customer') }} as c
    on u.customer_id = c.customer_id
group by 1, 2, 3
