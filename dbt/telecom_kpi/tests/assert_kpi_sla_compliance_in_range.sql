select * from {{ ref('kpi_monthly_ticket_sla') }}
where sla_compliance_rate < 0 or sla_compliance_rate > 1
