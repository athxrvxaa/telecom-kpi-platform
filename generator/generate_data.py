#!/usr/bin/env python3
"""
Synthetic telecom data generator for the Telecom KPI Data Platform.

Produces five raw source tables (what an operational system would export):
    plans, customers, usage_daily, recharges, tickets

Realistic behaviour is baked in so the analytics have something to find:
  * Churners show declining usage, fewer recharges and more / slower-resolved
    tickets in the weeks before they disconnect.
  * Ticket CSAT is lower when the SLA is breached.
  * A small, configurable share of deliberately dirty records is injected
    (duplicates, nulls, orphans, negatives, inconsistent casing) so that
    dbt data-quality tests have real defects to catch. Everything injected
    is logged in _injected_issues.json.

Usage:
    python generate_data.py --customers 30000 --out ../data/raw
    python generate_data.py --customers 5000 --format csv --seed 7
"""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

# --------------------------------------------------------------------------
# Reference data
# --------------------------------------------------------------------------
PLANS = pd.DataFrame(
    [
        # plan_id, plan_name, plan_type, price_inr, validity_days, data_gb_total
        ("P101", "Prepaid Lite", "Prepaid", 199, 28, 21),
        ("P102", "Prepaid Standard", "Prepaid", 299, 28, 42),
        ("P103", "Prepaid Plus", "Prepaid", 479, 56, 84),
        ("P104", "Prepaid Max", "Prepaid", 719, 84, 126),
        ("P201", "Postpaid Basic", "Postpaid", 399, 30, 40),
        ("P202", "Postpaid Plus", "Postpaid", 599, 30, 100),
        ("P203", "Postpaid Premium", "Postpaid", 999, 30, 200),
    ],
    columns=["plan_id", "plan_name", "plan_type", "price_inr", "validity_days", "data_gb_total"],
)

CIRCLES = {
    "Maharashtra": 0.16, "Uttar Pradesh": 0.14, "Delhi": 0.10, "Madhya Pradesh": 0.10,
    "Gujarat": 0.09, "Karnataka": 0.09, "Tamil Nadu": 0.09, "West Bengal": 0.08,
    "Rajasthan": 0.08, "Kerala": 0.07,
}
TICKET_CATEGORIES = {
    "Network Issue": 0.35, "Billing Dispute": 0.25, "Recharge Failure": 0.15,
    "Data Speed": 0.12, "SIM/Activation": 0.08, "Plan Query": 0.05,
}
# SLA targets in hours. Mirrored as a dbt seed later; the generator only uses
# them to make CSAT depend on breaches and never writes them to the raw data.
SLA_HOURS = {"P1": 4, "P2": 24, "P3": 72}
PRIORITY_MEDIAN_RES_H = {"P1": 2.2, "P2": 20.0, "P3": 45.0}


def choice(rng, mapping, size):
    keys = list(mapping.keys())
    p = np.array(list(mapping.values()), dtype=float)
    return rng.choice(keys, size=size, p=p / p.sum())


def ids(prefix, n, width):
    return np.array([f"{prefix}{i:0{width}d}" for i in range(1, n + 1)])


# --------------------------------------------------------------------------
# Tables
# --------------------------------------------------------------------------
def make_customers(rng, n, start, end):
    window_days = (end - start).days + 1
    cust = pd.DataFrame({"customer_id": ids("C", n, 7)})

    cust["segment"] = np.where(rng.random(n) < 0.75, "Prepaid", "Postpaid")
    is_pre = (cust["segment"] == "Prepaid").to_numpy()
    plan = np.where(
        is_pre,
        rng.choice(["P101", "P102", "P103", "P104"], size=n, p=[0.35, 0.40, 0.15, 0.10]),
        rng.choice(["P201", "P202", "P203"], size=n, p=[0.45, 0.40, 0.15]),
    )
    cust["plan_id"] = plan

    # 78% existing base (signed up in the 3 years before the window), 22% new adds in-window.
    is_new = rng.random(n) < 0.22
    offset_old = rng.integers(1, 3 * 365, size=n)
    offset_new = rng.integers(0, window_days, size=n)
    signup = np.where(is_new, start + pd.to_timedelta(offset_new, "D"), start - pd.to_timedelta(offset_old, "D"))
    cust["signup_date"] = pd.to_datetime(signup).normalize()

    cust["circle"] = choice(rng, CIRCLES, n)
    cust["age_band"] = rng.choice(["18-24", "25-34", "35-44", "45-54", "55+"], size=n, p=[0.22, 0.34, 0.24, 0.13, 0.07])
    cust["device_type"] = rng.choice(["Android", "iOS", "Feature Phone"], size=n, p=[0.72, 0.18, 0.10])
    cust["acquisition_channel"] = rng.choice(["Retail Store", "Online", "Partner", "Referral"], size=n, p=[0.45, 0.25, 0.20, 0.10])

    # Churn: prepaid churns more. New signups cannot churn within their first 30 days.
    p_churn = np.where(is_pre, 0.14, 0.05)
    churner = rng.random(n) < p_churn
    disc_offset = rng.integers(20, window_days, size=n)
    disc = start + pd.to_timedelta(disc_offset, "D")
    disc = np.maximum(pd.to_datetime(disc), cust["signup_date"] + pd.Timedelta(days=30))
    disc = pd.Series(pd.to_datetime(disc)).where(churner & (pd.Series(disc) <= end))
    cust["disconnect_date"] = disc.dt.normalize()
    cust["status"] = np.where(cust["disconnect_date"].notna(), "Disconnected", "Active")
    return cust


