# Power BI dashboard guide (Phase 8)

Power BI Desktop is free (Windows). Install it from the Microsoft Store.

## 1. Connect to BigQuery

1. Home > Get data > Google BigQuery > Connect. Sign in with the Google account that owns the project.
2. Under Advanced options set **Billing Project ID** = `telecom-kpi-platform-515209`.
3. Choose **Import** mode (not DirectQuery).
4. Tick these tables from the `marts` dataset, then Load:
   `dim_customer`, `dim_plan`, `kpi_monthly_arpu`, `kpi_monthly_churn`, `kpi_monthly_usage`,
   `kpi_monthly_ticket_sla`, `mart_customer_360`, `dq_raw_defect_report`, `dq_row_reconciliation`.
   (Skip `fct_usage_daily`, 4.6M rows; the KPI tables already aggregate it.)

If the connector errors in sandbox, run `python ingestion/export_marts.py` and load the CSVs from
`exports/` with Get data > Text/CSV instead. Everything below is identical.

## 2. Model: shared lookup tables (conformed dimensions)

The KPI tables are pre-aggregated, so they share three small lookup tables instead of joining each other.
Modeling > New table, one at a time:

```dax
Months   = DISTINCT ( kpi_monthly_arpu[month_start] )
Segments = DISTINCT ( dim_customer[segment] )
Circles  = DISTINCT ( dim_customer[circle] )
```

Model view, create these relationships (one-to-many, single direction, lookup -> fact):

| From (one) | To (many) |
|---|---|
| Months[month_start] | kpi_monthly_arpu, kpi_monthly_churn, kpi_monthly_usage, kpi_monthly_ticket_sla [month_start] |
| Segments[segment] | the four kpi tables + mart_customer_360 [segment] |
| Circles[circle] | kpi_monthly_arpu, kpi_monthly_churn, kpi_monthly_usage, mart_customer_360 [circle] |

(`kpi_monthly_ticket_sla` has no circle column, so Circles does not connect to it.)
Use `Months`, `Segments` and `Circles` for all slicers so one slicer filters every page.
Format `Months[month_start]` as `mmm yyyy`.

## 3. Measures

Create a table for measures: Home > Enter data > name it `_Measures` > Load.

```dax
-- Subscribers (never add monthly snapshots together: take the selected/last month)
Active Subscribers =
VAR m = MAX ( Months[month_start] )
RETURN CALCULATE ( SUM ( kpi_monthly_arpu[active_subscribers] ), Months[month_start] = m )

Closing Subscribers =
VAR m = MAX ( Months[month_start] )
RETURN CALCULATE ( SUM ( kpi_monthly_churn[closing_subscribers] ), Months[month_start] = m )

-- Revenue
Revenue (INR) = SUM ( kpi_monthly_arpu[revenue_inr] )

ARPU (INR) =
DIVIDE (
    [Revenue (INR)],
    SUMX ( VALUES ( Months[month_start] ), CALCULATE ( SUM ( kpi_monthly_arpu[active_subscribers] ) ) )
)

Payment Failure Rate =
DIVIDE ( SUM ( kpi_monthly_arpu[failed_transactions] ),
         SUM ( kpi_monthly_arpu[paid_transactions] ) + SUM ( kpi_monthly_arpu[failed_transactions] ) )

-- Churn
Churned Subscribers = SUM ( kpi_monthly_churn[churned_subscribers] )
Gross Adds          = SUM ( kpi_monthly_churn[gross_adds] )
Net Adds            = [Gross Adds] - [Churned Subscribers]

Churn Rate =
DIVIDE ( [Churned Subscribers],
         SUM ( kpi_monthly_churn[opening_subscribers] ) + SUM ( kpi_monthly_churn[gross_adds] ) )

-- Usage
Total Data (GB) = SUM ( kpi_monthly_usage[total_data_gb] )
Avg Data per Sub-Day (MB) =
DIVIDE ( SUM ( kpi_monthly_usage[total_data_gb] ) * 1024, SUM ( kpi_monthly_usage[subscriber_days] ) )

-- Service quality
Tickets = SUM ( kpi_monthly_ticket_sla[tickets] )
SLA Compliance =
1 - DIVIDE ( SUM ( kpi_monthly_ticket_sla[sla_breached_tickets] ), [Tickets] )

Avg CSAT =
DIVIDE ( SUMX ( kpi_monthly_ticket_sla, kpi_monthly_ticket_sla[avg_csat] * kpi_monthly_ticket_sla[csat_responses] ),
         SUM ( kpi_monthly_ticket_sla[csat_responses] ) )

Avg Resolution (h) =
DIVIDE ( SUMX ( kpi_monthly_ticket_sla, kpi_monthly_ticket_sla[avg_resolution_hours] * kpi_monthly_ticket_sla[closed_tickets] ),
         SUM ( kpi_monthly_ticket_sla[closed_tickets] ) )

-- Customer 360 (churn drivers)
Customers          = COUNTROWS ( mart_customer_360 )
Churned Customers  = CALCULATE ( COUNTROWS ( mart_customer_360 ), mart_customer_360[is_churned] = TRUE () )
Customer Churn %   = DIVIDE ( [Churned Customers], [Customers] )
Avg Data Change %  = AVERAGE ( mart_customer_360[data_usage_change_pct] )
Tickets per Customer (30d) = AVERAGE ( mart_customer_360[tickets_last_30d] )
```

