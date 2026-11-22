# Airflow 3.1.8 + an isolated venv for dbt and the BigQuery scripts.
FROM apache/airflow:3.1.8

# dbt + BigQuery client live in their own venv so they never conflict with Airflow's dependencies.
RUN python -m venv /home/airflow/dbt_venv \
 && /home/airflow/dbt_venv/bin/pip install --no-cache-dir \
        dbt-bigquery google-cloud-bigquery pyarrow pandas
