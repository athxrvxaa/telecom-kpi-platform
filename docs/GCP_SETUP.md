# Phase 0: GCP setup (one-time, ~20 minutes)

## Why not the no-card sandbox?
The BigQuery sandbox has no DML, no scheduled queries and expires tables after 60 days.
Stored procedures and dbt incremental models need DML, so we use the regular free tier
(billing account attached, same 10 GB / 1 TB monthly free limits, no table expiry).

## Steps

1. **Create a project**: console.cloud.google.com → New Project → name `telecom-kpi-platform`.
   Note the **project ID** (e.g. `telecom-kpi-platform-123456`).
2. **Link a billing account**: Billing → add a card. Free tier usage is not charged.
   (New accounts may also get free trial credits; check the console.)
3. **Set a budget alert (do this before anything else)**:
   Billing → Budgets & alerts → Create budget → ₹100 (or $2), alert at 50% / 90% / 100%.
   Alerts only notify; they do not stop spending, so also do step 4.
4. **Cap query spend**: BigQuery → Quotas (IAM & Admin → Quotas) → search
   "Query usage per day" → set a custom quota of ~50 GB/day. Anything that would exceed
   it fails instead of billing you.
5. **Enable the BigQuery API** (usually on by default).
6. **Create datasets** (location: pick one region, e.g. `asia-south1`, and use it for all):
   `raw`, `staging`, `marts`.
7. **Service account for dbt/Airflow**: IAM & Admin → Service Accounts → create
   `dbt-runner` with roles **BigQuery Data Editor** and **BigQuery Job User**.
   Keys → Add key → JSON. Save as `service-account.json` **outside the repo**
   (it is git-ignored, but never commit or share it).
8. Install the Google Cloud CLI and run `gcloud auth login`.

## What to send back
Your project ID and chosen region (never the key file). Then we do Phase 2: loading the data.

## Staying free
- Never `SELECT *` on big tables while exploring; use column selection and partition filters.
- `LIMIT` does not reduce bytes scanned on normal tables.
- Check the "bytes processed" estimate in the BigQuery editor before running.
