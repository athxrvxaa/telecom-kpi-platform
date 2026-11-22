-- Run these ONE AT A TIME in BigQuery Studio (select the statement, then Run).

-- 1) Run the procedure for the whole data window.
CALL `telecom-kpi-platform-515209.marts.sp_refresh_daily_kpis`(DATE '2026-05-01', DATE '2026-10-31');

-- 2) Check the run log (status should be SUCCESS).
SELECT * FROM `telecom-kpi-platform-515209.marts.etl_run_log`;

-- 3) Sanity-check the output.
--    Expected: 3,680 rows (184 days x 2 segments x 10 circles).
SELECT
  COUNT(*)                         AS row_count,
  COUNT(DISTINCT date_day)         AS days,
  ROUND(SUM(revenue_inr), 2)       AS revenue_inr,
  ROUND(SUM(data_gb), 1)           AS data_gb,
  SUM(disconnects)                 AS disconnects
FROM `telecom-kpi-platform-515209.marts.agg_daily_kpis`;

-- 4) Negative test: the ASSERT should FAIL this call with the message
--    "p_start_date must be on or before p_end_date". A failing call is the expected result.
CALL `telecom-kpi-platform-515209.marts.sp_refresh_daily_kpis`(DATE '2026-10-31', DATE '2026-05-01');

-- 5) The failed call must not have damaged anything: re-run query 3 and the numbers should be unchanged.
