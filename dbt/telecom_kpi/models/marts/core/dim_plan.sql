select
    plan_id,
    plan_name,
    plan_type,
    price_inr,
    validity_days,
    data_gb_total,
    round(price_inr / validity_days, 2) as price_per_day_inr
from {{ ref('stg_plans') }}