def make_usage(rng, cust, start, end):
    n = len(cust)
    days = pd.date_range(start, end, freq="D")
    nd = len(days)
    plans = PLANS.set_index("plan_id")
    gb = cust["plan_id"].map(plans["data_gb_total"]).to_numpy(float)
    val = cust["plan_id"].map(plans["validity_days"]).to_numpy(float)
    is_pre = (cust["segment"] == "Prepaid").to_numpy()

    # Per-customer baselines (daily).
    util = rng.lognormal(mean=np.log(0.65), sigma=0.45, size=n).clip(0.05, 1.6)
    base_data = gb * 1024 / val * util                        # MB / day
    base_voice = rng.gamma(2.0, np.where(is_pre, 14, 22), size=n)  # minutes / day
    base_sms = rng.gamma(1.5, np.where(is_pre, 1.6, 1.0), size=n)

    dow = np.array([1.00, 0.98, 0.98, 1.00, 1.05, 1.12, 1.08])[days.dayofweek]  # Mon..Sun

    signup = cust["signup_date"].to_numpy("datetime64[D]")
    disc = cust["disconnect_date"].to_numpy("datetime64[D]")
    day_arr = days.to_numpy("datetime64[D]")

    D = day_arr[None, :]
    active = D >= signup[:, None]
    has_disc = ~np.isnat(disc)
    active &= ~has_disc[:, None] | (D <= np.where(has_disc, disc, np.datetime64("2100-01-01"))[:, None])

    # Churn decay: last 30 days before disconnect, usage fades to ~35%.
    d2c = (np.where(has_disc, disc, np.datetime64("2100-01-01"))[:, None] - D).astype(int)
    decay = np.where(has_disc[:, None] & (d2c <= 30), 0.35 + 0.65 * (d2c.clip(0, 30) / 30), 1.0)

    # ~1% of customer-days are missing (collection gaps).
    present = rng.random((n, nd)) > 0.01
    keep = active & present
    ci, di = np.nonzero(keep)

    f = decay[ci, di] * dow[di]
    data_mb = base_data[ci] * f * rng.lognormal(0, 0.55, size=len(ci))
    voice = base_voice[ci] * f * rng.gamma(4, 0.25, size=len(ci))
    sms = rng.poisson(base_sms[ci] * f)
    roaming = rng.random(len(ci)) < 0.012

    usage = pd.DataFrame({
        "customer_id": pd.Categorical.from_codes(ci, categories=cust["customer_id"].to_numpy()),
        "usage_date": day_arr[di],
        "data_mb": data_mb.round(1),
        "voice_minutes": voice.round(1),
        "sms_count": sms.astype("int32"),
        "roaming_flag": roaming,
    })
    usage["usage_date"] = pd.to_datetime(usage["usage_date"]).dt.date
    return usage


