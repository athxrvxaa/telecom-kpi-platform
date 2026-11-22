with a as (select count(*) as n_360 from {{ ref('mart_customer_360') }}),
     b as (select count(*) as n_dim from {{ ref('dim_customer') }})
select * from a cross join b where n_360 != n_dim
