select *
from {{ ref('stg_usage_daily') }}
where data_mb < 0 or voice_minutes < 0 or sms_count < 0