Calculated columns on `mart_customer_360` for the churn-driver charts (Table view > New column):

```dax
Usage Trend Band =
SWITCH ( TRUE (),
    ISBLANK ( mart_customer_360[data_usage_change_pct] ), "No history",
    mart_customer_360[data_usage_change_pct] <= -0.5, "Down 50%+",
    mart_customer_360[data_usage_change_pct] <= -0.2, "Down 20-50%",
    mart_customer_360[data_usage_change_pct] <   0.2, "Stable",
    "Up 20%+" )

Recharge Recency Band =
SWITCH ( TRUE (),
    ISBLANK ( mart_customer_360[days_since_last_recharge] ), "Never",
    mart_customer_360[days_since_last_recharge] <= 14, "0-14 days",
    mart_customer_360[days_since_last_recharge] <= 28, "15-28 days",
    "29+ days" )

Ticket Band =
SWITCH ( TRUE (),
    mart_customer_360[tickets_last_30d] = 0, "0 tickets",
    mart_customer_360[tickets_last_30d] = 1, "1 ticket",
    "2+ tickets" )
```

Set `Usage Trend Band` sort order via a helper column if you want a logical left-to-right order
(Column tools > Sort by column).

## 4. Report pages

**Page 1: Executive overview**
- Slicers: Months, Segments, Circles.
- Cards: Active Subscribers, ARPU (INR), Churn Rate, SLA Compliance.
- Line chart: ARPU (INR) by Months[month_start], legend = Segments[segment].
- Column + line: Churned Subscribers (columns) and Churn Rate (line) by month.
- Bar chart: Revenue (INR) by Circles[circle].

**Page 2: Churn drivers (your best page)**
- Clustered column: Customer Churn % by `Usage Trend Band`.
- Clustered column: Customer Churn % by `Recharge Recency Band`.
- Clustered column: Customer Churn % by `Ticket Band`.
- Bar: Customer Churn % by tenure_band, and by plan_id.
- Takeaway text box with the findings you see (write your own, based on the data).

**Page 3: Usage and revenue**
- Line: Total Data (GB) by month. Line: Avg Data per Sub-Day (MB) by segment.
- Matrix: circle x month with ARPU (INR), conditional formatting on.
- Card/gauge: Payment Failure Rate.

**Page 4: Service quality**
- Bar: SLA Compliance by priority. Add a reference line at your target (for example 80%).
- Column: SLA Compliance by category.
- Line: Avg Resolution (h) by month. Card: Avg CSAT.
- Scatter or column: Avg CSAT for breached vs non-breached (use `sla_breached_tickets` > 0 as a flag if you like).

**Page 5: Data quality**
- Table: `dq_raw_defect_report` (manifest_key, table_name, defects_detected).
- Clustered bar: `dq_row_reconciliation` raw_rows vs staging_rows by table.
- Text: one line explaining the raw -> staging cleaning approach.

## 5. Polish checklist

- Consistent theme (View > Themes), two colours max plus neutrals, titles on every visual.
- Rename pages, hide `_Measures` columns, format numbers (thousands separators, `0.0%`).
- Mind the known limitation: churn for May 2026 is understated by the generator. Either start the
  churn month slicer at June or add a footnote.
- Sync slicers across pages (View > Sync slicers).
- Export: File > Export > PDF, and take screenshots of each page for the README.
- Record a 60-90 second screen capture walking through the dashboard.
- Commit `dashboard/telecom_kpi.pbix`, the PDF and screenshots to GitHub. Do not publish to the Power BI
  Service (needs a paid licence).
