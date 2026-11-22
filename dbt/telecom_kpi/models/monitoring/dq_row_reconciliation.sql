-- Raw vs staging row counts: shows how many rows each cleaning step removed.
select 'customers' as table_name,
       (select count(*) from {{ source('raw', 'customers') }}) as raw_rows,
       (select count(*) from {{ ref('stg_customers') }})       as staging_rows
union all
select 'usage_daily',
       (select count(*) from {{ source('raw', 'usage_daily') }}),
       (select count(*) from {{ ref('stg_usage_daily') }})
union all
select 'recharges',
       (select count(*) from {{ source('raw', 'recharges') }}),
       (select count(*) from {{ ref('stg_recharges') }})
union all
select 'tickets',
       (select count(*) from {{ source('raw', 'tickets') }}),
       (select count(*) from {{ ref('stg_tickets') }})
