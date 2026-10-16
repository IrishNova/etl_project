"""Model step 1 — estimate GRR per segment, WITH its uncertainty.

This is the pairs-screen analog: it produces the "rate + how sure we are" that the
Monte Carlo band later samples. For each product x region segment it computes:
  - logo renewal rate (a proportion) + a Wilson interval
  - gross revenue retention (a revenue-weighted ratio) + a bootstrap CI
A segment thinner than N_MIN events falls back to its product-level pool, so a sparse
backtest window still gets a stable rate (noisy small-sample rates would wreck the band).

Reuses the audit's event reconstruction so there is one definition of a renewal.
"""

from __future__ import annotations

import math
from datetime import date

import numpy as np
import pandas as pd

from etl.metrics.audit_renewals import _load_recurring, reconstruct

WINDOW_BEFORE, WINDOW_AFTER = 30, 60      # renewal window (days), from the audit
MATURATION_LAG = 60                       # only score events old enough to have resolved
N_MIN = 30                                # below this, pool to the product level
N_BOOT = 2000


def matured_events(as_of=None) -> pd.DataFrame:
    """Expiry events old enough to have resolved as of `as_of` (censoring control)."""
    as_of = pd.Timestamp(as_of or date.today()).normalize()
    ev = reconstruct(_load_recurring(), win_before=WINDOW_BEFORE, win_after=WINDOW_AFTER)
    return ev[ev["eff_end"] < as_of - pd.Timedelta(days=MATURATION_LAG)].copy()


def _grr(ev: pd.DataFrame) -> float:
    s = ev["pred_arr"].sum()
    return float(ev["retained_arr"].sum() / s) if s else float("nan")


def _boot_grr(ev: pd.DataFrame, rng: np.random.Generator, b: int = N_BOOT) -> np.ndarray:
    """Bootstrap the revenue-weighted GRR by resampling events with replacement."""
    pred = ev["pred_arr"].to_numpy()
    ret = ev["retained_arr"].to_numpy()
    n = len(pred)
    if n == 0:
        return np.array([])
    idx = rng.integers(0, n, size=(b, n))
    return ret[idx].sum(axis=1) / pred[idx].sum(axis=1)


def _wilson(k: int, n: int, z: float = 1.645) -> tuple[float, float]:
    """Wilson score interval for a proportion (z=1.645 -> 90%)."""
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def estimate(as_of=None, n_min: int = N_MIN, seed: int = 0) -> pd.DataFrame:
    ev = matured_events(as_of)
    rng = np.random.default_rng(seed)

    rows = []
    for (prod, region), g in ev.groupby(["product", "region"]):
        n, k = len(g), int(g["renewed"].sum())
        if n >= n_min:
            src, method = g, "direct"
        else:
            src, method = ev[ev["product"] == prod], "pooled-product"
        boot = _boot_grr(src, rng)
        lo, hi = (np.percentile(boot, [5, 95]) if boot.size else (np.nan, np.nan))
        wl, wh = _wilson(k, n)
        rows.append({
            "product": prod, "region": region, "n": n, "renewed": k,
            "logo_rate": k / n if n else np.nan, "logo_lo": wl, "logo_hi": wh,
            "grr": _grr(src), "grr_lo": float(lo), "grr_hi": float(hi),
            "method": method,
        })

    total = ev
    boot = _boot_grr(total, rng)
    lo, hi = np.percentile(boot, [5, 95])
    rows.append({
        "product": "ALL", "region": "ALL", "n": len(total),
        "renewed": int(total["renewed"].sum()),
        "logo_rate": total["renewed"].mean(),
        "logo_lo": np.nan, "logo_hi": np.nan,
        "grr": _grr(total), "grr_lo": float(lo), "grr_hi": float(hi), "method": "direct",
    })
    return pd.DataFrame(rows)


def trend_by_year(as_of=None, seed: int = 0) -> pd.DataFrame:
    """GRR by product x expiry-year, with per-cell bootstrap band + n.

    Bucketed on the year a contract expired (the renewal-decision cohort). The
    per-cell band + n is the honesty check: if the yearly bands overlap heavily,
    an apparent 'trend' is noise; if they march down with little overlap, it's real.
    The most recent year is partly censored (fewer matured events) — watch n.
    """
    ev = matured_events(as_of).copy()
    ev["year"] = ev["eff_end"].dt.year
    rng = np.random.default_rng(seed)
    rows = []
    for (prod, yr), g in ev.groupby(["product", "year"]):
        boot = _boot_grr(g, rng)
        lo, hi = (np.percentile(boot, [5, 95]) if boot.size else (np.nan, np.nan))
        rows.append({
            "product": prod, "year": int(yr), "n": len(g),
            "grr_pct": round(_grr(g) * 100, 1),
            "band": f"{lo * 100:.0f}-{hi * 100:.0f}",
        })
    return pd.DataFrame(rows)


if __name__ == "__main__":
    est = estimate()
    show = est.copy()
    for c in ["logo_rate", "logo_lo", "logo_hi", "grr", "grr_lo", "grr_hi"]:
        show[c] = (show[c] * 100).round(1)
    print("Per-segment GRR with uncertainty (as of today, matured events):\n")
    print(show.to_string(index=False))
    print("\nRead: grr is the point estimate; [grr_lo, grr_hi] is the 90% bootstrap band")
    print("the MC will sample from. Note the band WIDENS as segment n shrinks.")
