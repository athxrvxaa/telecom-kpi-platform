#!/usr/bin/env python3
"""
Load the generated Parquet files into the BigQuery `raw` dataset.

Design notes
  * Raw layer = data exactly as the source system delivered it. No cleaning here;
    all fixes happen in dbt staging so the lineage stays auditable.
  * Idempotent: every run replaces the table (WRITE_TRUNCATE), so re-running is safe.
  * Load jobs are free in BigQuery (no query bytes billed).
  * Nanosecond timestamps are downcast to microseconds, because BigQuery
    TIMESTAMP is microsecond precision, and dictionary-encoded columns are
    expanded to plain strings.
  * Row counts are verified against the source files after each load.

Usage (from the repo root):
    python ingestion/load_to_bigquery.py --project telecom-kpi-platform-515209
    python ingestion/load_to_bigquery.py --project <id> --tables customers tickets
    python ingestion/load_to_bigquery.py --project <id> --dry-run    # no BigQuery calls
"""
import argparse
import sys
import tempfile
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

TABLES = ["plans", "customers", "usage_daily", "recharges", "tickets"]


def normalise(path: Path, tmp_dir: Path) -> tuple[Path, pa.Table]:
    """Read a Parquet file and return a BigQuery-friendly copy (path, arrow table)."""
    table = pq.read_table(path)
    fields = []
    for f in table.schema:
        t = f.type
        if pa.types.is_dictionary(t):
            t = t.value_type
        if pa.types.is_timestamp(t) and t.unit == "ns":
            t = pa.timestamp("us")
        fields.append(pa.field(f.name, t, nullable=True))
    table = table.cast(pa.schema(fields))
    out = tmp_dir / path.name
    pq.write_table(table, out, compression="snappy")
    return out, table


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", required=True, help="GCP project ID")
    ap.add_argument("--dataset", default="raw")
    ap.add_argument("--data-dir", default="data/raw")
    ap.add_argument("--tables", nargs="+", default=TABLES, choices=TABLES)
    ap.add_argument("--dry-run", action="store_true", help="validate files and schemas only")
    a = ap.parse_args()

    data_dir = Path(a.data_dir)
    missing = [t for t in a.tables if not (data_dir / f"{t}.parquet").exists()]
    if missing:
        sys.exit(f"Missing parquet files in {data_dir}: {missing}. Run the generator first.")

    client = location = None
    if not a.dry_run:
        from google.cloud import bigquery
        client = bigquery.Client(project=a.project)
        ds = client.get_dataset(f"{a.project}.{a.dataset}")
        location = ds.location
        print(f"Target: {a.project}.{a.dataset} (location: {location})")
    else:
        print("DRY RUN: no BigQuery calls will be made")

    with tempfile.TemporaryDirectory() as tmp:
        for name in a.tables:
            src = data_dir / f"{name}.parquet"
            clean_path, arrow_tbl = normalise(src, Path(tmp))
            n_rows = arrow_tbl.num_rows
            print(f"\n[{name}] {n_rows:,} rows, {src.stat().st_size / 1e6:.1f} MB")
            for f in arrow_tbl.schema:
                print(f"    {f.name:<22} {f.type}")
            if a.dry_run:
                continue

            table_id = f"{a.project}.{a.dataset}.{name}"
            job_config = bigquery.LoadJobConfig(
                source_format=bigquery.SourceFormat.PARQUET,
                write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
            )
            with open(clean_path, "rb") as fh:
                job = client.load_table_from_file(fh, table_id, job_config=job_config, location=location)
            job.result()  # waits; raises on failure

            loaded = client.get_table(table_id).num_rows
            status = "OK" if loaded == n_rows else "MISMATCH"
            print(f"  -> loaded {loaded:,} rows into {table_id} [{status}]")
            if loaded != n_rows:
                sys.exit(f"Row count mismatch for {name}: file={n_rows:,} table={loaded:,}")

    print("\nAll done." if not a.dry_run else "\nDry run complete.")


if __name__ == "__main__":
    main()
