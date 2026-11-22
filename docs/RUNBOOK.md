# Runbook: operating and troubleshooting the pipeline

## Normal operation

| Task | How |
|---|---|
| Run the full pipeline | Airflow UI (http://localhost:8080) > `telecom_kpi_pipeline` > Trigger |
| Start / stop Airflow | `cd orchestration && docker compose up -d` / `docker compose down` |
| Check last run succeeded | `SELECT * FROM marts.etl_run_log` (status SUCCESS, expected 3,680 rows for the default window) |
| Run dbt only | `cd dbt/telecom_kpi && dbt build --profiles-dir .` |
| Rebuild everything from scratch | generate data -> `load_to_bigquery.py` -> `dbt build` -> `sql/run_and_verify.sql` (or just trigger the DAG) |
| Benchmark queries | `python benchmarks/sql_optimisation_benchmark.py --project <id> --cleanup` |

## Order of operations (why it is this order)

1. **Raw load** first, because everything reads from it.
2. **Source tests** next: they only warn, and they record how dirty the raw data is.
3. **Staging build** (run + test): marts must not be built on data that failed its checks.
4. **Marts build** (run + test): reconciliation tests confirm KPI totals equal fact totals.
5. **Stored procedure** reads the marts, so it runs after them. Its `ASSERT`s are the last data gate.
6. **verify_run** confirms the procedure logged a recent SUCCESS.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `Not found: Dataset ... in location X` | dbt/client guessed the wrong region | Add `location: <region>` to `dbt/telecom_kpi/profiles.yml` (see the dataset's "Data location" in the console) |
| Authentication / credentials error in Airflow task | gcloud credentials expired or wrong `GCP_ADC_PATH` | `gcloud auth application-default login`, then check `orchestration/.env` path (forward slashes) |
| Tables suddenly missing or "Not found: Table" after weeks | Sandbox deletes tables after 60 days | Re-run the pipeline; it rebuilds everything |
| `dbt build` fails on a test | Real data problem or a model change broke an assumption | Open the task log, find the failing test name, run its compiled SQL from `target/compiled` in BigQuery to see failing rows |
| Warnings on source tests | Expected: they detect the planted raw defects | None; compare counts with `dq_raw_defect_report` |
| `refresh_daily_kpis` fails with an assertion message | Output did not reconcile with fact tables, or bad date parameters | Read the message; check `fct_recharge` / `fct_usage_daily` freshness and the DAG `params` window |
| `verify_run` fails | Run log stale (> 30 min), status not SUCCESS, or zero rows | Look at the previous task's log; re-trigger from `refresh_daily_kpis` |
| `Docker build` slow or fails | First build installs dbt; low RAM | Give Docker Desktop >= 4 GB; retry |
| Power BI connector error | Sandbox/billing project setting | Set Billing Project ID in the connector, or use `ingestion/export_marts.py` and load CSVs |
| Airflow shows an old DAG version | Edited file not reparsed yet | Wait ~30 s or restart the container |

## Cost guardrails

- No billing account is attached, so charges are impossible; the limits are 10 GB storage and 1 TB queries/month.
- A full pipeline run scans roughly a few hundred MB. The benchmark scans under 1% of the monthly quota.
- Always check the "bytes processed" estimate in the BigQuery editor before running exploratory queries on fact tables.

## Extending

- **New KPI:** add a model in `dbt/telecom_kpi/models/marts/kpi/`, document columns in `_marts.yml`, add a reconciliation test in `tests/`, then add measures in Power BI.
- **New data quality check:** generic tests go in the model's YAML; custom checks are SQL files in `tests/` that return the failing rows (zero rows = pass).
- **Change the data window:** edit `data_start_date` / `data_end_date` in `dbt_project.yml` and the DAG `params`.

## Security

- Never commit `orchestration/.env`, gcloud credential files or service-account keys (all are git-ignored).
- Airflow is bound to localhost with no login: demo only. Add authentication before exposing it anywhere.
