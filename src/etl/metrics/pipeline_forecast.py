"""Pipeline model, step 3 — Monte Carlo bookings forecast from open opportunities.

Each trial: WIN ~ Beta(won+1,lost+1) per stage (parameter uncertainty + cross-deal
correlation) x Bernoulli; TIMING ~ the STAGE-aware survival curve for the deal's current
stage, conditional on how long it has sat there (so early-stage deals close later);
AMOUNT = the opp's amount. Stacking N trials gives a per-period bookings distribution.

Calibrated stage win-rates (not the CRM field), stage-aware timing, and the backtest
debias are all applied. Bucketed monthly (the grain we forecast/backtest at).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from etl.metrics.pipeline_backtest import debias_factor
from etl.metrics.pipeline_calibration import stage_win_rates
from etl.metrics.pipeline_timing import (
    TODAY, fit_stage_kms, km_for, load_opp_hist, open_deals_asof, sample_remaining)

HORIZON_MONTHS = 6


def _monthly_samples(n_trials: int, seed: int) -> np.ndarray:
    opp, hist = load_opp_hist()
    deals = open_deals_asof(opp, hist, TODAY)
    stage_kms, prod_kms = fit_stage_kms(opp, hist, TODAY)
    cal = stage_win_rates().set_index("rank")
    won, lost = cal["won"].to_dict(), (cal["resolved_reached"] - cal["won"]).to_dict()
    rng = np.random.default_rng(seed)

    p_rank = {k: rng.beta(won[k] + 1, lost[k] + 1, size=n_trials) for k in (1, 2, 3, 4)}
    monthly = np.zeros((n_trials, HORIZON_MONTHS + 1))
    for (prod, rank), g in deals.groupby(["product", "rank"]):
        km = km_for(stage_kms, prod_kms, prod, rank)
        if km is None:
            continue
        amt, ages, m = g["amount_usd"].to_numpy(), g["age_in_stage"].to_numpy(), len(g)
        win = rng.random((n_trials, m)) < p_rank[rank][:, None]
        rem = np.vstack([sample_remaining(km, ages[j], n_trials, rng) for j in range(m)]).T
        close = TODAY.to_numpy() + rem.astype("timedelta64[D]")
        cm = ((close.astype("datetime64[M]") - np.datetime64(TODAY, "M")) / np.timedelta64(1, "M")).astype(int)
        for mo in range(HORIZON_MONTHS + 1):
            monthly[:, mo] += ((win & (cm == mo)) * amt[None, :]).sum(axis=1)
    return monthly * debias_factor()


def run_mc(n_trials: int = 5000, seed: int = 0) -> pd.DataFrame:
    monthly = _monthly_samples(n_trials, seed)
    p10, p50, p90 = np.percentile(monthly, [10, 50, 90], axis=0)
    labels = [(TODAY + pd.DateOffset(months=mo)).strftime("%Y-%m") for mo in range(HORIZON_MONTHS + 1)]
    return pd.DataFrame({"month": labels, "p10": p10, "p50": p50, "p90": p90})


def weekly_booking_samples(n_weeks: int = 156, n_trials: int = 2000, seed: int = 0) -> np.ndarray:
    """(n_trials, n_weeks) debiased pipeline bookings as a smooth weekly RATE (monthly /4.35,
    so a partial current month doesn't spike) — for blending into the stack."""
    monthly = _monthly_samples(n_trials, seed)
    wk_month = np.array([((TODAY + pd.Timedelta(weeks=int(w))).year - TODAY.year) * 12
                         + ((TODAY + pd.Timedelta(weeks=int(w))).month - TODAY.month) for w in range(n_weeks)])
    weeks_per_month = 365.25 / 12 / 7
    out = np.zeros((n_trials, n_weeks))
    for mo in range(HORIZON_MONTHS + 1):
        wks = np.where(wk_month == mo)[0]
        if len(wks):
            out[:, wks] = (monthly[:, mo] / weeks_per_month)[:, None]
    return out


def pipeline_anomaly(hist_start="2024-01-01", hist_end="2025-12-01") -> dict:
    """Flag when the current open pipeline is far outside the range the model was backtested
    on. The near-term forecast scales with pipeline size, so an abnormally large pipeline
    means the near term is extrapolating beyond validated conditions — warn, don't hide it."""
    opp, hist = load_opp_hist()
    counts = [len(open_deals_asof(opp, hist, d))
              for d in pd.date_range(hist_start, hist_end, freq="MS")]
    now = len(open_deals_asof(opp, hist, TODAY))
    cmed, cmax, cp90 = np.median(counts), max(counts), np.percentile(counts, 90)
    level = "ANOMALY" if now > cmax else ("ELEVATED" if now > cp90 else "NORMAL")
    return {"level": level, "now": now, "median": int(cmed), "max": cmax,
            "ratio": now / cmed}


def leadtime_weight(n_weeks: int = 156) -> np.ndarray:
    """Blend weight w(week) = P(won-deal lead time >= week) = fraction of that week's
    bookings already 'born' in the pipeline. Data-derived handoff to run-rate."""
    opp, _ = load_opp_hist()
    w = opp[opp["status"] == "won"]
    lead = (w["close_date"] - w["created_date"]).dt.days
    lead = lead[lead >= 0].to_numpy()
    days = np.arange(n_weeks) * 7
    return np.array([(lead >= d).mean() for d in days])


if __name__ == "__main__":
    f = run_mc()
    show = f.copy()
    for c in ("p10", "p50", "p90"):
        show[c] = (show[c] / 1000).round(0).astype(int)
    print("Pipeline bookings forecast — next 6 months ($k), stage-aware timing:\n")
    print(show.to_string(index=False))
    print(f"\ntotal P50 over horizon: ${f['p50'].sum():,.0f}  [P10 ${f['p10'].sum():,.0f} .. P90 ${f['p90'].sum():,.0f}]")
