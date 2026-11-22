with f as (select count(*) as fact_rows from {{ ref('fct_usage_daily') }}),
     s as (select count(*) as stg_rows  from {{ ref('stg_usage_daily') }})
select * from f cross join s where fact_rows != stg_rows
