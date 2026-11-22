-- Grain: month x segment x circle.
-- ARPU is CASH-BASIS: successful recharge / bill payments in the month divided by
-- subscribers active at any point in the month. Prepaid packs longer than 28 days make
-- month-to-month ARPU lumpy; that is expected for cash-basis reporting.
with months as (
    select distinct month_start
    from {{ ref('dim_date') }}
    where date_day between date('{{ var("data_start_date") }}') and date('{{ var("data_end_date") }}')
),

subs as (
    select
        m.month_start,
        c.segment,
        c.circle,
        count(*) as active_subscribers
    from months as m
    inner join {{ ref('dim_customer') }} as c
        on c.signup_date <= last_day(m.month_start, month)
       and (c.disconnect_date is null or c.disconnect_date >= m.month_start)
    group by 1, 2, 3
),

rev as (
    select
        date_trunc(r.recharge_date, month) as month_start,
        c.segment,
        c.circle,
        sum(r.revenue_inr)          as revenue_inr,
        countif(r.is_paid)          as paid_transactions,
        countif(not r.is_paid)      as failed_transactions
    from {{ ref('fct_recharge') }} as r
    inner join {{ ref('dim_customer') }} as c
        on r.customer_id = c.customer_id
    group by 1, 2, 3
)

select
    s.month_start,
    s.segment,
    s.circle,
    s.active_subscribers,
    coalesce(r.revenue_inr, 0)                                  as revenue_inr,
    round(safe_divide(r.revenue_inr, s.active_subscribers), 2)  as arpu_inr,
    coalesce(r.paid_transactions, 0)                            as paid_transactions,
    coalesce(r.failed_transactions, 0)                          as failed_transactions,
    safe_divide(r.failed_transactions, r.paid_transactions + r.failed_transactions) as payment_failure_rate
from subs as s
left join rev as r
    using (month_start, segment, circle)
