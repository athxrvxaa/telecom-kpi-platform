# Interview guide: Telecom KPI Data Platform

Written for someone who built this project with help and now needs to **understand it deeply enough to defend it**.
Read it in order once, then use sections 9 and 10 for practice. Everything here refers to things that really exist
in this repository, so you can open the file while you study.

**The golden rule:** you can say "I built this with AI assistance and then made sure I understood every part."
That is honest and increasingly normal. What you must never do is claim something you cannot explain. When you
get a question you do not know, say how you would find out. Interviewers value that more than a bluff.

---

## 1. Your pitch

### 30-second version
"I built an end-to-end analytics platform for a synthetic telecom operator. Raw data is loaded into BigQuery,
cleaned and modelled into a star schema with dbt, orchestrated by Airflow, validated with automated tests and
stored-procedure assertions, and presented in a Power BI dashboard covering ARPU, churn, usage and ticket SLAs.
I also benchmarked query optimisations and measured the results, including one that made things worse."

### 2-minute walkthrough (say it in this order)
1. **Problem:** a telecom needs reliable KPIs, but source data is messy and reports are often built by hand.
2. **Data:** I generated synthetic data (30K customers, 4.6M daily usage rows, recharges, tickets) and deliberately
   planted 10 kinds of defects, so I could prove the pipeline catches them.
3. **Architecture:** raw layer exactly as delivered, staging layer cleaned, marts layer with a star schema and KPI tables.
4. **Quality:** defects are detected in raw, fixed in staging, then tests must pass or the pipeline stops. A stored
   procedure asserts its output reconciles with the fact tables.
5. **Orchestration:** an Airflow DAG with six tasks runs everything in order in about 1 min 40 s; a failed gate
   stops the run.
6. **Serving:** Power BI dashboard on pre-aggregated KPI tables.
7. **Optimisation:** four query benchmarks with identical-results checks: column pruning -56% bytes,
   pre-aggregation -99.9%, clustering -92%, and one rewrite that did not help.
8. **Honest limits:** synthetic data, BigQuery sandbox (no billing), local demo Airflow.

---

## 2. The basics, from zero

### 2.1 What is this field?
**Data engineering** = moving data from where it is created to where people can use it, reliably.
**Analytics engineering** = turning that data into trusted, well-modelled tables (what dbt is for).
**BI / reporting** = visualising those tables (Power BI). This internship is a mix of all three.

