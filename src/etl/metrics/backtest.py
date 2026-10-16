"""Model step 3 — walk-forward backtest of the one-cycle renewal prediction.

Honest scope: we validate the gen-1 renewal (the empirically testable core), not the
3-year compounding (no future to check it against). For each split date T we:
  - TRAIN a segment rate on events MATURED before T (censoring lag inside the loop),
  - FREEZE it, PREDICT the retained revenue of the cohort expiring in [T, T+quarter]
    (point + a bootstrap band),
  - compare to the ACTUAL retained revenue of that cohort (known now that it has resolved).
Only score windows old enough to be fully matured (T + h + lag <= today).

Two train modes (rolling / expanding) x two rate schemes (flat / recency-weighted) are
compared on: mean signed bias, MAE, band coverage (did actual land in P10-P90?), pinball.
The winner settles the flat-vs-recency decision. Few fully-matured windows exist, so power
is limited — reported plainly.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from etl.metrics.audit_renewals import _load_recurring, reconstruct
from etl.metrics.retention import MATURATION_LAG, N_MIN, WINDOW_AFTER, WINDOW_BEFORE

RETAIN_COL = "succ_arr"  # NRR (net, uncapped) drives the projection; GRR is a KPI only
H_DAYS = 91              # test-cohort length (a quarter)
ROLL_TRAIN_DAYS = 730    # rolling-window training length (2y)
HALFLIFE_DAYS = 365      # recency weighting half-life
N_BOOT = 1000


def _events() -> pd.DataFrame:
    ev = reconstruct(_load_recurring(), win_before=WINDOW_BEFORE, win_after=WINDOW_AFTER)
    return ev[["product", "region", "eff_end", "pred_arr", "retained_arr", "succ_arr", "renewed"]].copy()


def _weights(sub: pd.DataFrame, T: pd.Timestamp, recency: bool) -> np.ndarray:
    if not recency:
        return np.ones(len(sub))
    age_days = (T - sub["eff_end"]).dt.days.to_numpy()
    return 0.5 ** (age_days / HALFLIFE_DAYS)


def _pool(train: pd.DataFrame, prod: str, region: str) -> pd.DataFrame:
    seg = train[(train["product"] == prod) & (train["region"] == region)]
    if len(seg) >= N_MIN:
        return seg
    prod_pool = train[train["product"] == prod]
    return prod_pool if len(prod_pool) >= N_MIN else train


def _rate_draws(train, prod, region, T, recency, rng, b=N_BOOT):
    """(point p, bootstrap draws) for a segment, with pooling + optional recency weights."""
    sub = _pool(train, prod, region)
    w = _weights(sub, T, recency)
    pred, ret = sub["pred_arr"].to_numpy(), sub[RETAIN_COL].to_numpy()
    point = (w * ret).sum() / (w * pred).sum() if (w * pred).sum() else np.nan
    n = len(sub)
    p = w / w.sum()
    idx = rng.choice(n, size=(b, n), p=p)
    draws = ret[idx].sum(1) / pred[idx].sum(1)
    return point, draws


def _train_set(ev, as_of, mode):
    cutoff = as_of - pd.Timedelta(days=MATURATION_LAG)
    if mode == "expanding":
        return ev[ev["eff_end"] < cutoff]
    return ev[(ev["eff_end"] < cutoff) & (ev["eff_end"] >= cutoff - pd.Timedelta(days=ROLL_TRAIN_DAYS))]


def segment_rates(as_of=None, mode="expanding", recency=True) -> dict:
    """Production per-segment rates under the backtest-chosen config (default rolling+recency)."""
    as_of = pd.Timestamp(as_of or date.today()).normalize()
    ev = _events()
    train = _train_set(ev, as_of, mode)
    rates = {}
    for prod, region in sorted(set(zip(ev["product"], ev["region"]))):
        sub = _pool(train, prod, region)
        w = _weights(sub, as_of, recency)
        pred, ret = sub["pred_arr"].to_numpy(), sub[RETAIN_COL].to_numpy()
        rates[(prod, region)] = (w * ret).sum() / (w * pred).sum() if (w * pred).sum() else np.nan
    w = _weights(train, as_of, recency)
    rates[("ALL", "ALL")] = (w * train[RETAIN_COL]).sum() / (w * train["pred_arr"]).sum()
    return rates


def empirical_errors(mode="expanding", recency=True, seed=0) -> np.ndarray:
    """Realized relative forecast errors (actual-pred)/pred — the backtested per-cycle
    dispersion the forward band samples. Default = the chosen config (rolling+recency)."""
    df = walk_forward(mode=mode, recency=recency, seed=seed)
    return ((df["actual"] - df["pred"]) / df["pred"]).to_numpy()


def _pinball(actual: float, q_levels, q_vals) -> float:
    loss = 0.0
    for lv, f in zip(q_levels, q_vals):
        loss += (actual - f) * lv if actual >= f else (f - actual) * (1 - lv)
    return loss / len(q_levels)


def _one_window(ev, T, mode, recency, rng):
    cutoff = T - pd.Timedelta(days=MATURATION_LAG)
    if mode == "expanding":
        train = ev[ev["eff_end"] < cutoff]
    else:
        train = ev[(ev["eff_end"] < cutoff) & (ev["eff_end"] >= cutoff - pd.Timedelta(days=ROLL_TRAIN_DAYS))]
    cohort = ev[(ev["eff_end"] >= T) & (ev["eff_end"] < T + pd.Timedelta(days=H_DAYS))]
    if len(train) < N_MIN or cohort.empty:
        return None

    by_seg = cohort.groupby(["product", "region"])["pred_arr"].sum()
    pred_point = 0.0
    draws_total = np.zeros(N_BOOT)
    for (prod, region), cohort_pred in by_seg.items():
        point, draws = _rate_draws(train, prod, region, T, recency, rng)
        pred_point += cohort_pred * point
        draws_total += cohort_pred * draws
    actual = float(cohort[RETAIN_COL].sum())
    p10, p50, p90 = np.percentile(draws_total, [10, 50, 90])
    return {
        "T": T.date(), "n_cohort": len(cohort), "actual": actual, "pred": pred_point,
        "p10": p10, "p90": p90, "covered": p10 <= actual <= p90,
        "pinball": _pinball(actual, [.1, .5, .9], [p10, p50, p90]),
    }


def walk_forward(mode="expanding", recency=False, seed=0) -> pd.DataFrame:
    ev = _events()
    today = pd.Timestamp(date.today()).normalize()
    rng = np.random.default_rng(seed)
    last_T = today - pd.Timedelta(days=H_DAYS + MATURATION_LAG)
    rows = []
    T = pd.Timestamp("2023-01-02")
    while T <= last_T:
        r = _one_window(ev, T, mode, recency, rng)
        if r:
            rows.append(r)
        T += pd.Timedelta(days=H_DAYS)
    return pd.DataFrame(rows)


def calibrate_loo(df: pd.DataFrame, lo: float = 0.1, hi: float = 0.9) -> dict:
    """Empirical band from realized relative errors, leave-one-out (honest coverage).

    The bootstrap band only held rate-sampling noise and was too tight. The realized
    errors e = (actual - pred)/pred ARE the true out-of-sample dispersion (drift +
    idiosyncrasy included). For each window we build the band from the OTHER windows'
    errors and test the held-out one — so coverage isn't calibrated on itself.
    """
    e = ((df["actual"] - df["pred"]) / df["pred"]).to_numpy()
    n = len(e)
    covered = []
    for i in range(n):
        others = np.delete(e, i)
        ql, qh = np.quantile(others, [lo, hi])
        band_lo = df["pred"].iloc[i] * (1 + ql)
        band_hi = df["pred"].iloc[i] * (1 + qh)
        covered.append(band_lo <= df["actual"].iloc[i] <= band_hi)
    full_lo, full_hi = np.quantile(e, [lo, hi])
    return {"loo_coverage_%": 100 * np.mean(covered),
            "band_lo_%": 100 * full_lo, "band_hi_%": 100 * full_hi}


def _score(df: pd.DataFrame) -> dict:
    err = df["pred"] - df["actual"]
    return {
        "windows": len(df),
        "bias_$": err.mean(),
        "MAE_$": err.abs().mean(),
        "bias_%": (err.sum() / df["actual"].sum()) * 100,
        "coverage_%": df["covered"].mean() * 100,
        "pinball_$": df["pinball"].mean(),
    }


if __name__ == "__main__":
    print("Walk-forward backtest — one-cycle renewal prediction (quarterly cohorts)\n")
    summary = []
    for mode in ("expanding", "rolling"):
        for recency in (False, True):
            df = walk_forward(mode=mode, recency=recency)
            s = {"mode": mode, "scheme": "recency" if recency else "flat", **_score(df)}
            summary.append(s)
    out = pd.DataFrame(summary)
    for c in ["bias_$", "MAE_$", "pinball_$"]:
        out[c] = out[c].round(0).astype(int)
    for c in ["bias_%", "coverage_%"]:
        out[c] = out[c].round(1)
    print(out.to_string(index=False))

    print("\n--- band recalibration: bootstrap (too tight) vs empirical LOO ---")
    cal = []
    for mode in ("expanding", "rolling"):
        for recency in (False, True):
            df = walk_forward(mode=mode, recency=recency)
            boot_cov = df["covered"].mean() * 100
            c = calibrate_loo(df)
            cal.append({"mode": mode, "scheme": "recency" if recency else "flat",
                        "bootstrap_cov_%": round(boot_cov, 1),
                        "calibrated_cov_%": round(c["loo_coverage_%"], 1),
                        "band": f"{c['band_lo_%']:+.1f}% .. {c['band_hi_%']:+.1f}%"})
    print(pd.DataFrame(cal).to_string(index=False))
