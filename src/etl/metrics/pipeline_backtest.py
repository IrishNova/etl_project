"""Pipeline model, step 4 — point-in-time, leakage-free walk-forward backtest.

For each past origin T we reconstruct the pipeline AS OF T from the stage-change log
(an opp's stage at T = its last to_stage with changed_on <= T), refit the win-rate
calibration and survival timing on deals RESOLVED BEFORE T (never future outcomes),
forecast bookings in the window [T, T+h], and compare to what actually closed-won in
that window among the deals that were open at T.

Leakage controls: stage/age frozen at T; calibration & timing trained only on pre-T
resolved deals; all deals open at T are included (no survivorship). Known limitation:
we have only the CURRENT amount (no historical amount snapshots), used for both forecast
and actual, so amount restatement is not point-in-time — flagged, affects both sides equally.

Scored with WAPE, mean bias, interval coverage (PICP) and pinball loss across origins.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from lifelines import KaplanMeierFitter

from etl.load.db import get_engine
from etl.metrics.pipeline_timing import sample_remaining

RANK = {"Qualify": 1, "Proposal": 2, "Negotiate": 3, "Contract": 4}
OPEN_STAGES = set(RANK)
H_MONTHS = 2
N_TRIALS = 2000


def _load():
    eng = get_engine()
    opp = pd.read_sql("SELECT opportunity_id, product, amount_usd, created_date FROM fact_opportunity", eng)
    hist = pd.read_sql("SELECT opportunity_id, to_stage, changed_on FROM pipeline_stage_history", eng)
    opp["created_date"] = pd.to_datetime(opp["created_date"])
    hist["changed_on"] = pd.to_datetime(hist["changed_on"])
    hist["rank"] = hist["to_stage"].map(RANK)
    won_date = hist[hist["to_stage"] == "Won"].groupby("opportunity_id")["changed_on"].min()
    return opp.set_index("opportunity_id"), hist, won_date


def _stage_at(hist, T):
    h = hist[hist["changed_on"] <= T]
    return h.sort_values("changed_on").groupby("opportunity_id")["to_stage"].last()


def _calib_at(opp, hist, T):
    stage = _stage_at(hist, T)
    resolved = stage[stage.isin(["Won", "Lost"])]
    reached = hist[(hist["changed_on"] <= T) & hist["rank"].notna()].groupby("opportunity_id")["rank"].max()
    r = pd.DataFrame({"outcome": resolved}).join(reached.rename("reached")).dropna(subset=["reached"])
    won, lost = {}, {}
    for k in (1, 2, 3, 4):
        c = r[r["reached"] >= k]
        won[k], lost[k] = int((c["outcome"] == "Won").sum()), int((c["outcome"] == "Lost").sum())
    return won, lost


def _timing_at(opp, hist, T):
    stage = _stage_at(hist, T)
    term = hist[(hist["changed_on"] <= T) & hist["to_stage"].isin(["Won", "Lost"])] \
        .groupby("opportunity_id")["changed_on"].min()
    df = opp[opp["created_date"] <= T].copy()
    df["term"] = term.reindex(df.index)
    df["stage_at_T"] = stage.reindex(df.index)
    resolved = df["term"].notna()
    df["dur"] = np.where(resolved, (df["term"] - df["created_date"]).dt.days,
                         (T - df["created_date"]).dt.days)
    df["event"] = resolved.astype(int)
    df = df[(resolved | df["stage_at_T"].isin(OPEN_STAGES)) & (df["dur"] >= 0)]
    kms = {}
    for prod, g in df.groupby("product"):
        if g["event"].sum() > 5:
            kms[prod] = KaplanMeierFitter().fit(g["dur"], g["event"])
    return kms


def _open_at(opp, hist, T):
    stage = _stage_at(hist, T)
    df = opp.join(stage.rename("stage_at_T"))
    df = df[df["stage_at_T"].isin(OPEN_STAGES) & (df["created_date"] <= T)].copy()
    df["rank"] = df["stage_at_T"].map(RANK)
    df["age"] = (T - df["created_date"]).dt.days.clip(lower=0)
    return df


def _forecast(deals, won, lost, kms, T, rng):
    wdays = (T + pd.DateOffset(months=H_MONTHS) - T).days
    out = np.zeros(N_TRIALS)
    for prod, g in deals.groupby("product"):
        if prod not in kms:
            continue
        ranks, amt, ages = g["rank"].to_numpy(int), g["amount_usd"].to_numpy(float), g["age"].to_numpy(float)
        m = len(g)
        p = np.empty((N_TRIALS, m))
        for k in (1, 2, 3, 4):
            col = ranks == k
            if col.any():
                p[:, col] = rng.beta(won[k] + 1, lost[k] + 1, size=N_TRIALS)[:, None]
        win = rng.random((N_TRIALS, m)) < p
        rem = np.vstack([sample_remaining(kms[prod], ages[j], N_TRIALS, rng) for j in range(m)]).T
        out += ((win & (rem < wdays)) * amt[None, :]).sum(axis=1)
    return out


def _actual(deals, won_date, T):
    end = T + pd.DateOffset(months=H_MONTHS)
    wd = won_date.reindex(deals.index)
    won_in = wd.notna() & (wd >= T) & (wd < end)
    return float(deals.loc[won_in, "amount_usd"].sum())


def _pinball(a, q_levels, q_vals):
    return np.mean([(a - f) * lv if a >= f else (f - a) * (1 - lv) for lv, f in zip(q_levels, q_vals)])


from functools import lru_cache  # noqa: E402


@lru_cache(maxsize=1)
def debias_factor(seed: int = 0) -> float:
    """Full-sample multiplicative bias correction = sum(actual)/sum(p50) from the backtest.
    Applied to the live forecast to remove the measured systematic over/under-forecast."""
    f = walk_forward(seed=seed)
    return float(f["actual"].sum() / f["p50"].sum())


def walk_forward(start="2024-01-01", end="2025-12-01", seed=0) -> pd.DataFrame:
    opp, hist, won_date = _load()
    rng = np.random.default_rng(seed)
    rows = []
    for T in pd.date_range(start, end, freq="MS"):
        deals = _open_at(opp, hist, T)
        won, lost = _calib_at(opp, hist, T)
        kms = _timing_at(opp, hist, T)
        if deals.empty or not kms or min(won[k] + lost[k] for k in (1, 2, 3, 4)) < 20:
            continue
        fc = _forecast(deals, won, lost, kms, T, rng)
        a = _actual(deals, won_date, T)
        p10, p50, p90 = np.percentile(fc, [10, 50, 90])
        rows.append({"T": T.strftime("%Y-%m"), "n_open": len(deals), "actual": a,
                     "p10": p10, "p50": p50, "p90": p90,
                     "covered": p10 <= a <= p90, "pinball": _pinball(a, [.1, .5, .9], [p10, p50, p90])})
    return pd.DataFrame(rows)


if __name__ == "__main__":
    df = walk_forward()
    err = df["p50"] - df["actual"]
    print(f"Walk-forward pipeline backtest — {len(df)} monthly origins, {H_MONTHS}-month window:\n")
    show = df.copy()
    for c in ("actual", "p10", "p50", "p90"):
        show[c] = (show[c] / 1000).round(0).astype(int)
    print(show[["T", "n_open", "actual", "p10", "p50", "p90", "covered"]].to_string(index=False))
    print("\nSCORES (raw)")
    print(f"  WAPE          : {err.abs().sum()/df['actual'].sum()*100:.1f}%")
    print(f"  mean bias     : {err.sum()/df['actual'].sum()*100:+.1f}%")
    print(f"  coverage (80%): {df['covered'].mean()*100:.0f}%  (target ~80)")

    # Leave-one-out debias: each origin corrected by the OTHER origins' factor (honest).
    cov, derr = [], []
    for i in range(len(df)):
        o = df.drop(df.index[i])
        fac = o["actual"].sum() / o["p50"].sum()
        lo, mid, hi = df["p10"].iloc[i] * fac, df["p50"].iloc[i] * fac, df["p90"].iloc[i] * fac
        a = df["actual"].iloc[i]
        cov.append(lo <= a <= hi); derr.append(mid - a)
    derr = np.array(derr)
    print(f"\nDEBIAS factor (full-sample): {debias_factor():.3f}")
    print("SCORES (leave-one-out debiased)")
    print(f"  WAPE          : {np.abs(derr).sum()/df['actual'].sum()*100:.1f}%")
    print(f"  mean bias     : {derr.sum()/df['actual'].sum()*100:+.1f}%")
    print(f"  coverage (80%): {np.mean(cov)*100:.0f}%  (target ~80)")
