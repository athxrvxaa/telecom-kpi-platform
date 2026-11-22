-- Business rule table: resolution-time targets by ticket priority.
select * from unnest([
    struct('P1' as priority, 4  as sla_hours, 'Critical' as priority_label),
    struct('P2', 24, 'High'),
    struct('P3', 72, 'Normal')
])
