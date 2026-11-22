-- Grain: one row per customer.
-- Fixes: duplicate customer rows, inconsistent circle casing/whitespace, null age_band.
with source as (

    select * from {{ source('raw', 'customers') }}
    where customer_id is not null

),

cleaned as (

    select
        customer_id,
        segment,
        plan_id,
        signup_date,
        initcap(trim(circle))           as circle,
        coalesce(age_band, 'Unknown')   as age_band,
        device_type,
        acquisition_channel,
        disconnect_date,
        status,
        status = 'Disconnected'         as is_churned
    from source

)

select * from cleaned
-- If a customer appears twice, keep the copy that has a known age_band.
qualify row_number() over (
    partition by customer_id
    order by (age_band = 'Unknown'), signup_date
) = 1
