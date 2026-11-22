select
    cast(format_date('%Y%m%d', d) as int64)  as date_key,
    d                                        as date_day,
    extract(year from d)                     as calendar_year,
    extract(quarter from d)                  as calendar_quarter,
    extract(month from d)                    as month_num,
    format_date('%b', d)                     as month_name,
    date_trunc(d, month)                     as month_start,
    date_trunc(d, week(monday))              as week_start,
    format_date('%A', d)                     as day_name,
    extract(dayofweek from d) in (1, 7)      as is_weekend
from unnest(generate_date_array(date '2023-01-01', date '2026-12-31')) as d
