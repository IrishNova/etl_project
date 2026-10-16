"""Model step 2b — Monte Carlo uncertainty band (the whisker on the stack).

The closed-form (projection.py) gives the bar heights at the point-estimate rates. This
wraps it in parameter uncertainty: each path draws every segment's renewal rate p from its
bootstrap distribution and HOLDS it across all renewal generations (persistence — a path
where a segment is weak stays weak, so bad regimes compound into a fat right tail; redrawing
per cycle would cancel out and fake a tight band). Across paths we read P10/P50/P90 per week
= the whisker on the stacked bar's total.

Speed + consistency: everything reduces the recognition tensor A[seg, gen, week] from
projection.py, so one path is just (P**g).T @ A. With p FIXED at the point estimate this
reproduces the closed form exactly (validation). With p sampled, the mean sits slightly
above it — real convexity (Jensen on p^g), not a bug.

Band = parameter/regime uncertainty only (not per-contract coin-flips, which average out).
A correlated cross-segment regime shock + explicit stress scenario are a labelled overlay
left for later, by design (no arbitrary stress number baked in here).
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from etl.metrics.projection import (
    MAX_GEN,
    default_rates,
    expected_from_tensor,
    recognition_tensor,
)
from etl.metrics.retention import N_MIN, _boot_grr, matured_events
from etl.metrics.runoff import weekly_runoff


def _segment_draws(segments, as_of, n_paths, rng) -> np.ndarray:
    """(n_seg, n_paths) bootstrap draws of p per segment (pool to product if thin)."""
    ev = matured_events(as_of)
    out = np.zeros((len(segments), n_paths))
    for i, (prod, region) in enumerate(segments):
        g = ev[(ev["product"] == prod) & (ev["region"] == region)]
        if len(g) < N_MIN:
            g = ev[ev["product"] == prod]
        out[i] = _boot_grr(g, rng, b=n_paths)
    return out


def _floor_aligned(weeks, as_of) -> np.ndarray:
    f = weekly_runoff(as_of=as_of)[["week_start", "guaranteed_usd"]]
    m = dict(zip(f["week_start"], f["guaranteed_usd"]))
    return np.array([m.get(w, 0.0) for w in weeks])


def run_mc(n_paths: int = 2000, as_of=None, seed: int = 0, horizon_weeks: int = 156):
    as_of = pd.Timestamp(as_of or date.today()).normalize()
    rng = np.random.default_rng(seed)

    segments, weeks, A = recognition_tensor(as_of, horizon_weeks)
    floor = _floor_aligned(weeks, as_of)
    P = _segment_draws(segments, as_of, n_paths, rng)          # (n_seg, n_paths)

    # Expected per path per week, holding each path's p across generations.
    exp_paths = np.zeros((n_paths, len(weeks)))
    for g in range(1, MAX_GEN + 1):
        exp_paths += (P ** g).T @ A[:, g - 1, :]               # (n_paths, n_weeks)
    total_paths = exp_paths + floor[None, :]

    p10, p50, p90 = np.percentile(total_paths, [10, 50, 90], axis=0)
    out = pd.DataFrame({
        "week_start": weeks, "guaranteed": floor,
        "expected_p50": np.percentile(exp_paths, 50, axis=0),
        "total_p10": p10, "total_p50": p50, "total_p90": p90,
    })
    return out, exp_paths, (segments, weeks, A)


def _validate_and_report(n_paths=2000, as_of=None, seed=0):
    as_of = pd.Timestamp(as_of or date.today()).normalize()
    out, exp_paths, (segments, weeks, A) = run_mc(n_paths, as_of, seed)

    # Validation: fixed-p reduction of the tensor == the closed form, exactly.
    rates = default_rates(as_of)
    p_vec = np.array([rates.get(s, rates[("ALL", "ALL")]) for s in segments])
    point = expected_from_tensor(A, p_vec)
    from etl.metrics.projection import expected_renewal_runoff
    cf = expected_renewal_runoff(as_of=as_of)["expected_usd"].to_numpy()
    exact = np.allclose(point, cf, atol=1e-6)

    point_total = point.sum()
    sampled_total = exp_paths.sum(axis=1)
    jensen = sampled_total.mean() - point_total
    cov = sampled_total.std() / sampled_total.mean()

    # Convergence: P90 of 3y total, half the paths vs all.
    tot = total_3y = (out["total_p50"])  # placeholder to keep names; recompute below
    half = np.percentile(sampled_total[: n_paths // 2], 90)
    full = np.percentile(sampled_total, 90)

    print(f"Monte Carlo band — {n_paths:,} paths, as of {as_of.date()}\n")
    print(f"[{'PASS' if exact else 'FAIL'}] fixed-p MC reduces to the closed form exactly")
    print(f"closed-form expected (3y): ${point_total:,.0f}")
    print(f"MC mean expected     (3y): ${sampled_total.mean():,.0f}  "
          f"(+${jensen:,.0f} convexity / Jensen, expected to be small & positive)")
    print(f"path-total CoV: {cov:.2%}   P90(3y) half vs full: "
          f"${half:,.0f} vs ${full:,.0f} (converged if close)\n")

    disp = out.iloc[[0, 12, 26, 52, 78, 104, 130, 155]].copy()
    disp["whisker_±"] = ((disp["total_p90"] - disp["total_p10"]) / 2)
    for c in ["guaranteed", "expected_p50", "total_p10", "total_p50", "total_p90", "whisker_±"]:
        disp[c] = disp[c].round(0).astype(int)
    print("--- stack with band (whisker should WIDEN to the right) ---")
    print(disp.to_string(index=False))


if __name__ == "__main__":
    _validate_and_report()
