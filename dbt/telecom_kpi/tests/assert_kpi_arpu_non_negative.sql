select * from {{ ref('kpi_monthly_arpu') }}
where arpu_inr < 0 or revenue_inr < 0 or active_subscribers <= 0
