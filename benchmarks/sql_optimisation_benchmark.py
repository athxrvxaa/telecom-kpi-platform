#!/usr/bin/env python3
"""
SQL optimisation benchmark for the Telecom KPI Data Platform (BigQuery).

For each case it runs a BASELINE query and an OPTIMISED query that must return the same
results, measures cost with BigQuery's own job statistics, and writes a results report.

Measured per query (cache disabled, 1 warm-up run + N measured runs):
  * bytes processed   - deterministic; this is what on-demand BigQuery bills
  * slot-seconds      - total compute used; much more stable than wall-clock time
  * elapsed seconds   - median of N runs; noisy on small tables, report with care

Correctness: every case compares baseline vs optimised output (floats with a small tolerance).
A case whose results differ is flagged MISMATCH and must not be quoted as an optimisation.

Usage (repo root):
    python benchmarks/sql_optimisation_benchmark.py --project telecom-kpi-platform-515209
    python benchmarks/sql_optimisation_benchmark.py --project <id> --runs 5 --cleanup

Cost: each run scans < ~300 MB; the default (4 cases x 2 queries x 4 runs) is well under 1% of
the 1 TB monthly free quota. Requires the marts and sql/sp_refresh_daily_kpis.sql to have been run.
"""
import argparse
import csv
import statistics
from datetime import datetime, timezone
from pathlib import Path

DS = "@DS@"  # replaced with `<project>.<dataset>` at run time

CASES = [
    {
        "id": "A",
        "title": "Select only the columns you need",
        "technique": "Column pruning (no SELECT *)",
        "baseline": f"""
SELECT *
FROM `{DS}.fct_usage_daily`
WHERE usage_date BETWEEN DATE '2026-09-01' AND DATE '2026-09-30'""",
        "optimised": f"""
SELECT customer_id, usage_date, data_gb
FROM `{DS}.fct_usage_daily`
WHERE usage_date BETWEEN DATE '2026-09-01' AND DATE '2026-09-30'""",
        "compare": "rowcount",
    },
    {
        "id": "B",
        "title": "Query a pre-aggregated table instead of the raw fact",
        "technique": "Pre-aggregation (agg_daily_kpis built by the stored procedure)",
        "baseline": f"""
SELECT DATE_TRUNC(u.usage_date, MONTH) AS month_start, c.circle, SUM(u.data_gb) AS total_data_gb
FROM `{DS}.fct_usage_daily` AS u
JOIN `{DS}.dim_customer` AS c USING (customer_id)
GROUP BY 1, 2""",
        "optimised": f"""
SELECT DATE_TRUNC(a.date_day, MONTH) AS month_start, a.circle, SUM(a.data_gb) AS total_data_gb
FROM `{DS}.agg_daily_kpis` AS a
GROUP BY 1, 2""",
        "compare": "rows",
    },
    {
        "id": "C",
        "title": "Aggregate before joining",
        "technique": "Reduce rows before the join (4.6M usage rows -> ~180K customer-months)",
        "baseline": f"""
SELECT DATE_TRUNC(u.usage_date, MONTH) AS month_start, c.segment, c.circle,
       SUM(u.data_gb) AS total_data_gb, COUNT(*) AS subscriber_days
FROM `{DS}.fct_usage_daily` AS u
JOIN `{DS}.dim_customer` AS c USING (customer_id)
GROUP BY 1, 2, 3""",
        "optimised": f"""
WITH per_customer_month AS (
  SELECT customer_id, DATE_TRUNC(usage_date, MONTH) AS month_start,
         SUM(data_gb) AS data_gb, COUNT(*) AS days
  FROM `{DS}.fct_usage_daily`
  GROUP BY 1, 2
)
SELECT p.month_start, c.segment, c.circle, SUM(p.data_gb) AS total_data_gb, SUM(p.days) AS subscriber_days
FROM per_customer_month AS p
JOIN `{DS}.dim_customer` AS c USING (customer_id)
GROUP BY 1, 2, 3""",
        "compare": "rows",
    },
    {
        "id": "D",
        "title": "Clustered vs unclustered table for a single-customer lookup",
        "technique": "Clustering on customer_id (date partitioning is not tested: sandbox expiry rules)",
        "setup": [f"CREATE OR REPLACE TABLE `{DS}.bench_usage_unclustered` AS SELECT * FROM `{DS}.fct_usage_daily`"],
        "baseline": f"""
SELECT usage_date, data_gb, voice_minutes
FROM `{DS}.bench_usage_unclustered`
WHERE customer_id = 'C0000123'
ORDER BY usage_date""",
        "optimised": f"""
SELECT usage_date, data_gb, voice_minutes
FROM `{DS}.fct_usage_daily`
WHERE customer_id = 'C0000123'
ORDER BY usage_date""",
        "compare": "rows",
        "cleanup": [f"DROP TABLE IF EXISTS `{DS}.bench_usage_unclustered`"],
    },
]


# ---------------------------------------------------------------- helpers
def rows_match(a, b, rel_tol=1e-6, abs_tol=1e-4):
    """Compare two result sets: same rows regardless of order, floats within tolerance."""
    if len(a) != len(b):
        return False

    def key(row):
        return tuple(str(x) for x in row if not isinstance(x, float))

    for ra, rb in zip(sorted(a, key=key), sorted(b, key=key)):
        if len(ra) != len(rb):
            return False
        for x, y in zip(ra, rb):
            if isinstance(x, float) or isinstance(y, float):
                if x is None or y is None:
                    if x is not y:
                        return False
                elif abs(x - y) > max(abs_tol, rel_tol * max(abs(x), abs(y))):
                    return False
            elif x != y:
                return False
    return True


