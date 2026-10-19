"""Pipeline model, step 2 — close-date timing via STAGE-aware survival analysis.

Timing must depend on stage, not just age: a Qualify deal is much further from closing
than a Negotiate deal. So for each (product, stage k) we fit a Kaplan-Meier survival
curve on "time from ENTERING stage k to close", from the stage-change log — every deal
that ever reached k contributes (close - first-entry-to-k); deals still open are
right-censored. An open deal currently at stage k then draws its remaining time from the
curve for that (product, k), conditional on how long it has sat in that stage.

All as-of-date aware, so the backtest can refit on pre-T data with no leakage.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
from lifelines import KaplanMeierFitter

from etl.load.db import get_engine

TODAY = pd.Timestamp(date.today()).normalize()
RANK = {"Qualify": 1, "Proposal": 2, "Negotiate": 3, "Contract": 4}
OPEN_STAGES = set(RANK)
MIN_EVENTS = 20


def load_opp_hist():
    eng = get_engine()
    opp = pd.read_sql(
        "SELECT opportunity_id, product, status, amount_usd, created_date, close_date "
        "FROM fact_opportunity", eng).set_index("opportunity_id")
    hist = pd.read_sql("SELECT opportunity_id, to_stage, changed_on FROM pipeline_stage_history", eng)
    opp["created_date"] = pd.to_datetime(opp["created_date"])
    opp["close_date"] = pd.to_datetime(opp["close_date"])
    hist["changed_on"] = pd.to_datetime(hist["changed_on"])
    hist["rank"] = hist["to_stage"].map(RANK)
    return opp, hist


def _terminal(hist, as_of):
    h = hist[hist["changed_on"] <= as_of]
    return h[h["to_stage"].isin(["Won", "Lost"])].groupby("opportunity_id")["changed_on"].min()


def stage_durations(opp, hist, as_of) -> pd.DataFrame:
    """One row per (deal, stage reached): time from first entering that stage to close
    (or censored at as_of if unresolved)."""
    hle = hist[(hist["changed_on"] <= as_of) & hist["rank"].notna()]
    first_entry = hle.groupby(["opportunity_id", "rank"])["changed_on"].min().reset_index()
    term = _terminal(hist, as_of)
    first_entry["product"] = first_entry["opportunity_id"].map(opp["product"])
    first_entry["close"] = first_entry["opportunity_id"].map(term)
    resolved = first_entry["close"].notna()
    end = first_entry["close"].where(resolved, as_of)
    first_entry["duration"] = (end - first_entry["changed_on"]).dt.days.clip(lower=0)
    first_entry["event"] = resolved.astype(int)
    return first_entry.dropna(subset=["product", "duration"])


def fit_stage_kms(opp, hist, as_of) -> tuple[dict, dict]:
    """Return ((product,rank)->KM, product->KM fallback for sparse cells)."""
    d = stage_durations(opp, hist, as_of)
    stage_kms, prod_kms = {}, {}
    for (prod, rank), g in d.groupby(["product", "rank"]):
        if g["event"].sum() >= MIN_EVENTS:
            stage_kms[(prod, int(rank))] = KaplanMeierFitter().fit(g["duration"], g["event"])
    for prod, g in d.groupby("product"):           # pooled-over-stage fallback
        if g["event"].sum() >= MIN_EVENTS:
            prod_kms[prod] = KaplanMeierFitter().fit(g["duration"], g["event"])
    return stage_kms, prod_kms


def km_for(stage_kms, prod_kms, product, rank):
    return stage_kms.get((product, int(rank))) or prod_kms.get(product)


def open_deals_asof(opp, hist, as_of) -> pd.DataFrame:
    """Deals open at as_of: product, current rank, age-IN-current-stage, amount."""
    hle = hist[(hist["changed_on"] <= as_of) & hist["opportunity_id"].isin(opp.index)].sort_values("changed_on")
    last = hle.groupby("opportunity_id")["to_stage"].last()
    openids = last[last.isin(OPEN_STAGES)].index
    first_entry = hle[hle["rank"].notna()].groupby(["opportunity_id", "rank"])["changed_on"].min()
    rows = []
    for oid in openids:
        amount = opp.at[oid, "amount_usd"]
        if pd.isna(amount):                       # a few opps have no parseable amount
            continue
        r = RANK[last[oid]]
        entry = first_entry.get((oid, r))
        age = (as_of - entry).days if pd.notna(entry) else 0
        rows.append((oid, opp.at[oid, "product"], r, max(age, 0), float(amount)))
    return pd.DataFrame(rows, columns=["opportunity_id", "product", "rank", "age_in_stage", "amount_usd"])


def sample_remaining(km: KaplanMeierFitter, age_days, size: int, rng) -> np.ndarray:
    """Sample remaining days-to-close for deals of a given in-stage age, from S(t)/S(age)."""
    sf = km.survival_function_.iloc[:, 0]
    t, s = sf.index.to_numpy(float), sf.to_numpy(float)
    age = np.asarray(age_days, float)
    s_age = np.interp(age, t, s)
    u = rng.uniform(0.0, np.maximum(s_age, 1e-9), size=size)
    t_close = np.interp(u, s[::-1], t[::-1])
    return np.maximum(t_close - age, 0.0)


if __name__ == "__main__":
    opp, hist = load_opp_hist()
    stage_kms, prod_kms = fit_stage_kms(opp, hist, TODAY)
    print("Stage-aware median days-to-close (from entering each stage):\n")
    print(f"{'product':<8}{'Qualify':>9}{'Proposal':>10}{'Negotiate':>11}{'Contract':>10}")
    for prod in ("A", "B", "C"):
        row = [f"{km_for(stage_kms, prod_kms, prod, k).median_survival_time_:>.0f}"
               if km_for(stage_kms, prod_kms, prod, k) else "-" for k in (1, 2, 3, 4)]
        print(f"{prod:<8}{row[0]:>9}{row[1]:>10}{row[2]:>11}{row[3]:>10}")
    print("\n(Qualify should be MUCH longer than Negotiate — early deals close later.)")
