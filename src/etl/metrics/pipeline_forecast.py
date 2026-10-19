"""Pipeline model, step 3 — Monte Carlo bookings forecast from open opportunities.

Each trial combines the three uncertainties the research prescribed:
  - WIN: draw each stage's win-rate p_k from a Beta(won+1, lost+1) posterior (this single
    draw gives BOTH parameter/epistemic uncertainty AND cross-deal correlation, since every
    open deal at stage k shares that trial's p_k), then flip each deal ~ Bernoulli(p_k).
  - TIMING: for each won deal, sample remaining days from the survival model conditional on
    its current age, and place its revenue in that close month.
  - AMOUNT: the opp's amount_usd (amount-distribution noise is a documented refinement).
Stacking N trials gives a per-month bookings distribution (P10/P50/P90), not a point.

Uses the calibrated stage win-rates (NOT the CRM field) and the censored survival timing.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from etl.load.db import get_engine
from etl.metrics.pipeline_backtest import debias_factor
from etl.metrics.pipeline_calibration import stage_win_rates
from etl.metrics.pipeline_timing import fit_by_product, sample_remaining

TODAY = pd.Timestamp(date.today()).normalize()
HORIZON_MONTHS = 6


def _open_deals() -> pd.DataFrame:
    df = pd.read_sql(
        "SELECT product, stage_rank, amount_usd, created_date "
        "FROM fact_opportunity WHERE status='open'", get_engine())
    df["created_date"] = pd.to_datetime(df["created_date"])
    df = df[df["stage_rank"].notna() & df["amount_usd"].notna() & df["created_date"].notna()]
    df["age"] = (TODAY - df["created_date"]).dt.days.clip(lower=0)
    return df.reset_index(drop=True)


def run_mc(n_trials: int = 5000, seed: int = 0) -> pd.DataFrame:
    deals = _open_deals()
    kms = fit_by_product()
    cal = stage_win_rates().set_index("rank")
    rng = np.random.default_rng(seed)

    # Beta posterior params per stage: won, lost (= resolved_reached - won).
    won = cal["won"].to_dict()
    lost = (cal["resolved_reached"] - cal["won"]).to_dict()

    months = np.arange(HORIZON_MONTHS + 1)          # 0 = this month .. HORIZON
    book = np.zeros((n_trials, len(months)))

    for prod, g in deals.groupby("product"):
        idx = g.index.to_numpy()
        ranks = g["stage_rank"].to_numpy(int)
        amt = g["amount_usd"].to_numpy(float)
        ages = g["age"].to_numpy(float)
        m = len(g)

        # (n_trials,) Beta draw per stage -> p per deal per trial (shared within stage = correlation)
        p = np.empty((n_trials, m))
        for k in (1, 2, 3, 4):
            col = ranks == k
            if col.any():
                p[:, col] = rng.beta(won[k] + 1, lost[k] + 1, size=n_trials)[:, None]
        win = rng.random((n_trials, m)) < p

        # remaining days (m, n_trials) conditional on age, -> close month index
        rem = np.vstack([sample_remaining(kms[prod], ages[j], n_trials, rng) for j in range(m)])
        close = TODAY.to_numpy() + rem.astype("timedelta64[D]")
        cm = ((close.astype("datetime64[M]") - np.datetime64(TODAY, "M")) / np.timedelta64(1, "M")).astype(int).T

        for mo in months:                            # scatter won revenue into its close month
            hit = win & (cm == mo)
            book[:, mo] += (hit * amt[None, :]).sum(axis=1)

    book *= debias_factor()      # backtest-measured correction (~0.912), removes over-forecast

    p10, p50, p90 = np.percentile(book, [10, 50, 90], axis=0)
    labels = [(TODAY + pd.DateOffset(months=int(mo))).strftime("%Y-%m") for mo in months]
    return pd.DataFrame({"month": labels, "p10": p10, "p50": p50, "p90": p90})


if __name__ == "__main__":
    f = run_mc()
    show = f.copy()
    for c in ("p10", "p50", "p90"):
        show[c] = (show[c] / 1000).round(0).astype(int)
    print(f"Pipeline bookings forecast — next {HORIZON_MONTHS} months ($k), from "
          f"{len(_open_deals())} open deals:\n")
    print(show.to_string(index=False))
    print(f"\ntotal expected (P50) over horizon: ${f['p50'].sum():,.0f}  "
          f"[P10 ${f['p10'].sum():,.0f} .. P90 ${f['p90'].sum():,.0f}]")
