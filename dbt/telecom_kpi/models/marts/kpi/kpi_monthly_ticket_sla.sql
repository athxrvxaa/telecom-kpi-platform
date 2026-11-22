-- Grain: month opened x priority x category x segment.
-- sla_compliance_rate counts still-open tickets past their target as breaches.
select
    date_trunc(t.opened_date, month)                        as month_start,
    t.priority,
    t.category,
    c.segment,
    count(*)                                                as tickets,
    countif(t.status = 'Closed')                            as closed_tickets,
    countif(t.status = 'Open')                              as open_tickets,
    countif(t.is_sla_breached)                              as sla_breached_tickets,
    round(1 - safe_divide(countif(t.is_sla_breached), count(*)), 4) as sla_compliance_rate,
    round(avg(t.resolution_hours), 2)                       as avg_resolution_hours,
    round(avg(t.csat_score), 2)                             as avg_csat,
    count(t.csat_score)                                     as csat_responses
from {{ ref('fct_ticket') }} as t
inner join {{ ref('dim_customer') }} as c
    on t.customer_id = c.customer_id
group by 1, 2, 3, 4
