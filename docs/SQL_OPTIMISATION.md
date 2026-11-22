# Phase 7: SQL optimisation case study

**Goal:** show, with measurements, how query design changes BigQuery cost for the reporting workload
behind the dashboard. Every optimisation is verified to return the same results as its baseline.

Measured numbers are generated into [`benchmarks/results/benchmark_results.md`](../benchmarks/results/benchmark_results.md)
by `benchmarks/sql_optimisation_benchmark.py`. Nothing in this document is hand-typed, so quote the
results file, not memory.

## Method

| Choice | Why |
|---|---|
| Query cache disabled | A cached result costs 0 bytes and would hide the real cost |
| 1 warm-up + N measured runs | Discards cold-start noise; median reported |
| Bytes processed | Deterministic, and what on-demand BigQuery bills |
| Slot-seconds | Total compute; far more stable than wall-clock on small tables |
| Median elapsed time with min-max spread | Honest about noise instead of cherry-picking a run |
| Result comparison (floats within 1e-6 relative) | An "optimisation" that changes answers is a bug |

## Cases

| Case | Technique | What it demonstrates |
|---|---|---|
| A | Column pruning | BigQuery is columnar: `SELECT *` scans every column, naming 3 scans only those 3 |
| B | Pre-aggregation | Dashboards should read a small aggregate (built by `sp_refresh_daily_kpis`), not re-scan 4.6M fact rows |
| C | Aggregate before join | Shrink 4.6M rows to customer-months before joining to the customer dimension |
| D | Clustering | Compare a clustered table with an unclustered copy for a single-customer lookup |

## How to run

```bash
python benchmarks/sql_optimisation_benchmark.py --project telecom-kpi-platform-515209 --cleanup
```

Prerequisite: the marts are built and `marts.agg_daily_kpis` exists (run the Airflow DAG or `sql/run_and_verify.sql`).
Cost: well under 1% of the 1 TB monthly free quota. `--cleanup` drops the temporary unclustered copy used by case D.

## How to read the results honestly

- **Bytes** is the headline metric for A, B and D. Expect A and B to change a lot; they are structural wins.
- **Case C** reads the same columns either way, so bytes should be about equal. Any gain shows up in slot-seconds,
  and BigQuery's optimiser may already do this rewrite, in which case the honest finding is "no meaningful difference".
- **Case D** is a genuine test, not a guaranteed win. Clustering prunes storage blocks, and this table
  (a few hundred MB) is small. If the gain is small, the correct conclusion is that clustering pays off at larger
  scale, which is itself the lesson. Do not describe a result you did not measure.
- **Elapsed time** on tables this small is dominated by fixed overhead. Prefer slot-seconds when they disagree.
- Report a case as an optimisation only if `Results identical` is `YES`.

## Limitations (state these in interviews)

- Synthetic data of about 4.6M usage rows. Absolute savings are small; the relative effect and the method are the point.
- Date partitioning was **not** tested: in the BigQuery sandbox, the default 60-day partition expiry would drop
  historical partitions, so tables are clustered instead. With billing enabled, partitioning by `usage_date` is the
  natural next test.
- Single region, single run session; results will vary a little between runs.

## Measured results (benchmark run, 21 Nov 2026)

Copied from the console output of `benchmarks/sql_optimisation_benchmark.py`; the authoritative record is
`benchmarks/results/benchmark_results.md`. Slot-seconds are rounded to two decimals, so percentages on very small
values (cases B and D) are approximate.

| Case | Bytes before | Bytes after | Change | Slot-s before | Slot-s after | Change | Results identical |
|---|---|---|---|---|---|---|---|
| A: column pruning | 271.6 MB | 119.7 MB | -56% | 2.34 | 1.35 | -42% | YES |
| B: pre-aggregated table | 120.3 MB | 0.1 MB | -99.9% | 0.43 | 0.01 | about -98% | YES |
| C: aggregate before join | 120.6 MB | 120.6 MB | 0% | 0.40 | 0.77 | +93% (worse) | YES |
| D: clustering, single customer | 156.5 MB | 13.1 MB | -92% | 0.45 | 0.03 | about -93% | YES |

### What the results mean

- **A:** BigQuery bills per column scanned. Note the baseline scans 271.6 MB even though the query filters to one
  month: the table is not date-partitioned, so a date filter cannot reduce bytes. Column choice is the only lever there.
- **B:** The dashboard-style question needs 0.1 MB from the pre-aggregated table versus re-scanning 120 MB of fact
  data. Elapsed time barely moved (0.20 s vs 0.17 s) because fixed overhead dominates tiny queries, which is why
  bytes and slot-seconds are the right metrics.
- **C:** No bytes saved, and compute got worse. BigQuery's optimiser already handles this join well; my manual
  rewrite only added a stage. A rewrite is not an optimisation until it is measured.
- **D:** I expected clustering to matter little on a table this small, and I was wrong: the lookup scanned about 92%
  fewer bytes. Clustering lets BigQuery skip storage blocks that cannot contain the customer. Benefit would be larger
  on bigger tables.

### Resume-ready wording (supported by the numbers above)

> Benchmarked four BigQuery query patterns with the cache disabled and verified identical results; cut bytes scanned
> by 56% (column pruning), 99.9% (pre-aggregated table) and 92% (clustering) on a 4.6M-row fact table, and
> identified one rewrite that increased compute and was rejected.