### 2.2 Database vs data warehouse
- **OLTP database** (MySQL, PostgreSQL, SQL Server): runs applications. Many small reads/writes ("update this
  customer's address"). Stores data **row by row**.
- **Data warehouse** (BigQuery, Snowflake, Redshift): built for analysis. Few huge reads ("total revenue by region
  by month"). Stores data **column by column** (columnar).

**Why columnar matters:** to sum one column across 4.6M rows, a columnar store reads only that column. A row store
reads every column of every row. This is exactly why Case A in the benchmark saved 56%: `SELECT *` reads all columns;
naming three reads three.

### 2.3 ETL vs ELT
- **ETL** (Extract, Transform, Load): clean the data *before* it enters the warehouse, using a separate tool.
- **ELT** (Extract, Load, Transform): load raw data first, then transform *inside* the warehouse using its power.

This project is **ELT**. Why modern teams prefer it: the raw data is preserved (you can reprocess when logic changes),
transformations are plain SQL, and the warehouse scales the compute. ETL still makes sense when data must be cleansed
or masked before it may be stored (privacy), or when the warehouse is small.

### 2.4 Layers (raw, staging, marts)
Also called bronze/silver/gold or "medallion" architecture.
| Layer | Meaning | In this project |
|---|---|---|
| Raw | Exactly as delivered, never edited | dataset `raw`, defects included |
| Staging | Cleaned, typed, deduplicated, one table per source | dataset `staging`, `stg_*` |
| Marts | Business-ready models and KPIs | dataset `marts`, `dim_*`, `fct_*`, `kpi_*` |

**Why keep raw untouched?** Auditability. If someone asks "why does the number differ from the source?", you can
trace every change. Also if your cleaning logic has a bug, you can fix it and rebuild from raw.

### 2.5 Dimensional modelling (star schema)
- **Fact table:** records events/measurements. Many rows. Numbers you add up. E.g. `fct_recharge` (one row per payment).
- **Dimension table:** descriptive context. Fewer rows. E.g. `dim_customer` (who), `dim_date` (when), `dim_plan`.
- **Grain:** what one row means. Always define it first. `fct_usage_daily` grain = one customer on one day.
- **Star schema:** one fact in the middle, dimensions around it. Simple joins, fast, easy for BI tools to understand.
- **Snowflake schema:** dimensions normalised into sub-dimensions. Saves space, adds joins. Rarely worth it in modern warehouses.
- **Surrogate key:** a made-up ID instead of a business ID. We used the business key `customer_id` because it is stable
  in this synthetic data; in real systems surrogate keys protect you when business keys change or get reused.
- **SCD (slowly changing dimension):** how you handle a dimension attribute that changes over time. Type 1 overwrite,
  Type 2 keep history with start/end dates (dbt "snapshots" do this). We did not need it; mention it as a next step.

### 2.6 Orchestration
An **orchestrator** runs tasks in the right order, on a schedule, retries failures, and shows you what happened.
Airflow terms:
- **DAG** (Directed Acyclic Graph): the workflow. "Directed" = arrows have direction, "acyclic" = no loops.
- **Task / Operator:** one step; the operator says how (we use `BashOperator`, which runs a shell command).
- **Scheduler:** decides what runs when. **Executor:** how tasks are actually run (local process, Celery workers, Kubernetes).
- **Retries / retry_delay:** automatic re-attempts on failure.
- **Idempotent:** running it twice gives the same result as once. Our pipeline is idempotent because every step is
  `CREATE OR REPLACE`. This is a core data engineering principle: it makes reruns and recovery safe.
- **Backfill / catchup:** running past scheduled intervals you missed. We set `catchup=False`.

### 2.7 Data quality
Kinds of checks, with examples from this project:
| Kind | Example here |
|---|---|
| Uniqueness | `customer_id` unique in `stg_customers` |
| Not null | `age_band` not null after cleaning |
| Referential integrity | every recharge's `customer_id` exists in customers |
| Accepted values | `circle` is one of 10 known names |
| Range / validity | no negative `data_mb`, no future-dated recharge |
| Consistency | closed ticket has a `closed_ts`, open ticket does not |
| Reconciliation | KPI revenue total equals fact revenue total |
| Volume / freshness | row counts raw vs staging; run log is recent |

**Warn vs error:** a *warn* test reports a problem without stopping the pipeline (used on raw, where we *expect*
dirt). An *error* test stops the pipeline (used on staging and marts, where dirt must not exist).
**Quarantine:** rows that cannot be trusted are excluded and counted, not silently "fixed" by guessing.

### 2.8 Business intelligence concepts
- **Semantic model:** tables + relationships + measures that report authors build on.
- **Measure vs calculated column (DAX):** a *measure* is calculated at query time in the current filter context
  (e.g. `Churn Rate`). A *calculated column* is computed per row when data refreshes (e.g. `Usage Trend Band`).
- **Filter context:** Power BI evaluates a measure again for every cell/bar, with the filters (month, segment) of that cell applied.
- **Import vs DirectQuery:** Import copies data into Power BI's in-memory engine (fast, needs refresh). DirectQuery sends
  queries to the source each time (always current, slower, more load on the warehouse). We used Import.

### 2.9 Telecom vocabulary
| Term | Meaning |
|---|---|
| **ARPU** | Average Revenue Per User per period. Revenue / active subscribers |
| **Churn** | Customers leaving. **Churn rate** = leavers / customer base at risk |
| **Gross adds** | New subscribers in the period. **Net adds** = gross adds - churned |
| **Prepaid / Postpaid** | Pay before use (recharge) vs bill after use |
| **Circle** | A telecom licence region in India (e.g. Maharashtra) |
| **CDR** | Call Detail Record. Our `usage_daily` is a daily summary of such records |
| **SLA** | Service Level Agreement: promised resolution time (P1 4h, P2 24h, P3 72h here) |
| **CSAT** | Customer Satisfaction score, 1-5 |
| **Cash-basis ARPU** | Counts money when paid, not spread over the pack's validity; lumpy for long packs |

---

## 3. Why each tool, what else exists, when NOT to use it

### 3.1 BigQuery
**What it is:** Google's serverless data warehouse. You do not manage servers; you load data and run SQL.

**How it works (be able to say this in 4 sentences):** storage and compute are separate. Data sits in Google's
distributed storage in a columnar format. A query is split across many workers called **slots**, which scan only the
columns needed and combine results. On-demand pricing charges for **bytes scanned**; capacity pricing (editions)
charges for slot time.

**Why we chose it:**
1. The role mentions Google Cloud; BigQuery is its flagship analytics product.
2. Free sandbox: no card, 10 GB storage and 1 TB queries per month, enough for this project.
3. Zero infrastructure work, plain SQL, scales to far larger data.

**Honest trade-offs:** cost scales with bytes scanned, so sloppy queries cost money; no traditional indexes (you use
partitioning and clustering instead); sandbox limits (no DML, 60-day expiry) shaped our design.

| Alternative | One-line comparison | Choose it when |
|---|---|---|
| **Snowflake** | Similar idea; separate "virtual warehouses" billed per time; multi-cloud | Multi-cloud, or the company already uses it (you hold the SnowPro certificate, so mention it) |
| **Amazon Redshift** | AWS warehouse, cluster-based | Already deep in AWS |
| **Azure Synapse / Microsoft Fabric** | Microsoft's analytics stack | Microsoft-centric organisation, tight Power BI integration |
| **Databricks** | Lakehouse on Spark + Delta tables; strong for ML and big engineering | Heavy data science, streaming, very large unstructured data |
| **PostgreSQL / SQL Server** | General databases | Small data, or transactional workloads |
| **DuckDB** | In-process analytics engine on a laptop | Local analysis, tests, small-to-medium data |

### 3.2 dbt (data build tool)
**What it is:** a tool where you write each transformation as a SQL `SELECT` in its own file; dbt turns it into a
table/view, works out dependency order from `ref()` calls, and runs tests. It does the **T in ELT**.

**Why we chose it:** version-controlled SQL, automatic dependency graph, built-in testing and documentation, and it is
the industry standard for analytics engineering.

**Key concepts:** *model* (a SELECT file), *source* (a raw table declared in YAML), `ref()` (link to another model),
*materialisation* (view, table, incremental, ephemeral), *test* (generic in YAML, singular as SQL files),
*seed* (CSV loaded as a table), *snapshot* (SCD2 history), *macro* (reusable Jinja code).
`dbt build` = run models and their tests together, skipping anything downstream of a failure.

| Alternative | Comparison |
|---|---|
| **Dataform** | Google's own, built into BigQuery, free. Very similar; the natural choice if you are all-in on GCP |
| **SQLMesh** | Newer, adds virtual environments and change detection |
| **Plain SQL scripts / stored procedures** | Works, but no dependency graph, tests or docs; hard to review |
| **Spark / PySpark jobs** | Needed for huge data or non-SQL logic; heavier to write and run |
| **GUI ETL tools** (Informatica, Talend, SSIS) | Visual and common in big enterprises; harder to version-control and review |

**Why not just stored procedures for everything?** We did use one (for the daily aggregate), but dbt gives tests,
lineage and reviewable files. Use a procedure when you need scripting logic (loops, assertions, parameters).

### 3.3 Airflow
**What it is:** an open-source workflow orchestrator. You define a DAG in Python; Airflow schedules, runs, retries
and monitors it, with a web UI.

**Why we chose it:** it is the most widely used orchestrator (and what **Cloud Composer**, GCP's managed service, runs).
It demonstrates scheduling, dependencies, retries and failure handling. The failed `verify_run` screenshot is proof
the quality gate works.

**Why Airflow when BigQuery has scheduled queries?** Scheduled queries run one SQL statement on a timer. We needed
ordering across *different systems* (Python loader, dbt, stored procedure, verification), failure propagation, retries
and a run history. (Also, scheduled queries are unavailable in the sandbox.)

| Alternative | Comparison |
|---|---|
| **Cloud Composer** | Managed Airflow on GCP. What a company on GCP would likely use; same DAG code, no servers to run, but costs money |
| **Prefect** | Python-native, lighter, easier local start |
| **Dagster** | Models *data assets* rather than tasks; strong dbt integration |
| **Cron / Cloud Scheduler** | Fine for one simple job; no dependencies, retries or UI |
| **Cloud Workflows** | GCP service orchestration via YAML; lighter than Airflow |
| **Azure Data Factory** | Microsoft's visual orchestrator |
| **dbt Cloud scheduler** | Schedules dbt only, not the other steps |

### 3.4 Power BI
**What it is:** Microsoft's BI tool: connect data, build a semantic model, write DAX measures, make reports.
**Why:** the JD lists Tableau, Power BI, Qlik; Power BI is the most accessible and free on Windows.

| Alternative | Comparison |
|---|---|
| **Tableau** | Strong visual exploration; different modelling approach (worksheets, LOD expressions) |
| **Qlik Sense** | Associative engine, in-memory; common in some enterprises |
| **Looker / Looker Studio** | Google's; Looker has a code-based semantic layer (LookML), Looker Studio is free and lightweight |
| **Superset / Metabase** | Open-source BI |

**Transferable skill:** the *thinking* (star schema, measures vs columns, filter context, pre-aggregation) is the same in every tool.

### 3.5 Smaller choices
| Choice | Why | Alternative |
|---|---|---|
| **Parquet** | Typed, compressed, columnar; BigQuery reads schema directly | CSV (no types, bigger, ambiguous), Avro, JSON |
| **Docker** | Airflow does not run natively on Windows; container gives a reproducible setup | WSL2, a managed Composer environment |
| **Python generator** | Safe data with known planted defects, so tests can be verified | Public datasets (no known ground truth) |
| **Clustering instead of partitioning** | Sandbox's default 60-day partition expiry would drop historic partitions | Date partitioning (preferred when billing exists) |
| **Full-refresh tables instead of incremental** | Sandbox has no DML (incremental needs MERGE/INSERT) | Incremental models (preferred at scale) |

---

## 4. Mapping the project to the job description

| Job description bullet | Evidence in this project |
|---|---|
| Design, develop, maintain data pipelines and ETL | Airflow DAG, loader, dbt models (ELT) |
| Translate stakeholder needs into technical solutions | KPI definitions (ARPU, churn, SLA) turned into models; `DATA_MODEL.md` |
| Develop scalable data models | Star schema, dimension and fact tables, defined grain |
| Interactive dashboards (Tableau, Power BI, Qlik) | Five-page Power BI report with slicers and DAX |
| Maintain and optimise databases, SQL, stored procedures | `sp_refresh_daily_kpis`, benchmark with measured results |
| Ensure data quality, consistency, accuracy | Source/staging/marts tests, defect report, reconciliation, assertions |
| Automate reporting processes | Airflow schedule, pre-aggregated KPI tables, run log |
| Investigate and resolve data issues | Defect detection and quarantine logic; runbook |
| Document pipelines and configurations | README, data dictionary, runbook, Airflow guide |
| Google Cloud familiarity | BigQuery, IAM-based auth via ADC, datasets, load jobs |
| Stay current | Airflow 3, dbt, awareness of Dataform/Composer alternatives |

---

## 5. Design decisions (the "why" log)

Interviewers love "why did you do X instead of Y?". Each row is a decision you can defend.

| Decision | Alternative considered | Why this way |
|---|---|---|
| ELT with an untouched raw layer | Clean data before loading (ETL) | Keeps an audit trail; lets me re-run cleaning logic when it changes |
| Quarantine bad rows (exclude + count) | Auto-correct them (e.g. flip negative values with `ABS`) | Guessing a "correct" value hides problems. Excluding and counting is transparent. For tiny, clearly-typo cases a documented correction can also be valid; the rule must be explicit |
| Warn tests on raw, error tests on staging/marts | Same severity everywhere | Raw is *expected* to be dirty; failing there would block the pipeline for no benefit. Downstream must be clean |
| Star schema | One wide table; or fully normalised | Simple joins, BI-friendly, clear grain |
| Pre-aggregated KPI tables for Power BI | Let Power BI aggregate 4.6M rows | Case B: 0.1 MB vs 120 MB scanned; dashboard stays fast and cheap |
| `table` materialisations (full refresh) | Incremental models | Sandbox has no DML. At this size, a full rebuild takes seconds anyway. At scale I would go incremental |
| Clustering, no date partitioning | Partition by `usage_date` | Sandbox's default 60-day partition expiry would delete historic partitions. With billing, partition |
| Stored procedure with `ASSERT` for the daily aggregate | Another dbt model | Shows scripting, parameters and validation; the assertion makes bad output fail loudly |
| Airflow runs shell commands in an isolated virtualenv | Install dbt into Airflow's own Python | Avoids dependency conflicts between Airflow and dbt/Google libraries |
| Cash-basis ARPU | Revenue spread over pack validity | Simpler, auditable, matches payments. The limitation is documented |
| Shared lookup tables (Months/Segments/Circles) in Power BI | Relate KPI tables directly to each other | KPI tables are different grains; a shared dimension lets one slicer filter all of them |
| Dashboard churn page framed as "behaviour before disconnect" | Call it "churn drivers/prediction" | Metrics are measured at disconnect and the generator planted the patterns, so it is not a predictive result |

---

## 6. Phase-by-phase deep dive (what the code actually does)

### Phase 1: generator (`generator/generate_data.py`)
Uses NumPy to create customers, plans, daily usage, recharges and tickets. Built-in behaviour: churners' usage fades over
their last 30 days, they stop recharging before disconnecting, and they raise more and slower-resolved tickets. Ticket
satisfaction drops when SLA is breached. Then `inject_issues` corrupts ~0.2% of rows in ten specific ways and writes a
manifest (`_injected_issues.json`) of exactly what was injected, **so the pipeline's detections can be checked against ground truth.**
*Say:* "I planted known defects so I could prove the checks work, instead of just hoping they do."

### Phase 2: loader (`ingestion/load_to_bigquery.py`)
Reads each Parquet file, normalises timestamp precision (nanoseconds to microseconds, which BigQuery needs), uploads with
`WRITE_TRUNCATE` (replace table, so reruns are safe), and checks the BigQuery row count equals the file's. Load jobs are free.

### Phase 3: staging (dbt)
The core cleaning idea is **`QUALIFY ROW_NUMBER()`** for deduplication:
```sql
select * from cleaned
qualify row_number() over (
    partition by customer_id
    order by (age_band = 'Unknown'), signup_date
) = 1
```
Meaning: group rows by `customer_id`, rank them (rows with a known age band first), keep rank 1. `QUALIFY` filters on a
window function result the way `HAVING` filters on an aggregate. Without `QUALIFY` you would need a subquery.
Other staging rules: `INITCAP(TRIM(circle))` fixes casing/whitespace; `COALESCE(age_band,'Unknown')`; inner joins to
`stg_customers` drop orphan recharges and tickets; `WHERE amount_inr > 0 AND recharge_date <= data_end_date` drops invalid rows.
Tickets wrap timestamps in `TIMESTAMP()` because Parquet's naive timestamps load into BigQuery as `DATETIME`.

### Phase 4: marts
- `dim_*`: descriptive tables. `fct_*`: events with measures. `fct_ticket.is_sla_breached` joins to `dim_sla_target`.
- `kpi_monthly_*`: pre-aggregated at month x segment x circle (ticket table adds priority and category).
- `mart_customer_360`: one row per customer with last-30-days vs previous-30-days behaviour, snapshotted at the disconnect
  date for churned customers and the window end for active ones.
- Reconciliation tests, e.g. total KPI revenue must equal total fact revenue.

### Phase 5: stored procedure (`sql/sp_refresh_daily_kpis.sql`)
Takes `p_start_date` and `p_end_date`. Steps: `ASSERT` the dates make sense; `CREATE OR REPLACE TABLE agg_daily_kpis` from
four CTEs (subscribers, usage, revenue, tickets) joined on day x segment x circle; `ASSERT` the table is non-empty and that
revenue and data volume match the fact tables; write `etl_run_log`. If any `ASSERT` fails the call errors, which fails the
Airflow task. *Remember:* we proved the validation works by calling it with a start date after the end date; the assertion rejected it.

### Phase 6: Airflow (`orchestration/dags/telecom_kpi_pipeline.py`)
Six `BashOperator` tasks in a chain. `dbt build` runs models and their tests in dependency order and skips anything downstream
of a failure. Each command uses an isolated virtualenv inside the Docker image. Credentials come from a read-only mounted
Application Default Credentials file. A failure callback logs which task failed (a hook for Slack/email).

### Phase 7: benchmark (`benchmarks/sql_optimisation_benchmark.py`)
Runs each query pair with the cache off, one warm-up and three measured runs; records bytes processed, slot-milliseconds and
elapsed time from BigQuery's job statistics; compares result sets (floats with tolerance); writes a report. Only trust a
speed-up whose results are identical.

### Phase 8: dashboard
Import mode, three shared lookup tables, DAX measures that avoid double-counting (e.g. subscribers take the selected month,
ARPU divides revenue by the sum of monthly subscribers).

---

## 7. Numbers to remember (all measured or counted in this project)

| Fact | Value |
|---|---|
| Customers / usage rows / recharges / tickets (raw) | 30,060 (incl. 60 duplicates) / 4,621,211 / 145,098 / 31,354 |
| Planted defect types | 10 (all detected) |
| Defect counts | dup customers 60, casing 120, null age 60, dup usage 9,223, negative usage 9,223, orphan recharges 290, zero amount 290, future-dated 290, null ticket customer 62, closed-before-opened 62 |
| DAG | 6 tasks, successful run 1 min 39 s |
| Daily KPI table | 3,680 rows = 184 days x 2 segments x 10 circles |
| Total revenue in KPI layer | ₹53,012,582 (matched an independent pandas calculation) |
| Total data volume | about 6.55 million GB (6,548,106.6 in the run log) |
| Dashboard headline | ~27.4K active subscribers, ARPU about ₹338, SLA compliance 66%, monthly churn about 2% |
| Benchmark A | 271.6 -> 119.7 MB, -56% bytes |
| Benchmark B | 120.3 -> 0.1 MB, -99.9% bytes |
| Benchmark C | bytes equal; compute 0.40 -> 0.77 slot-s (worse) |
| Benchmark D | 156.5 -> 13.1 MB, -92% bytes |

---

## 8. Limitations, said confidently

Naming limits yourself makes you sound senior. Say them *before* they are asked.

1. **Synthetic data.** Chosen deliberately: no privacy risk, known ground truth for testing. Not a substitute for real-world messiness.
2. **Sandbox constraints.** No billing account, so no DML, scheduled queries or partitioning. I designed around each (see section 5).
3. **Local Airflow in a single container with no login.** A demo of the same DAG code that Cloud Composer would run.
4. **Batch, not real-time.** Daily refresh; no streaming.
5. **Churn page is descriptive.** The generator plants the patterns; it is not a model or a discovery.
6. **Known generator quirk:** no disconnects in the first 20 days, so May churn is understated.
7. **Benchmark scale is small** (about 4.6M rows), so absolute savings are small; the method and relative effects are the point.

### What I would do with more time or a billing account
Partition by date and move to incremental models; add CI (GitHub Actions running `dbt build` on every pull request);
publish `dbt docs` lineage; add Slack/email alerts; add SCD2 snapshots for customer plan changes; add data-contract checks
on the raw feed; move to Cloud Composer; build an actual churn model (logistic regression / gradient boosting) on the 360 table
with a *proper* time split to avoid label leakage; add cost monitoring from `INFORMATION_SCHEMA.JOBS`.

---

## 9. Question bank with model answers

Answers are short on purpose; practise saying them in your own words.

### Project and behavioural
**1. Why did you build this?** To gain hands-on experience across the stack the role uses (SQL, cloud warehouse, orchestration, BI, data quality) rather than only reading about it.

**2. What was the hardest part?** Making the pipeline trustworthy instead of just working: planting defects, proving each was detected, and reconciling KPI totals back to the facts. Also designing around sandbox limits.

**3. What would you do differently?** Add CI and partitioning earlier, and generate the data window so recent months are not artificially low on churn.

**4. How did you make sure the numbers were right?** Independent recomputation in pandas matched the pipeline (revenue ₹53,012,582), tests reconcile KPI tables to facts, and the stored procedure asserts its own output.

**5. Did you build this alone?** "I built it with AI assistance, working step by step. I ran every stage myself, debugged results, found and fixed issues in my own dashboard, and I can walk through any component." (Only say this if true for you, and then make it true by studying this guide.)

**6. Tell me about a mistake you found.** Use a story from section 10.

**7. How would you explain this to a non-technical stakeholder?** "Every morning the system collects the latest customer, usage, payment and support data, checks it, and updates a dashboard that shows revenue per customer, how many customers are leaving, and whether support is meeting its promised response times."

### SQL
**8. INNER vs LEFT vs FULL vs CROSS JOIN?** INNER: matching rows only. LEFT: all left rows plus matches (NULLs where none). FULL: all rows from both. CROSS: every combination. In `kpi_monthly_churn` I cross join months with customers on purpose to test each customer against each month.

**9. WHERE vs HAVING?** WHERE filters rows before grouping; HAVING filters groups after aggregation. `QUALIFY` filters after window functions.

**10. ROW_NUMBER vs RANK vs DENSE_RANK?** ROW_NUMBER gives unique sequence (ties broken arbitrarily or by tiebreaker). RANK gives ties the same rank and skips numbers (1,1,3). DENSE_RANK ties same rank, no gaps (1,1,2). I used ROW_NUMBER to keep exactly one row per key.

**11. How do you remove duplicates?** `QUALIFY ROW_NUMBER() OVER (PARTITION BY key ORDER BY preference) = 1`, as in `stg_customers`. Or `SELECT DISTINCT` if rows are fully identical. Always decide *which* duplicate to keep.

**12. CTE vs subquery vs temp table vs view?** CTE and subquery are logically similar; CTEs read better and can be reused in the same query. A temp table stores intermediate data for a session. A view saves a query definition (no stored data); a materialised table stores results.

**13. COUNT(*) vs COUNT(column) vs COUNT(DISTINCT)?** COUNT(*) counts rows; COUNT(col) skips NULLs; DISTINCT counts unique non-NULL values. I used `COUNT(*) - COUNT(DISTINCT customer_id)` to count duplicates.

**14. NULL traps?** Comparisons with NULL are unknown, not false; `NOT IN` against a list containing NULL returns nothing (use `NOT EXISTS`, which I used for orphan detection); aggregates ignore NULLs; use `COALESCE`/`SAFE_DIVIDE`.

**15. How do you optimise a slow or expensive query?** Measure first (bytes, slot time, execution graph). Then: select only needed columns; filter early and on partition/cluster columns; avoid cross joins and repeated scans; pre-aggregate; join smaller to larger and reduce rows before joins when it helps; avoid unnecessary DISTINCT/ORDER BY. Then re-measure. In my benchmark one "obvious" rewrite got slower, which is why you measure.

**16. Stored procedure vs function vs view?** Procedure: runs a sequence of statements, can take parameters, does things (create tables, assert). Function: returns a value inside a query. View: saved SELECT. I used a procedure because the task is a multi-step build with validation.

**17. Index vs partition vs cluster?** Traditional databases use B-tree indexes to find rows fast. BigQuery has no such indexes for normal tables; **partitioning** splits a table by date/integer so queries read only relevant segments; **clustering** sorts data within storage by chosen columns so blocks can be skipped. Partitioning gives predictable pruning and cost estimates; clustering helps filters/joins on high-cardinality columns. They combine.

**18. Month-over-month growth in SQL?** `LAG` window function (example in section 12).

### BigQuery
**19. What is a slot?** A unit of BigQuery compute (CPU/memory/networking). A query uses many slots in parallel. "Slot-seconds" is total compute used.

**20. On-demand vs capacity pricing?** On-demand charges per TiB of data scanned (with a free monthly allowance); capacity (editions) buys slot capacity billed over time, better for steady heavy workloads.

**21. How do you control cost?** Select needed columns, filter on partitions/clusters, dry-run to see bytes, set `maximum_bytes_billed`, quotas, budget alerts, `require_partition_filter`, pre-aggregate for dashboards.

**22. Why did the date filter in Case A not reduce bytes?** The table is not partitioned by date, so BigQuery still scans the columns for all rows.

**23. Why did clustering help even on a small table?** It reduced scanned bytes by about 92% because rows for one customer sit together and other blocks can be skipped. I had predicted a small effect and was wrong; the measurement corrected me.

**24. Streaming vs batch loading?** Batch load jobs are free; streaming inserts cost and (in sandbox) are unavailable. We used batch because data arrives as files.

**25. STRUCT/ARRAY?** BigQuery supports nested and repeated fields, enabling denormalised storage without joins. We used a flat star schema; nested fields are an alternative for one-to-many data like ticket events.

**26. What is the query cache?** BigQuery caches identical query results for about 24 hours at no cost. I disabled it in the benchmark so I measured real work.

### dbt
**27. `ref` vs `source`?** `source()` points to a raw table loaded by something else; `ref()` points to another dbt model and builds the dependency graph.

**28. Materialisations?** view (query on read), table (rebuilt storage), incremental (only new/changed rows via merge/insert), ephemeral (inlined CTE). I used tables because the sandbox has no DML; I would use incremental for large facts.

**29. How does an incremental model work?** First run builds the table; later runs use `is_incremental()` to select only new rows (by date or ID) and merge or insert them using a `unique_key`.

**30. Generic vs singular tests?** Generic: reusable (`unique`, `not_null`, `accepted_values`, `relationships`) declared in YAML. Singular: a custom SQL file that returns failing rows; zero rows = pass.

**31. What does `dbt build` do vs `run` + `test`?** `build` runs each model then its tests in order and skips downstream nodes when something fails, so a bad model never feeds the next one.

### Airflow
**32. What is a DAG and why acyclic?** Workflow of tasks with dependencies; no cycles so there is always a valid order to run.

**33. Why not cron?** Cron cannot express dependencies, retries, backfills or give a run history/UI.

**34. What does idempotent mean and why care?** Re-running yields the same result; makes retries and recovery safe. Ours uses `CREATE OR REPLACE` and `WRITE_TRUNCATE`.

**35. XCom, sensors, hooks, connections?** XCom passes small values between tasks; sensors wait for a condition (file arrives); hooks wrap connections to external systems; connections store credentials/endpoints. We did not need XCom because tasks communicate through BigQuery tables.

**36. Executors?** Local (one machine), Celery (worker pool), Kubernetes (a pod per task). Ours is a single-container local setup.

**37. What if a task fails?** Retried once after 2 minutes; if it still fails, downstream tasks are not run, the failure callback logs it, and the UI shows it red (my `verify_run` demonstration).

**38. Airflow vs Cloud Composer?** Same code. Composer is Google's managed Airflow: no servers to maintain, integrated with GCP IAM, but paid.

### Data modelling and quality
**39. Star vs snowflake?** Star keeps dimensions flat (fewer joins, faster); snowflake normalises them (less redundancy, more joins). Star is usual for BI.

**40. Types of fact tables?** Transactional (one row per event, e.g. recharges), periodic snapshot (state at regular intervals, like my monthly KPI tables), accumulating snapshot (one row per process that updates through stages, like a ticket going open to closed).

**41. SCD types?** Type 1 overwrite; Type 2 add a new row with validity dates to keep history; Type 3 keep previous value in a column.

**42. How do you monitor quality in production?** Tests in the pipeline, row-count and freshness checks, reconciliation to sources, alerting on failure, and trend tracking of defect counts (my `dq_raw_defect_report`).

### Power BI
**43. Measure vs calculated column?** Measure is evaluated at query time in filter context and does not store data; calculated column is stored per row at refresh. Prefer measures for aggregations.

**44. Why not average the average column?** Averages are not additive. Computing the mean of means weights small groups equally. I compute totals and divide: `DIVIDE(SUM(data_gb)*1024, SUM(subscriber_days))`.

**45. Import vs DirectQuery?** Import is fast and works offline but needs refresh; DirectQuery is live but slower and loads the source. With pre-aggregated tables, Import is ideal.

**46. How do you keep a report fast?** Star schema, pre-aggregated data, remove unused columns, avoid high-cardinality columns, measures not calculated columns, limit visuals per page.

### Honest and tough
**47. Is this production-ready?** No. It demonstrates production *patterns* (tests, idempotency, orchestration, assertions) at demo scale on a free tier. Productionising needs CI/CD, secrets management, monitoring/alerting, managed orchestration, access control and incremental loads.

**48. Why should we believe your benchmark?** Cache disabled, warm-up discarded, median of runs, bytes and slot time reported (not just elapsed time), results verified identical, and I report the case where my change was worse.

**49. What is label leakage?** Using information that would not be available at prediction time. My churn page measures behaviour up to the disconnect date, so it describes churners but cannot predict them. A real model would snapshot customers *before* the churn window.

**50. What do you not know yet?** Pick two or three honestly (e.g. incremental models at scale, BigQuery partitioning in practice, Kubernetes executors) and say how you would learn them.

---

## 10. Stories from this project (use STAR: Situation, Task, Action, Result)

**A. "The average that wasn't."** *Situation:* my dashboard chart showed about 36,000 MB average data per subscriber-day; the true figure is about 1,800. *Task:* find out why. *Action:* realised I had dragged the raw `avg_data_mb_per_sub_day` column into a chart, and Power BI defaulted to Sum, adding up 20 segment-circle averages. *Result:* replaced it with a measure dividing total data by total subscriber-days. *Lesson:* averages are not additive; aggregate from sums and counts.

**B. "Bars over 100%."** The SLA compliance chart showed bars above 100% because a "percent of grand total" setting was on a ratio measure. Fix: remove the setting. Lesson: sanity-check every chart against a number you know (I knew compliance was 66%).

**C. "Identical bars."** The CSAT-by-SLA-status chart showed two equal bars. The KPI table had no per-ticket breach flag, so the question could not be answered at that grain. Fix: load the ticket-level fact table and chart average CSAT by breach status. Lesson: pre-aggregated tables answer only questions at or above their grain; keep the detailed table available for drill-down.

**D. "Churn drivers" that were not.** My churn page showed about 100% churn for customers whose usage dropped 50%+. Looking closer, behaviour was measured at the disconnect date, and my own generator had planted those patterns. I retitled the page to "behaviour before disconnect" and noted the data is synthetic. Lesson: avoid label leakage and overclaiming.

**E. "My optimisation was worse."** Aggregating before joining (Case C) doubled compute. I kept it in the report. Separately, I predicted clustering would barely help on a small table; it cut bytes by 92%. Lesson: measure, do not assume.

**F. "Designing around limits."** The sandbox's 60-day partition expiry would silently delete old partitions. I recognised that before building, used clustering instead and documented the trade-off. Lesson: read platform constraints before choosing a design.

**G. "Proving the checks work."** Instead of trusting my tests, I planted 10 defect types with a manifest and confirmed every count matched. A test you have never seen fail proves little.

---

## 11. Things not to claim

| Do not say | Say instead |
|---|---|
| "Production pipeline" / "enterprise-scale" | "Production-style patterns at demo scale on BigQuery's free sandbox" |
| "Real-time" | "Daily batch" |
| "I predicted churn" | "I analysed behaviour before disconnect on synthetic data" |
| "Cut costs by 99.9%" | "In a benchmark, a pre-aggregated table scanned 99.9% fewer bytes than the fact table" |
| "Real customer data" | "Synthetic data with planted defects" |
| Anything you cannot explain | "I'd need to look that up; here is how I would approach it" |

---

## 12. Practice SQL on your own marts

Run these in BigQuery against `marts.*`. Try writing each yourself before reading the answer.

**Month-over-month revenue growth by segment**
```sql
SELECT month_start, segment,
       SUM(revenue_inr) AS revenue,
       SAFE_DIVIDE(SUM(revenue_inr) - LAG(SUM(revenue_inr)) OVER (PARTITION BY segment ORDER BY month_start),
                   LAG(SUM(revenue_inr)) OVER (PARTITION BY segment ORDER BY month_start)) AS mom_growth
FROM marts.kpi_monthly_arpu
GROUP BY month_start, segment
ORDER BY segment, month_start;
```
**Top 3 circles by revenue in each month** (top-N per group)
```sql
SELECT month_start, circle, SUM(revenue_inr) AS revenue
FROM marts.kpi_monthly_arpu
GROUP BY month_start, circle
QUALIFY ROW_NUMBER() OVER (PARTITION BY month_start ORDER BY SUM(revenue_inr) DESC) <= 3
ORDER BY month_start, revenue DESC;
```
**Cumulative daily revenue** (running total)
```sql
SELECT date_day, SUM(revenue_inr) AS revenue,
       SUM(SUM(revenue_inr)) OVER (ORDER BY date_day) AS cumulative_revenue
FROM marts.agg_daily_kpis
GROUP BY date_day
ORDER BY date_day;
```
**Churned customers whose data usage fell by half or more**
```sql
SELECT customer_id, circle, data_usage_change_pct
FROM marts.mart_customer_360
WHERE is_churned AND data_usage_change_pct <= -0.5
ORDER BY data_usage_change_pct;
```
**Exercises to try (no answers given):** (1) cohort retention: percentage of customers per signup month still active at the end;
(2) 7-day moving average of daily data usage using `ROWS BETWEEN 6 PRECEDING AND CURRENT ROW`; (3) circles with SLA compliance
below the overall average (needs a join); (4) customers with no usage for 14 consecutive days (gaps-and-islands pattern);
(5) find the circle with the highest payment failure rate each month.

---

## 13. Study plan (in priority order)

1. **SQL (most important):** joins, GROUP BY/HAVING, window functions (`ROW_NUMBER`, `LAG`, running totals), CTEs, NULL handling.
   Do section 12 daily for a week, then practise on public SQL question sets.
2. **Data modelling:** star schema, grain, SCD types, fact table types. Be able to draw this project's ER diagram from memory.
3. **BigQuery basics:** how storage/compute separate, partition vs cluster, cost model, `INFORMATION_SCHEMA`.
4. **dbt concepts:** materialisations, tests, `ref/source`, incremental logic. Skim the dbt fundamentals course (free).
5. **Airflow concepts:** DAG, operators, scheduler, executors, retries, idempotency, backfill.
6. **Power BI:** DAX `CALCULATE`, filter context, relationships. Redo the dashboard fixes yourself.
7. **Re-read this guide's section 9 aloud** until the answers come naturally in your own words.

**Final tip:** when the interviewer asks about something in your project, answer in three beats: *what it is, why I chose it,
what I would change.* That pattern signals real understanding.
