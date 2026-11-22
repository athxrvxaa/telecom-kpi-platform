-- Grain: one row per customer per day.
-- Fixes: duplicate customer-days, negative data_mb (rows quarantined = excluded).
-- Not date-partitioned: see README ("Sandbox design decisions").
{{ config(cluster_by=['customer_id']) }}

with deduped as (

    select
        customer_id,
        usage_date,
        data_mb,
        voice_minutes,
        sms_count,
        roaming_flag
    from {{ source('raw', 'usage_daily') }}
    where customer_id is not null
    -- Prefer the non-negative copy when a duplicate pair disagrees.
    qualify row_number() over (
        partition by customer_id, usage_date
        order by data_mb desc
    ) = 1

)

select * from deduped
where data_mb >= 0
