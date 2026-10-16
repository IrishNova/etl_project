"""Model step 2a — expected-renewal layer (closed-form mean / bar heights).

The middle layer of the stacked bar: revenue we EXPECT to retain past expiry. For each
currently-active recurring contract, once its current term ends it renews with its
segment probability p, contributing a fresh term weighted by p; that renewal renews
again weighted by p^2, and so on — a geometric survival decay, recognized straight-line.

No double-counting: we only project renewals for contracts whose term ends in the FUTURE
(eff_end >= as_of). Already-expired-and-renewed contracts are realized successors already
in the data (the floor). Cancelled contracts churned, so they don't renew.

Core abstraction: a **recognition tensor** A[segment, generation, week] holding the
recognized $ per week at p=1. Then expected[week] = sum_seg sum_g A[seg,g,week] * p_seg^g.
The closed-form (this file) and the Monte Carlo band (band.py) both reduce this one tensor,
so they are guaranteed consistent — the MC with p fixed reproduces this exactly.

`rates` is a pluggable {(product, region): p} map — flat today, recency-weighted later.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from etl.metrics.audit_renewals import _effective_end, _load_recurring
from etl.metrics.retention import estimate

DAYS_PER_YEAR = 365.25
MAX_GEN = 6  # renewal generations (covers a 3y horizon even for annual terms)


def default_rates(as_of=None) -> dict:
    est = estimate(as_of)
    rates = {(r.product, r.region): r.grr for r in est.itertuples() if r.product != "ALL"}
    allrow = est[est["product"] == "ALL"]
    rates[("ALL", "ALL")] = float(allrow["grr"].iloc[0]) if len(allrow) else 0.0
    return rates


def _active(as_of: pd.Timestamp) -> pd.DataFrame:
    df = _load_recurring()
    df["eff_end"] = _effective_end(df)
    df = df[(df["cancel_date"].isna()) & (df["eff_end"] >= as_of)].copy()
    df["daily"] = df["arr_usd"].astype(float) / DAYS_PER_YEAR
    df["term"] = df["end_date"].sub(df["start_date"]).dt.days.clip(lower=1)
    return df


def recognition_tensor(as_of=None, horizon_weeks: int = 156):
    """Return (segments, week_starts, A) where A[seg, gen, week] = recognized $ at p=1."""
    as_of = pd.Timestamp(as_of or date.today()).normalize()
    df = _active(as_of)

    week0 = as_of - pd.Timedelta(days=as_of.weekday())
    weeks = pd.date_range(week0, periods=horizon_weeks, freq="7D")
    ws = np.array([np.datetime64(w.date(), "D") for w in weeks])
    horizon = np.datetime64((week0 + pd.Timedelta(weeks=horizon_weeks)).date(), "D")
    we = np.minimum(ws + np.timedelta64(6, "D"), horizon - np.timedelta64(1, "D"))

    segments = sorted(set(zip(df["product"], df["region"])))
    seg_idx = {s: i for i, s in enumerate(segments)}
    A = np.zeros((len(segments), MAX_GEN, len(weeks)))

    daily = df["daily"].to_numpy()
    eff = df["eff_end"].to_numpy("datetime64[D]")
    term = df["term"].to_numpy()
    segs = [seg_idx[(p, r)] for p, r in zip(df["product"], df["region"])]

    for c in range(len(df)):
        si, e, t, d = segs[c], eff[c], int(term[c]), daily[c]
        for g in range(1, MAX_GEN + 1):
            gs = e + np.timedelta64(t * (g - 1), "D")
            ge = e + np.timedelta64(t * g, "D")  # exclusive
            lo = np.maximum(gs, ws)
            hi = np.minimum(ge - np.timedelta64(1, "D"), we)
            days = np.maximum((hi - lo).astype(int) + 1, 0)
            if days.any():
                A[si, g - 1, :] += d * days
    return segments, [w.date() for w in weeks], A


def expected_from_tensor(A: np.ndarray, p_vec: np.ndarray) -> np.ndarray:
    """Reduce the tensor at a given per-segment p: sum_seg sum_g A[seg,g,:] * p_seg^g."""
    exp = np.zeros(A.shape[2])
    for g in range(1, MAX_GEN + 1):
        exp += (A[:, g - 1, :] * (p_vec ** g)[:, None]).sum(axis=0)
    return exp


def expected_renewal_runoff(rates=None, as_of=None, horizon_weeks: int = 156) -> pd.DataFrame:
    as_of = pd.Timestamp(as_of or date.today()).normalize()
    rates = rates or default_rates(as_of)
    segments, weeks, A = recognition_tensor(as_of, horizon_weeks)
    p_vec = np.array([rates.get(s, rates[("ALL", "ALL")]) for s in segments])
    return pd.DataFrame({"week_start": weeks, "expected_usd": expected_from_tensor(A, p_vec)})


def reconcile(rates=None, as_of=None, horizon_weeks: int = 156) -> None:
    """Weekly buckets must sum to the direct per-contract expected value."""
    as_of = pd.Timestamp(as_of or date.today()).normalize()
    rates = rates or default_rates(as_of)
    week0 = as_of - pd.Timedelta(days=as_of.weekday())
    w0 = np.datetime64(week0.date(), "D")
    horizon = np.datetime64((week0 + pd.Timedelta(weeks=horizon_weeks)).date(), "D")

    df = _active(as_of)
    daily = df["daily"].to_numpy()
    eff = df["eff_end"].to_numpy("datetime64[D]")
    term = df["term"].to_numpy()
    p = np.array([rates.get((pr, rg), rates[("ALL", "ALL")])
                  for pr, rg in zip(df["product"], df["region"])])

    direct = 0.0
    for g in range(1, MAX_GEN + 1):
        gs = eff + (term * (g - 1)).astype("timedelta64[D]")
        ge = eff + (term * g).astype("timedelta64[D]")
        lo = np.maximum(gs, w0)
        hi = np.minimum(ge - np.timedelta64(1, "D"), horizon - np.timedelta64(1, "D"))
        days = np.maximum((hi - lo).astype(int) + 1, 0)
        direct += float((daily * (p ** g) * days).sum())

    grid = float(expected_renewal_runoff(rates, as_of, horizon_weeks)["expected_usd"].sum())
    ok = bool(np.isclose(direct, grid, rtol=0, atol=0.01))
    print("===== RECONCILIATION — expected-renewal buckets vs direct =====")
    print(f"sum of weekly buckets : ${grid:,.2f}")
    print(f"direct per-contract   : ${direct:,.2f}")
    print(f"  [{'PASS' if ok else 'FAIL'}] buckets sum to the whole (within 1c)")
    if not ok:
        raise SystemExit("Expected-renewal reconciliation FAILED.")


if __name__ == "__main__":
    from etl.metrics.runoff import weekly_runoff

    exp = expected_renewal_runoff()
    floor = weekly_runoff()[["week_start", "guaranteed_usd"]]
    stack = floor.merge(exp, on="week_start", how="outer").fillna(0.0).sort_values("week_start")
    stack["total_usd"] = stack["guaranteed_usd"] + stack["expected_usd"]

    print(f"Expected renewals over 3y horizon: ${exp['expected_usd'].sum():,.0f}\n")
    print("--- the stack taking shape (guaranteed floor + expected renewals) ---")
    disp = stack.iloc[[0, 12, 26, 52, 78, 104, 130, 155]].copy()
    for c in ["guaranteed_usd", "expected_usd", "total_usd"]:
        disp[c] = disp[c].round(0).astype(int)
    print(disp.to_string(index=False))
    print()
    reconcile()
