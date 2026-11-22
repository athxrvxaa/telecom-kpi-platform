select
    customer_id,
    segment,
    plan_id,
    signup_date,
    date_trunc(signup_date, month)  as signup_month,
    circle,
    age_band,
    device_type,
    acquisition_channel,
    disconnect_date,
    status,
    is_churned,
    date_diff(coalesce(disconnect_date, date('{{ var("data_end_date") }}')), signup_date, day) as tenure_days,
    case
        when date_diff(coalesce(disconnect_date, date('{{ var("data_end_date") }}')), signup_date, day) < 90  then '0-3 months'
        when date_diff(coalesce(disconnect_date, date('{{ var("data_end_date") }}')), signup_date, day) < 365 then '3-12 months'
        when date_diff(coalesce(disconnect_date, date('{{ var("data_end_date") }}')), signup_date, day) < 730 then '1-2 years'
        else '2+ years'
    end as tenure_band
from {{ ref('stg_customers') }}
