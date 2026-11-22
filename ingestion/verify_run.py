#!/usr/bin/env python3
"""
Post-run gate: confirm the stored procedure logged a recent SUCCESS with sensible output.
Exits non-zero (failing the Airflow task) otherwise.

    python ingestion/verify_run.py --project telecom-kpi-platform-515209
"""
import argparse
import sys
from datetime import datetime, timedelta, timezone

from google.cloud import bigquery


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--dataset", default="marts")
    ap.add_argument("--max-age-minutes", type=int, default=30)
    a = ap.parse_args()

    client = bigquery.Client(project=a.project)
    rows = list(client.query(
        f"SELECT * FROM `{a.project}.{a.dataset}.etl_run_log`").result())
    if len(rows) != 1:
        sys.exit(f"FAIL: expected exactly 1 row in etl_run_log, found {len(rows)}")
    r = rows[0]

    age = datetime.now(timezone.utc) - r["run_ts"]
    days = (r["end_date"] - r["start_date"]).days + 1
    checks = {
        "status is SUCCESS": r["status"] == "SUCCESS",
        f"run is recent (<= {a.max_age_minutes} min old)": age <= timedelta(minutes=a.max_age_minutes),
        "rows_written > 0": r["rows_written"] > 0,
        "rows_written is a multiple of the number of days": r["rows_written"] % days == 0,
        "revenue total > 0": r["revenue_inr_total"] > 0,
    }
    for name, ok in checks.items():
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    print(f"run_ts={r['run_ts']}  rows={r['rows_written']:,}  revenue={r['revenue_inr_total']:,.2f}")
    if not all(checks.values()):
        sys.exit("Verification failed")
    print("Verification passed.")


if __name__ == "__main__":
    main()
