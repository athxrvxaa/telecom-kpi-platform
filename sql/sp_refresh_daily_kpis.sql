-- Phase 5: stored procedure that rebuilds the daily KPI aggregate and validates it.
--
-- Sandbox-friendly: uses CREATE OR REPLACE TABLE (DDL) instead of INSERT/MERGE (DML).
-- Re-running is safe (idempotent). ASSERT statements fail the call, and therefore the
-- orchestrating Airflow task, if the output does not reconcile with the fact tables.
--
-- Deploy: paste this whole file in BigQuery Studio and Run (creates/replaces the procedure).
-- Run   : see sql/run_and_verify.sql

CREATE OR REPLACE PROCEDURE `telecom-kpi-platform-515209.marts.sp_refresh_daily_kpis`(
  IN p_start_date DATE,
  IN p_end_date   DATE
)
BEGIN
  DECLARE v_rows         INT64;
  DECLARE v_fact_revenue FLOAT64;
  DECLARE v_agg_revenue  FLOAT64;
  DECLARE v_fact_data_gb FLOAT64;
  DECLARE v_agg_data_gb  FLOAT64;

  -- Input validation
  ASSERT p_start_date <= p_end_date AS 'p_start_date must be on or before p_end_date';

  -- Build the aggregate: one row per day x segment x circle
  CREATE OR REPLACE TABLE `telecom-kpi-platform-515209.marts.agg_daily_kpis`
  CLUSTER BY segment, circle
  AS
  WITH days AS (
    SELECT date_day
    FROM `telecom-kpi-platform-515209.marts.dim_date`
    WHERE date_day BETWEEN p_start_date AND p_end_date
  ),

  subs AS (
    SELECT
      d.date_day,
      c.segment,
      c.circle,
      COUNT(*)                                  AS active_subscribers,
      COUNTIF(c.disconnect_date = d.date_day)   AS disconnects,
      COUNTIF(c.signup_date = d.date_day)       AS gross_adds
    FROM days AS d
    INNER JOIN `telecom-kpi-platform-515209.marts.dim_customer` AS c
      ON  c.signup_date <= d.date_day
      AND (c.disconnect_date IS NULL OR c.disconnect_date >= d.date_day)
    GROUP BY 1, 2, 3
  ),

  usage AS (
    SELECT
      u.usage_date AS date_day,
      c.segment,
      c.circle,
      SUM(u.data_gb)       AS data_gb,
      SUM(u.voice_minutes) AS voice_minutes,
      SUM(u.sms_count)     AS sms_count,
      COUNT(*)             AS usage_records
    FROM `telecom-kpi-platform-515209.marts.fct_usage_daily` AS u
    INNER JOIN `telecom-kpi-platform-515209.marts.dim_customer` AS c
      ON u.customer_id = c.customer_id
    WHERE u.usage_date BETWEEN p_start_date AND p_end_date
    GROUP BY 1, 2, 3
  ),

  rev AS (
    SELECT
      r.recharge_date AS date_day,
      c.segment,
      c.circle,
      SUM(r.revenue_inr)         AS revenue_inr,
      COUNTIF(r.is_paid)         AS paid_transactions,
      COUNTIF(NOT r.is_paid)     AS failed_transactions
    FROM `telecom-kpi-platform-515209.marts.fct_recharge` AS r
    INNER JOIN `telecom-kpi-platform-515209.marts.dim_customer` AS c
      ON r.customer_id = c.customer_id
    WHERE r.recharge_date BETWEEN p_start_date AND p_end_date
    GROUP BY 1, 2, 3
  ),

  tix AS (
    SELECT
      t.opened_date AS date_day,
      c.segment,
      c.circle,
      COUNT(*)                    AS tickets_opened,
      COUNTIF(t.is_sla_breached)  AS tickets_sla_breached
    FROM `telecom-kpi-platform-515209.marts.fct_ticket` AS t
    INNER JOIN `telecom-kpi-platform-515209.marts.dim_customer` AS c
      ON t.customer_id = c.customer_id
    WHERE t.opened_date BETWEEN p_start_date AND p_end_date
    GROUP BY 1, 2, 3
  )

  SELECT
    s.date_day,
    s.segment,
    s.circle,
    s.active_subscribers,
    s.gross_adds,
    s.disconnects,
    COALESCE(u.data_gb, 0)              AS data_gb,
    COALESCE(u.voice_minutes, 0)        AS voice_minutes,
    COALESCE(u.sms_count, 0)            AS sms_count,
    COALESCE(u.usage_records, 0)        AS usage_records,
    COALESCE(r.revenue_inr, 0)          AS revenue_inr,
    COALESCE(r.paid_transactions, 0)    AS paid_transactions,
    COALESCE(r.failed_transactions, 0)  AS failed_transactions,
    COALESCE(t.tickets_opened, 0)       AS tickets_opened,
    COALESCE(t.tickets_sla_breached, 0) AS tickets_sla_breached
  FROM subs AS s
  LEFT JOIN usage AS u USING (date_day, segment, circle)
  LEFT JOIN rev   AS r USING (date_day, segment, circle)
  LEFT JOIN tix   AS t USING (date_day, segment, circle);

  -- Validation: output must reconcile with the fact tables, or the call fails.
  SET v_rows = (SELECT COUNT(*) FROM `telecom-kpi-platform-515209.marts.agg_daily_kpis`);
  ASSERT v_rows > 0 AS 'agg_daily_kpis is empty';

  SET v_fact_revenue = (
    SELECT IFNULL(SUM(revenue_inr), 0)
    FROM `telecom-kpi-platform-515209.marts.fct_recharge`
    WHERE recharge_date BETWEEN p_start_date AND p_end_date);
  SET v_agg_revenue = (SELECT IFNULL(SUM(revenue_inr), 0) FROM `telecom-kpi-platform-515209.marts.agg_daily_kpis`);
  ASSERT ABS(v_fact_revenue - v_agg_revenue) < 0.01
    AS 'Revenue in agg_daily_kpis does not reconcile with fct_recharge';

  SET v_fact_data_gb = (
    SELECT IFNULL(SUM(data_gb), 0)
    FROM `telecom-kpi-platform-515209.marts.fct_usage_daily`
    WHERE usage_date BETWEEN p_start_date AND p_end_date);
  SET v_agg_data_gb = (SELECT IFNULL(SUM(data_gb), 0) FROM `telecom-kpi-platform-515209.marts.agg_daily_kpis`);
  ASSERT ABS(v_fact_data_gb - v_agg_data_gb) < 1.0
    AS 'Data volume in agg_daily_kpis does not reconcile with fct_usage_daily';

  -- Run log (latest run only: sandbox has no INSERT, so this table is replaced each run)
  CREATE OR REPLACE TABLE `telecom-kpi-platform-515209.marts.etl_run_log` AS
  SELECT
    'sp_refresh_daily_kpis'  AS procedure_name,
    CURRENT_TIMESTAMP()      AS run_ts,
    p_start_date             AS start_date,
    p_end_date               AS end_date,
    v_rows                   AS rows_written,
    v_agg_revenue            AS revenue_inr_total,
    v_agg_data_gb            AS data_gb_total,
    'SUCCESS'                AS status;
END;
