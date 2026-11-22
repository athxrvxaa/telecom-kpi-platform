select * from {{ ref('kpi_monthly_churn') }}
where churn_rate < 0 or churn_rate > 1
   or closing_subscribers < 0