def make_recharges(rng, cust, start, end):
    n = len(cust)
    plans = PLANS.set_index("plan_id")
    val = cust["plan_id"].map(plans["validity_days"]).to_numpy()
    price = cust["plan_id"].map(plans["price_inr"]).to_numpy(float)
    is_pre = (cust["segment"] == "Prepaid").to_numpy()

    signup = cust["signup_date"].to_numpy("datetime64[D]")
    disc = cust["disconnect_date"].to_numpy("datetime64[D]")
    has_disc = ~np.isnat(disc)
    # Churners stop recharging 5-20 days before disconnect (the plan lapses first).
    cutoff = np.where(has_disc, disc - rng.integers(5, 21, size=n).astype("timedelta64[D]"), np.datetime64(end.date()))
    cutoff = np.minimum(cutoff, np.datetime64(end.date()))

    is_new = signup >= np.datetime64(start.date())
    first = np.where(is_new, signup, np.datetime64(start.date()) + rng.integers(0, val).astype("timedelta64[D]"))

    frames, cum = [], np.zeros(n, dtype=int)
    for _ in range(8):
        d = first + cum.astype("timedelta64[D]")
        ok = (d <= cutoff) & (d <= np.datetime64(end.date()))
        idx = np.nonzero(ok)[0]
        if len(idx):
            frames.append(pd.DataFrame({"ci": idx, "recharge_date": d[idx]}))
        lapse = np.where(rng.random(n) < 0.20, rng.integers(1, 7, size=n), 0)
        cum = cum + val + lapse
    r = pd.concat(frames, ignore_index=True)
    ci = r["ci"].to_numpy()

    amount = price[ci].copy()
    pre = is_pre[ci]
    # Prepaid: 8% buy a different pack / top-up. Postpaid: 25% pay overage on top of the plan.
    alt = pre & (rng.random(len(ci)) < 0.08)
    amount[alt] = rng.choice([99, 149, 199, 299, 479, 719], size=alt.sum())
    over = (~pre) & (rng.random(len(ci)) < 0.25)
    amount[over] += rng.uniform(50, 400, size=over.sum()).round(0)

    out = pd.DataFrame({
        "recharge_id": ids("R", len(r), 9),
        "customer_id": cust["customer_id"].to_numpy()[ci],
        "recharge_date": pd.to_datetime(r["recharge_date"]).dt.date,
        "amount_inr": amount,
        "channel": rng.choice(["App", "UPI", "Retail", "Web"], size=len(r), p=[0.38, 0.34, 0.20, 0.08]),
        "payment_status": rng.choice(["Paid", "Failed"], size=len(r), p=[0.955, 0.045]),
    })
    return out


def make_tickets(rng, cust, start, end):
    n = len(cust)
    nd = (end - start).days + 1
    signup = cust["signup_date"].to_numpy("datetime64[D]")
    disc = cust["disconnect_date"].to_numpy("datetime64[D]")
    has_disc = ~np.isnat(disc)
    s0 = np.maximum(signup, np.datetime64(start.date()))
    e0 = np.where(has_disc, disc, np.datetime64(end.date()))
    active_days = (e0 - s0).astype(int).clip(1, None)

    # Base: ~0.18 tickets / customer / month.
    k_base = rng.poisson(0.18 * active_days / 30.0)
    # Churners: extra tickets in their last 30 days.
    k_churn = np.where(has_disc, rng.poisson(1.1, size=n), 0)

    ci_b = np.repeat(np.arange(n), k_base)
    ci_c = np.repeat(np.arange(n), k_churn)
    sec_b = s0[ci_b].astype("datetime64[s]") + (rng.random(len(ci_b)) * active_days[ci_b] * 86400).astype("timedelta64[s]")
    c_back = (rng.random(len(ci_c)) * 30 * 86400).astype("timedelta64[s]")
    sec_c = np.maximum(e0[ci_c].astype("datetime64[s]") - c_back, s0[ci_c].astype("datetime64[s]"))

    ci = np.concatenate([ci_b, ci_c])
    opened = np.concatenate([sec_b, sec_c])
    pre_churn = np.concatenate([np.zeros(len(ci_b), bool), np.ones(len(ci_c), bool)])
    m = len(ci)

    prio = rng.choice(["P1", "P2", "P3"], size=m, p=[0.08, 0.32, 0.60])
    med = pd.Series(prio).map(PRIORITY_MEDIAN_RES_H).to_numpy()
    res_h = rng.lognormal(np.log(med), 0.85) * np.where(pre_churn, 1.35, 1.0)
    closed = opened + (res_h * 3600).astype("timedelta64[s]")

    end_ts = np.datetime64(end.date()) + np.timedelta64(1, "D")
    still_open = closed > end_ts
    sla = pd.Series(prio).map(SLA_HOURS).to_numpy()
    breached = res_h > sla
    csat_prob = np.where(breached, 0.30, 0.55)
    has_csat = (rng.random(m) < 0.45) & ~still_open
    csat = np.where(
        breached,
        rng.choice([1, 2, 3, 4, 5], size=m, p=[0.28, 0.27, 0.22, 0.15, 0.08]),
        rng.choice([1, 2, 3, 4, 5], size=m, p=[0.04, 0.06, 0.15, 0.35, 0.40]),
    ).astype(float)
    csat[~has_csat] = np.nan

    t = pd.DataFrame({
        "customer_id": cust["customer_id"].to_numpy()[ci],
        "opened_ts": opened,
        "closed_ts": np.where(still_open, np.datetime64("NaT", "s"), closed),
        "category": choice(rng, TICKET_CATEGORIES, m),
        "priority": prio,
        "channel": rng.choice(["App", "Call Centre", "Store", "Social"], size=m, p=[0.35, 0.40, 0.15, 0.10]),
        "status": np.where(still_open, "Open", "Closed"),
        "csat_score": csat,
    })
    t = t.sort_values("opened_ts").reset_index(drop=True)
    t.insert(0, "ticket_id", ids("T", len(t), 8))
    return t


