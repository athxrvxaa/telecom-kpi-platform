-- Grain: one row per recharge / bill payment.
-- Fixes (rows excluded): orphan customer_id, non-positive amounts, future-dated rows.
select
    r.recharge_id,
    r.customer_id,
    r.recharge_date,
    r.amount_inr,
    r.channel,
    r.payment_status,
    r.payment_status = 'Paid' as is_paid
from {{ source('raw', 'recharges') }} as r
inner join {{ ref('stg_customers') }} as c
    on r.customer_id = c.customer_id
where r.amount_inr > 0
  and r.recharge_date <= date('{{ var("data_end_date") }}')
