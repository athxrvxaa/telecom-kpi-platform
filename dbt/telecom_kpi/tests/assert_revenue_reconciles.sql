-- Total revenue in the KPI table must equal total revenue in the fact table.
with f as (select sum(revenue_inr) as fact_revenue from {{ ref('fct_recharge') }}),
     k as (select sum(revenue_inr) as kpi_revenue  from {{ ref('kpi_monthly_arpu') }})
select * from f cross join k
where abs(fact_revenue - kpi_revenue) > 0.01
