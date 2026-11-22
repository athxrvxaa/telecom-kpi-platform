select *
from {{ ref('stg_customers') }}
where disconnect_date is not null and disconnect_date < signup_date
