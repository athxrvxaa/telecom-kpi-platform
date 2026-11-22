-- Grain: month x segment x circle.
-- churn_rate = disconnects in month / (opening subscribers + gross adds in month).
with months as (
    select distinct month_start
    from {{ ref('dim_date') }}
    where date_day between date('{{ var("data_start_date") }}') and date('{{ var("data_end_date") }}')
)

select
    m.month_start,
    c.segment,
    c.circle,
    countif(c.signup_date < m.month_start
            and (c.disconnect_date is null or c.disconnect_date >= m.month_start)) as opening_subscribers,
    countif(c.signup_date between m.month_start and last_day(m.month_start, month)) as gross_adds,
    countif(c.disconnect_date between m.month_start and last_day(m.month_start, month)) as churned_subscribers,
    countif(c.signup_date <= last_day(m.month_start, month)
            and (c.disconnect_date is null or c.disconnect_date > last_day(m.month_start, month))) as closing_subscribers,
    round(safe_divide(
        countif(c.disconnect_date between m.month_start and last_day(m.month_start, month)),
        countif(c.signup_date < m.month_start
                and (c.disconnect_date is null or c.disconnect_date >= m.month_start))
        + countif(c.signup_date between m.month_start and last_day(m.month_start, month))
    ), 4) as churn_rate
from months as m
cross join {{ ref('dim_customer') }} as c
group by 1, 2, 3
