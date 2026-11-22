select *
from {{ ref('stg_recharges') }}
where amount_inr <= 0
