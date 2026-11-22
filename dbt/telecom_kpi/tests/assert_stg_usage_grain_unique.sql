-- One row per customer per day.
select customer_id, usage_date, count(*) as n
from {{ ref('stg_usage_daily') }}
group by customer_id, usage_date
having count(*) > 1
