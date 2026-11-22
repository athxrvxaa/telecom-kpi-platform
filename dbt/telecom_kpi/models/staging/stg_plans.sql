select
    plan_id,
    plan_name,
    plan_type,
    price_inr,
    validity_days,
    data_gb_total
from {{ source('raw', 'plans') }}
