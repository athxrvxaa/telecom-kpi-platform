"""
Telecom KPI pipeline: raw load -> source DQ -> dbt staging -> dbt marts -> stored procedure -> verify.

Every step is a shell command run inside the Airflow container. dbt and the BigQuery scripts
live in an isolated virtualenv (/home/airflow/dbt_venv) so their dependencies never clash with
Airflow's. The pipeline is idempotent (everything is rebuilt with CREATE OR REPLACE), which also
resets BigQuery sandbox's 60-day table expiry on every successful run.
"""
import os
from datetime import datetime, timedelta

# Imports that work on Airflow 3.x and fall back to 2.x.
try:
    from airflow.sdk import DAG
except ImportError:  # Airflow 2.x
    from airflow import DAG
try:
    from airflow.providers.standard.operators.bash import BashOperator
except ImportError:  # Airflow 2.x
    from airflow.operators.bash import BashOperator

PROJECT = os.environ.get("GCP_PROJECT", "telecom-kpi-platform-515209")
REPO = "/opt/airflow/project"
DBT_DIR = f"{REPO}/dbt/telecom_kpi"
VENV = "/home/airflow/dbt_venv/bin"

DBT_ENV = {
    "DBT_PROFILES_DIR": DBT_DIR,
    "DBT_LOG_PATH": "/tmp/dbt_logs",        # keep dbt output out of the mounted repo
    "DBT_TARGET_PATH": "/tmp/dbt_target",
    "DBT_SEND_ANONYMOUS_USAGE_STATS": "False",
}


def alert_on_failure(context):
    """Hook for alerting. Logs a clear message; swap in email/Slack for production."""
    ti = context["task_instance"]
    print(f"ALERT: task '{ti.task_id}' failed in DAG '{ti.dag_id}' (run {context.get('run_id')}). "
          f"Check the task log for the dbt/BigQuery error.")


default_args = {
    "owner": "data-analytics",
    "retries": 1,
    "retry_delay": timedelta(minutes=2),
    "on_failure_callback": alert_on_failure,
}

with DAG(
    dag_id="telecom_kpi_pipeline",
    description="Raw load -> dbt (staging, marts) -> stored procedure -> verification",
    default_args=default_args,
    schedule="0 6 * * *",              # daily 06:00
    start_date=datetime(2026, 11, 1),
    catchup=False,
    max_active_runs=1,
    dagrun_timeout=timedelta(hours=1),
    params={"start_date": "2026-05-01", "end_date": "2026-10-31"},
    tags=["telecom", "bigquery", "dbt"],
) as dag:

    load_raw = BashOperator(
        task_id="load_raw",
        bash_command=(f"{VENV}/python {REPO}/ingestion/load_to_bigquery.py "
                      f"--project {PROJECT} --data-dir {REPO}/data/raw"),
    )

    # Source tests are severity=warn: they record the defects found in raw without failing the run.
    dbt_test_sources = BashOperator(
        task_id="dbt_test_sources",
        bash_command=f"cd {DBT_DIR} && {VENV}/dbt test --select 'source:*'",
        env=DBT_ENV, append_env=True,
    )

    # `dbt build` = run + test per model; a failing test stops everything downstream.
    dbt_build_staging = BashOperator(
        task_id="dbt_build_staging",
        bash_command=f"cd {DBT_DIR} && {VENV}/dbt build --select staging",
        env=DBT_ENV, append_env=True,
    )

    dbt_build_marts = BashOperator(
        task_id="dbt_build_marts",
        bash_command=f"cd {DBT_DIR} && {VENV}/dbt build --select marts monitoring",
        env=DBT_ENV, append_env=True,
    )

    refresh_daily_kpis = BashOperator(
        task_id="refresh_daily_kpis",
        bash_command=(f"{VENV}/python {REPO}/ingestion/run_procedure.py --project {PROJECT} "
                      f"--sql {REPO}/sql/sp_refresh_daily_kpis.sql "
                      "--start {{ params.start_date }} --end {{ params.end_date }}"),
    )

    verify_run = BashOperator(
        task_id="verify_run",
        bash_command=f"{VENV}/python {REPO}/ingestion/verify_run.py --project {PROJECT}",
    )

    (load_raw >> dbt_test_sources >> dbt_build_staging >> dbt_build_marts
     >> refresh_daily_kpis >> verify_run)
