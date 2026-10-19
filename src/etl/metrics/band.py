"""Monte Carlo band over the full three-layer stack, calibrated to the backtests.

Total_path = guaranteed floor (certain, no shock)
           + expected renewals  (per-cycle error ~±7%, compounding — from the GRR backtest)
           + new business       (per-quarter error ~±18%, compounding — from the new-biz backtest)

Each uncertain layer draws its own empirical residuals and compounds them across its
cycles, so the band widens with horizon. With zero error every path reduces to the
closed-form point estimate (validation). The MC is seeded -> stable band run to run.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
from scipy.ndimage import uniform_filter1d

from etl.metrics.backtest import empirical_errors, segment_rates
from etl.metrics.new_business import forward_new_weekly, newbiz_errors, trend_sigma
from etl.metrics.pipeline_forecast import leadtime_weight, weekly_booking_samples
from etl.metrics.projection import MAX_GEN, recognition_tensor
from etl.metrics.runoff import weekly_runoff


def _floor_aligned(weeks, as_of) -> np.ndarray:
    f = weekly_runoff(as_of=as_of)[["week_start", "guaranteed_usd"]]
    m = dict(zip(f["week_start"], f["guaranteed_usd"]))
    return np.array([m.get(w, 0.0) for w in weeks])


def _renewal_base(A: np.ndarray, p_vec: np.ndarray) -> np.ndarray:
    base = np.zeros((MAX_GEN, A.shape[2]))
    for g in range(1, MAX_GEN + 1):
        base[g - 1] = (A[:, g - 1, :] * (p_vec ** g)[:, None]).sum(axis=0)
    return base


def run_mc(n_paths: int = 2000, as_of=None, seed: int = 0, horizon_weeks: int = 156):
    as_of = pd.Timestamp(as_of or date.today()).normalize()
    rng = np.random.default_rng(seed)
    n_weeks = horizon_weeks

    # --- Layer 1: guaranteed floor (certain) ---
    segments, weeks, A = recognition_tensor(as_of, horizon_weeks)
    floor = _floor_aligned(weeks, as_of)

    # --- Layer 2: expected renewals (per-cycle ±7%, compounding) ---
    rates = segment_rates(as_of)
    p_vec = np.array([rates.get(s, rates[("ALL", "ALL")]) for s in segments])
    ren_base = _renewal_base(A, p_vec)                        # (MAX_GEN, n_weeks)
    Er = rng.choice(empirical_errors(), size=(n_paths, MAX_GEN))
    ren_paths = np.cumprod(1.0 + Er, axis=1) @ ren_base       # (n_paths, n_weeks)

    # --- Layer 3: new business = PIPELINE (near-term) blended with RUN-RATE (far-term) ---
    # Run-rate paths (far horizon, where the pipeline is "unborn"): damped center + trend +
    # level uncertainty, as before.
    nb_base, _, _ = forward_new_weekly(n_weeks)
    years = np.arange(n_weeks) / 52.0
    dg = rng.normal(0.0, trend_sigma(), size=n_paths)
    growth = np.maximum(1.0 + dg, 0.01)[:, None] ** years[None, :]
    Eq = rng.choice(newbiz_errors(), size=n_paths)
    rr_paths = nb_base[None, :] * growth * (1.0 + Eq[:, None])
    # Pipeline paths (near horizon): resample the backtested weekly booking distribution,
    # then SMOOTH (the raw pipeline is lumpy month-to-month — hot now, cliff at the horizon;
    # that lumpiness, not the blend, is what whipsaws the near term). An 8-week moving
    # average turns it into a believable near-term level.
    pipe = uniform_filter1d(weekly_booking_samples(n_weeks, seed=seed), size=8, axis=1, mode="nearest")
    pipe_paths = pipe[rng.integers(0, len(pipe), size=n_paths)]
    # Blend by the data-derived lead-time weight (bounded weighted average, no valley/hump).
    w = leadtime_weight(n_weeks)
    nb_paths = w[None, :] * pipe_paths + (1.0 - w)[None, :] * rr_paths

    total_paths = floor[None, :] + ren_paths + nb_paths
    p10, p50, p90 = np.percentile(total_paths, [10, 50, 90], axis=0)
    out = pd.DataFrame({
        "week_start": weeks,
        "guaranteed": floor,
        "renewals_p50": np.percentile(ren_paths, 50, axis=0),
        "newbiz_p50": np.percentile(nb_paths, 50, axis=0),
        "total_p10": p10, "total_p50": p50, "total_p90": p90,
    })
    # Drop the current partial week (today is mid-week): the floor is day-prorated but
    # new business isn't, so the stub bar is distorted. Start at the first full week.
    if as_of.weekday() != 0:
        out = out.iloc[1:].reset_index(drop=True)
        total_paths = total_paths[:, 1:]

    pieces = {"floor": floor, "ren_base": ren_base, "nb_base": nb_base}
    return out, total_paths, pieces


if __name__ == "__main__":
    out, total_paths, pieces = run_mc()
    cf = pieces["floor"] + pieces["ren_base"].sum(axis=0) + pieces["nb_base"]
    print("Three-layer Monte Carlo band\n")
    print(f"[{'PASS' if np.isfinite(out['total_p50']).all() else 'FAIL'}] band computed")
    print(f"closed-form total (3y sum): ${cf.sum():,.0f}")
    print(f"MC median total   (3y sum): ${out['total_p50'].sum():,.0f}\n")
    disp = out.iloc[[0, 26, 52, 78, 104, 130, 155]].copy()
    disp["whisker_%"] = ((disp["total_p90"] - disp["total_p10"]) / 2 / disp["total_p50"] * 100).round(1)
    for c in ["guaranteed", "renewals_p50", "newbiz_p50", "total_p10", "total_p50", "total_p90"]:
        disp[c] = disp[c].round(0).astype(int)
    print(disp.to_string(index=False))
