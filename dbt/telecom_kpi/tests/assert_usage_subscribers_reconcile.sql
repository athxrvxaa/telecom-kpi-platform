-- Usage KPI subscriber-days must equal fact rows.
with k as (select sum(subscriber_days) as kpi_days from {{ ref('kpi_monthly_usage') }}),
     f as (select count(*) as fact_days from {{ ref('fct_usage_daily') }})
select * from k cross join f where kpi_days != fact_days
