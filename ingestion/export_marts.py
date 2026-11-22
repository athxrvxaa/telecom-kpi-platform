#!/usr/bin/env python3
"""
Fallback for Power BI: export the mart tables from BigQuery to local CSV files.

Use this only if Power BI's BigQuery connector fails in the sandbox. Reading tables is
free. The 4.6M-row usage fact is skipped on purpose (the KPI tables already aggregate it).

    python ingestion/export_marts.py --project telecom-kpi-platform-515209
"""
import argparse
from pathlib import Path

import pandas as pd
from google.cloud import bigquery

TABLES = [
    "dim_customer", "dim_plan", "dim_sla_target",
    "kpi_monthly_arpu", "kpi_monthly_churn", "kpi_monthly_usage", "kpi_monthly_ticket_sla",
    "mart_customer_360", "fct_ticket", "fct_recharge",
    "dq_raw_defect_report", "dq_row_reconciliation",
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--dataset", default="marts")
    ap.add_argument("--out", default="exports")
    a = ap.parse_args()

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    client = bigquery.Client(project=a.project)

    for name in TABLES:
        rows = client.list_rows(f"{a.project}.{a.dataset}.{name}")
        df = pd.DataFrame([dict(r.items()) for r in rows])
        path = out / f"{name}.csv"
        df.to_csv(path, index=False)
        print(f"{name:<26}{len(df):>9,} rows -> {path}")


if __name__ == "__main__":
    main()