# --------------------------------------------------------------------------
# Dirty-data injection
# --------------------------------------------------------------------------
def inject_issues(rng, cust, usage, rech, tick, rate):
    log = {}

    # customers: duplicate rows, messy circle casing, missing age_band
    k = max(1, int(len(cust) * rate))
    dup = cust.sample(k, random_state=int(rng.integers(1e9)))
    cust = pd.concat([cust, dup], ignore_index=True)
    log["customers_duplicate_rows"] = int(k)

    ix = rng.choice(len(cust), size=k * 2, replace=False)
    cust.loc[ix[:k], "circle"] = cust.loc[ix[:k], "circle"].str.upper()
    cust.loc[ix[k:], "circle"] = cust.loc[ix[k:], "circle"].str.lower() + " "
    log["customers_inconsistent_circle_casing"] = int(k * 2)

    ix = rng.choice(len(cust), size=k, replace=False)
    cust.loc[ix, "age_band"] = None
    log["customers_null_age_band"] = int(k)

    # usage: duplicate rows, negative data_mb
    k = max(1, int(len(usage) * rate))
    usage = pd.concat([usage, usage.sample(k, random_state=int(rng.integers(1e9)))], ignore_index=True)
    log["usage_duplicate_rows"] = int(k)
    ix = rng.choice(len(usage), size=k, replace=False)
    usage.loc[ix, "data_mb"] = -usage.loc[ix, "data_mb"].abs()
    log["usage_negative_data_mb"] = int(k)

    # recharges: orphan customer ids, non-positive amounts, future-dated
    k = max(1, int(len(rech) * rate))
    ix = rng.choice(len(rech), size=k, replace=False)
    rech.loc[ix, "customer_id"] = "C9999999"
    log["recharges_orphan_customer_id"] = int(k)
    ix = rng.choice(len(rech), size=k, replace=False)
    rech.loc[ix, "amount_inr"] = 0.0
    log["recharges_zero_amount"] = int(k)
    ix = rng.choice(len(rech), size=k, replace=False)
    rech["recharge_date"] = pd.to_datetime(rech["recharge_date"])
    rech.loc[ix, "recharge_date"] = pd.Timestamp("2027-01-15")
    rech["recharge_date"] = rech["recharge_date"].dt.date
    log["recharges_future_dated"] = int(k)

    # tickets: null customer ids, closed before opened
    k = max(1, int(len(tick) * rate))
    ix = rng.choice(len(tick), size=k, replace=False)
    tick.loc[ix, "customer_id"] = None
    log["tickets_null_customer_id"] = int(k)
    closed_ix = tick.index[tick["closed_ts"].notna()]
    ix = rng.choice(closed_ix, size=k, replace=False)
    tick.loc[ix, "closed_ts"] = tick.loc[ix, "opened_ts"] - pd.Timedelta(hours=2)
    log["tickets_closed_before_opened"] = int(k)

    return cust, usage, rech, tick, log


# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--customers", type=int, default=30000)
    ap.add_argument("--start", default="2026-05-01")
    ap.add_argument("--end", default="2026-10-31")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--dirty-rate", type=float, default=0.002, help="share of rows to corrupt (0 disables)")
    ap.add_argument("--format", choices=["parquet", "csv"], default="parquet")
    ap.add_argument("--out", default="../data/raw")
    a = ap.parse_args()

    rng = np.random.default_rng(a.seed)
    start, end = pd.Timestamp(a.start), pd.Timestamp(a.end)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    print(f"Generating {a.customers:,} customers, {a.start} -> {a.end} ...")
    cust = make_customers(rng, a.customers, start, end)
    usage = make_usage(rng, cust, start, end)
    rech = make_recharges(rng, cust, start, end)
    tick = make_tickets(rng, cust, start, end)

    log = {}
    if a.dirty_rate > 0:
        cust, usage, rech, tick, log = inject_issues(rng, cust, usage, rech, tick, a.dirty_rate)

    cust["signup_date"] = pd.to_datetime(cust["signup_date"]).dt.date
    cust["disconnect_date"] = pd.to_datetime(cust["disconnect_date"]).dt.date

    tables = {"plans": PLANS, "customers": cust, "usage_daily": usage, "recharges": rech, "tickets": tick}
    for name, df in tables.items():
        path = out / f"{name}.{a.format}"
        if a.format == "parquet":
            df.to_parquet(path, index=False)
        else:
            df.to_csv(path, index=False)
        mb = path.stat().st_size / 1e6
        print(f"  {name:<12} {len(df):>10,} rows  {mb:>7.1f} MB  -> {path}")

    (out / "_injected_issues.json").write_text(json.dumps({"seed": a.seed, "dirty_rate": a.dirty_rate, **log}, indent=2))
    print("Done. Injected-issue manifest written to _injected_issues.json")


if __name__ == "__main__":
    main()
