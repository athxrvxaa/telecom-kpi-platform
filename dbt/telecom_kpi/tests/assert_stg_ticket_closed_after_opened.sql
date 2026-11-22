select *
from {{ ref('stg_tickets') }}
where closed_ts < opened_ts
