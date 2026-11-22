-- Counts every defect type in the RAW layer.
-- `manifest_key` matches the keys in data/raw/_injected_issues.json, so you can
-- reconcile "defects injected" vs "defects detected" line by line.
with cust as (select * from {{ source('raw', 'customers') }}),
     usage as (select customer_id, usage_date, data_mb from {{ source('raw', 'usage_daily') }}),
     rech as (select * from {{ source('raw', 'recharges') }}),
     tick as (select * from {{ source('raw', 'tickets') }})

select 'customers_duplicate_rows' as manifest_key, 'customers' as table_name,
       (select count(*) - count(distinct customer_id) from cust) as defects_detected
union all
select 'customers_inconsistent_circle_casing', 'customers',
       (select count(*) from cust where circle != initcap(trim(circle)))
union all
select 'customers_null_age_band', 'customers',
       (select count(*) from cust where age_band is null)
union all
select 'usage_duplicate_rows', 'usage_daily',
       (select count(*) - count(distinct concat(customer_id, '|', cast(usage_date as string))) from usage)
union all
select 'usage_negative_data_mb', 'usage_daily',
       (select count(*) from usage where data_mb < 0)
union all
select 'recharges_orphan_customer_id', 'recharges',
       (select count(*) from rech as r
        where not exists (select 1 from cust as c where c.customer_id = r.customer_id))
union all
select 'recharges_zero_amount', 'recharges',
       (select count(*) from rech where amount_inr <= 0)
union all
select 'recharges_future_dated', 'recharges',
       (select count(*) from rech where recharge_date > date('{{ var("data_end_date") }}'))
union all
select 'tickets_null_customer_id', 'tickets',
       (select count(*) from tick where customer_id is null)
union all
select 'tickets_closed_before_opened', 'tickets',
       (select count(*) from tick where closed_ts < opened_ts)
