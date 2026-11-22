-- Grain: one recharge / bill payment. revenue_inr counts only successful payments.
select
    recharge_id,
    customer_id,
    recharge_date,
    cast(format_date('%Y%m%d', recharge_date) as int64) as date_key,
    amount_inr,
    channel,
    payment_status,
    is_paid,
    if(is_paid, amount_inr, 0) as revenue_inr
from {{ ref('stg_recharges') }}
