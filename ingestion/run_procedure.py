#!/usr/bin/env python3
"""
Deploy (CREATE OR REPLACE) and call the daily-KPI stored procedure.
Used by the Airflow DAG; also runnable by hand:

    python ingestion/run_procedure.py --project telecom-kpi-platform-515209 \
        --sql sql/sp_refresh_daily_kpis.sql --start 2026-05-01 --end 2026-10-31

If any ASSERT inside the procedure fails, BigQuery raises and this script exits non-zero,
which fails the Airflow task.
"""
import argparse
from pathlib import Path

from google.cloud import bigquery


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--dataset", default="marts")
    ap.add_argument("--sql", required=True, help="path to the CREATE PROCEDURE script")
    ap.add_argument("--start", required=True, help="YYYY-MM-DD")
    ap.add_argument("--end", required=True, help="YYYY-MM-DD")
    a = ap.parse_args()

    client = bigquery.Client(project=a.project)

    print("Deploying procedure ...")
    client.query(Path(a.sql).read_text()).result()

    call = (f"CALL `{a.project}.{a.dataset}.sp_refresh_daily_kpis`"
            f"(DATE '{a.start}', DATE '{a.end}')")
    print(f"Running: {call}")
    job = client.query(call)
    job.result()
    print(f"Procedure finished. Bytes processed (script total): {job.total_bytes_processed:,}")


if __name__ == "__main__":
    main()
