# Phase 6: Airflow orchestration

## Pipeline

```
load_raw -> dbt_test_sources -> dbt_build_staging -> dbt_build_marts -> refresh_daily_kpis -> verify_run
```

| Task | What it does | Fails the run when |
|---|---|---|
| `load_raw` | Loads Parquet files into `raw` (idempotent) | A row count does not match the file |
| `dbt_test_sources` | Source tests (severity warn): records defects found in raw | Never (warn only) |
| `dbt_build_staging` | `dbt build --select staging` (run + test per model) | Any staging test fails |
| `dbt_build_marts` | `dbt build --select marts monitoring` | Any mart or reconciliation test fails |
| `refresh_daily_kpis` | Deploys and calls the stored procedure | Any `ASSERT` inside it fails |
| `verify_run` | Checks `etl_run_log`: SUCCESS, recent, rows > 0 | Any check fails |

A failing step stops everything downstream, so bad data never reaches the dashboard tables.
The whole pipeline is idempotent (`CREATE OR REPLACE`), and each successful run also resets BigQuery
sandbox's 60-day table expiry.

## Prerequisites

- **Docker Desktop** (Windows; enable the WSL 2 backend when asked). Allow ~4 GB RAM for it.
- Your gcloud Application Default Credentials file. You already have it if this works for you:
  `python -c "from google.cloud import bigquery; print(bigquery.Client(project='telecom-kpi-platform-515209').project)"`
  Default location on Windows: `C:\Users\<you>\AppData\Roaming\gcloud\application_default_credentials.json`
  If the file is not there, run `gcloud auth application-default login`.
- `data/raw/*.parquet` generated (see README quickstart).

## Run it

```bash
cd orchestration
copy .env.example .env          # then edit .env: set GCP_ADC_PATH (forward slashes)
docker compose build            # first build takes several minutes (installs dbt)
docker compose up -d
docker compose logs -f airflow  # wait until you see the API server is up, then Ctrl+C
```

Open http://localhost:8080. If a login page appears, search the logs for the generated password:
`docker compose logs airflow | findstr /i password` (username `admin`).

1. Find the DAG `telecom_kpi_pipeline`, un-pause it, and press **Trigger**.
2. Watch the six tasks turn green. Open any task's log to see the dbt output.
3. Verify in BigQuery: `SELECT * FROM marts.etl_run_log` shows a new `run_ts`.

Stop it with `docker compose down`.

## Test failure handling (worth a screenshot)

Break something on purpose, for example edit `ingestion/verify_run.py` to require `rows_written > 99999`,
trigger the DAG, and show `verify_run` failing red while upstream tasks stay green. Then fix it.
Alternatively temporarily rename a column in a staging model to see `dbt_build_staging` stop the run.

## Security notes

- The credentials file is mounted read-only into the container. Never commit it or `orchestration/.env`
  (both are git-ignored / outside the repo).
- The UI is bound to localhost only and runs without login. Fine for a local demo, not for a server.

## Why this design (talking points)

- dbt and BigQuery scripts run in an isolated virtualenv inside the image, so their dependencies cannot
  conflict with Airflow's.
- Quality gates are in the pipeline itself: dbt tests, stored-procedure ASSERTs and a final verification step.
- Failures are surfaced through a callback (`alert_on_failure`), a hook where email or Slack can be added.
- Sandbox constraints (no scheduled queries, no DML) are handled by Airflow scheduling and full-refresh DDL.