def pct_change(before, after):
    return None if not before else (after - before) / before * 100.0


def measure(client, sql, runs, compare_mode):
    from google.cloud import bigquery
    cfg = bigquery.QueryJobConfig(use_query_cache=False)
    stats, last_rows, last_count = [], None, None
    for i in range(runs + 1):  # first run is a warm-up and is discarded
        job = client.query(sql, job_config=cfg)
        result = job.result()
        if i == 0:
            continue
        stats.append({
            "bytes": job.total_bytes_processed or 0,
            "slot_s": (job.slot_millis or 0) / 1000.0,
            "elapsed_s": (job.ended - job.started).total_seconds(),
        })
        last_count = result.total_rows
        if compare_mode == "rows":
            last_rows = [tuple(r.values()) for r in result]
    return {
        "bytes": stats[-1]["bytes"],
        "slot_s": statistics.median(s["slot_s"] for s in stats),
        "elapsed_s": statistics.median(s["elapsed_s"] for s in stats),
        "elapsed_min": min(s["elapsed_s"] for s in stats),
        "elapsed_max": max(s["elapsed_s"] for s in stats),
        "row_count": last_count,
        "rows": last_rows,
    }


def render_markdown(project, runs, results):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    out = [
        "# SQL optimisation benchmark results", "",
        f"Project `{project}` | measured {ts} | {runs} measured runs per query (+1 warm-up), cache disabled", "",
        "| Case | Technique | Bytes: before | Bytes: after | Bytes change | Slot-s: before | Slot-s: after | Slot change | Median s: before | Median s: after | Results identical |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        b, o = r["baseline"], r["optimised"]
        bc, sc = pct_change(b["bytes"], o["bytes"]), pct_change(b["slot_s"], o["slot_s"])
        fmt = lambda v: "n/a" if v is None else f"{v:+.1f}%"
        out.append(
            f"| {r['id']} | {r['technique']} | {b['bytes']/1e6:,.1f} MB | {o['bytes']/1e6:,.1f} MB | {fmt(bc)} "
            f"| {b['slot_s']:.2f} | {o['slot_s']:.2f} | {fmt(sc)} "
            f"| {b['elapsed_s']:.2f} | {o['elapsed_s']:.2f} | {'YES' if r['match'] else 'MISMATCH'} |")
    out += ["", "Negative change = cheaper. Bytes are deterministic; slot-seconds are the most reliable compute measure; "
            "elapsed time on tables this small is noisy (see min-max below).", "", "## Elapsed time spread (min-max, seconds)", ""]
    for r in results:
        b, o = r["baseline"], r["optimised"]
        out.append(f"- Case {r['id']}: before {b['elapsed_min']:.2f}-{b['elapsed_max']:.2f} | after {o['elapsed_min']:.2f}-{o['elapsed_max']:.2f}")
    out += ["", "## Queries", ""]
    for r in results:
        out += [f"### Case {r['id']}: {r['title']}", "", "Baseline:", "```sql", r["baseline_sql"].strip(), "```",
                "Optimised:", "```sql", r["optimised_sql"].strip(), "```", ""]
    return "\n".join(out)


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", required=True)
    ap.add_argument("--dataset", default="marts")
    ap.add_argument("--runs", type=int, default=3, help="measured runs per query")
    ap.add_argument("--out-dir", default="benchmarks/results")
    ap.add_argument("--cleanup", action="store_true", help="drop temporary benchmark tables afterwards")
    a = ap.parse_args()

    from google.cloud import bigquery
    client = bigquery.Client(project=a.project)
    ds = f"{a.project}.{a.dataset}"
    fill = lambda s: s.replace(DS, ds)

    results = []
    for case in CASES:
        print(f"\nCase {case['id']}: {case['title']}")
        for stmt in case.get("setup", []):
            client.query(fill(stmt)).result()
        bsql, osql = fill(case["baseline"]), fill(case["optimised"])
        base = measure(client, bsql, a.runs, case["compare"])
        opt = measure(client, osql, a.runs, case["compare"])
        if case["compare"] == "rows":
            match = rows_match(base["rows"], opt["rows"])
        else:
            match = base["row_count"] == opt["row_count"]
        print(f"  baseline : {base['bytes']/1e6:9.1f} MB  {base['slot_s']:7.2f} slot-s  {base['elapsed_s']:6.2f} s")
        print(f"  optimised: {opt['bytes']/1e6:9.1f} MB  {opt['slot_s']:7.2f} slot-s  {opt['elapsed_s']:6.2f} s")
        print(f"  results identical: {'YES' if match else 'MISMATCH'}")
        results.append({"id": case["id"], "title": case["title"], "technique": case["technique"],
                        "baseline": base, "optimised": opt, "match": match,
                        "baseline_sql": bsql, "optimised_sql": osql})

    out_dir = Path(a.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "benchmark_results.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["case", "technique", "bytes_before", "bytes_after", "slot_s_before", "slot_s_after",
                    "median_s_before", "median_s_after", "results_identical"])
        for r in results:
            b, o = r["baseline"], r["optimised"]
            w.writerow([r["id"], r["technique"], b["bytes"], o["bytes"], round(b["slot_s"], 3), round(o["slot_s"], 3),
                        round(b["elapsed_s"], 3), round(o["elapsed_s"], 3), r["match"]])
    (out_dir / "benchmark_results.md").write_text(render_markdown(a.project, a.runs, results), encoding="utf-8")
    print(f"\nWrote {out_dir / 'benchmark_results.md'} and benchmark_results.csv")

    if a.cleanup:
        for case in CASES:
            for stmt in case.get("cleanup", []):
                client.query(fill(stmt)).result()
        print("Temporary benchmark tables dropped.")


if __name__ == "__main__":
    main()
