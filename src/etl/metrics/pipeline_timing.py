"""Pipeline model, step 2 — close-date timing via survival analysis.

When will an open deal close? We fit a Kaplan-Meier survival curve S(t) on time-from-
creation, per product, treating still-open deals as RIGHT-CENSORED (duration = age so far,
event = 0) rather than dropping them — averaging only closed deals would under-estimate
how long deals take. For an open deal already aged `a`, we sample its REMAINING time from
the conditional distribution S(t)/S(a), so an old deal's expected close is pushed later.

This feeds the Monte Carlo: each won trial places revenue in the period of its sampled
close date.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
from lifelines import KaplanMeierFitter

from etl.load.db import get_engine

TODAY = pd.Timestamp(date.today()).normalize()


def _durations() -> pd.DataFrame:
    opp = pd.read_sql(
        "SELECT product, status, created_date, close_date FROM fact_opportunity", get_engine())
    opp["created_date"] = pd.to_datetime(opp["created_date"])
    opp["close_date"] = pd.to_datetime(opp["close_date"])
    opp = opp[opp["created_date"].notna()].copy()
    resolved = opp["status"].isin(["won", "lost"])
    end = opp["close_date"].where(resolved, TODAY)
    opp["duration"] = (end - opp["created_date"]).dt.days.clip(lower=0)
    opp["event"] = resolved.astype(int)          # 1 = closed, 0 = still open (censored)
    return opp[opp["duration"].notna()]


def fit_by_product() -> dict[str, KaplanMeierFitter]:
    df = _durations()
    out = {}
    for prod, g in df.groupby("product"):
        km = KaplanMeierFitter().fit(g["duration"], g["event"], label=prod)
        out[prod] = km
    return out


def sample_remaining(km: KaplanMeierFitter, age_days, size: int, rng) -> np.ndarray:
    """Sample remaining days-to-close for open deals of a given age, from S(t)/S(age)."""
    sf = km.survival_function_.iloc[:, 0]
    t, s = sf.index.to_numpy(float), sf.to_numpy(float)
    age = np.asarray(age_days, float)
    s_age = np.interp(age, t, s)                 # S(age)
    u = rng.uniform(0.0, np.maximum(s_age, 1e-9), size=size)
    # invert: find t where S(t) = u (S decreasing -> use reversed arrays)
    t_close = np.interp(u, s[::-1], t[::-1])
    return np.maximum(t_close - age, 0.0)


if __name__ == "__main__":
    df = _durations()
    kms = fit_by_product()
    print("Close-timing survival by product (open deals censored):\n")
    print(f"{'prod':<5}{'deals':>7}{'open(cens)':>11}{'median_days_to_close':>22}")
    for prod, km in kms.items():
        g = df[df["product"] == prod]
        print(f"{prod:<5}{len(g):>7}{int((g['event']==0).sum()):>11}{km.median_survival_time_:>22.0f}")

    # sanity: remaining time for an open deal aged 30 vs 180 days (Product B)
    rng = np.random.default_rng(0)
    for age in (30, 180):
        rem = sample_remaining(kms["B"], age, 10000, rng)
        print(f"\nB open deal aged {age}d -> remaining days median {np.median(rem):.0f}, "
              f"p90 {np.percentile(rem,90):.0f}")
