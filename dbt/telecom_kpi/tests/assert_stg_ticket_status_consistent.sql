-- Open tickets have no closed_ts; closed tickets always do.
select *
from {{ ref('stg_tickets') }}
where (status = 'Open'   and closed_ts is not null)
   or (status = 'Closed' and closed_ts is null)
