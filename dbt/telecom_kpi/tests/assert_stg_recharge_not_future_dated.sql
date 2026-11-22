select *
from {{ ref('stg_recharges') }}
where recharge_date > date('{{ var("data_end_date") }}')
