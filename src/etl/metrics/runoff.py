"""Metrics (L4) — the GUARANTEED weekly revenue runoff (the bottom of the stack).

Business question: of the revenue we have ALREADY sold and have under contract, how
much do we recognize in each future week — and how does it melt away as contracts
expire? This is the certain floor of the planning chart; the expected/projected band
(renewals beyond expiry) is layered on later (Phase 3).

Definition (recurring contracts only):
  - A contract recognizes arr_usd / 365.25 per DAY it is live (straight-line, ASC 606).
  - Live = [start_date, end_date], ended early by cancel_date, and clipped to today
    forward (past days are already earned, not "future cashflow").
  - Guaranteed revenue in week W = sum over contracts of daily_rate * (active days in W).
  - Day-level overlap handles partial first/last weeks exactly.

Reconciliation: the weekly buckets must sum to each contract's remaining value computed
directly (daily_rate * remaining days). If they don't, the bucketing is wrong.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
from sqlalchemy import Engine, select

from etl.load.db import get_engine
from etl.load.tables import fact_contracts

DAYS_PER_YEAR = 365.25


def _load_recurring(engine: Engine) -> pd.DataFrame:
    sel = select(
        fact_contracts.c.arr_usd,
        fact_contracts.c.start_date,
        fact_contracts.c.end_date,
        fact_contracts.c.cancel_date,
    ).where(fact_contracts.c.revenue_type == "recurring")
    with engine.connect() as conn:
        df = pd.DataFrame(conn.execute(sel).mappings().all())
    for c in ("start_date", "end_date", "cancel_date"):
        df[c] = pd.to_datetime(df[c])
    df["arr_usd"] = df["arr_usd"].astype(float)
    return df


def weekly_runoff(engine: Engine | None = None, as_of=None) -> pd.DataFrame:
    """Per-week guaranteed revenue + active-license count, from today forward."""
    engine = engine or get_engine()
    as_of = pd.Timestamp(as_of or date.today()).normalize()

    df = _load_recurring(engine)

    # Effective live interval: end is the earlier of end_date / cancel_date; start is
    # clipped to today (we only project future cashflow).
    eff_end = df["end_date"].where(df["cancel_date"].isna(),
                                   df[["end_date", "cancel_date"]].min(axis=1))
    eff_start = df["start_date"].clip(lower=as_of)
    daily = df["arr_usd"] / DAYS_PER_YEAR

    live = eff_end >= eff_start                      # drop already-expired contracts
    es = eff_start[live].to_numpy("datetime64[D]")
    ee = eff_end[live].to_numpy("datetime64[D]")
    dv = daily[live].to_numpy()

    # Weekly grid: Monday of the current week, out to the last expiry.
    week0 = as_of - pd.Timedelta(days=as_of.weekday())
    weeks = pd.date_range(week0, eff_end[live].max(), freq="7D")

    rows = []
    for w in weeks:
        ws = np.datetime64(w.date(), "D")
        we = ws + np.timedelta64(6, "D")
        lo = np.maximum(es, ws)
        hi = np.minimum(ee, we)
        days = np.maximum((hi - lo).astype(int) + 1, 0)   # inclusive overlap, floored at 0
        rows.append({
            "week_start": w.date(),
            "active_licenses": int((days > 0).sum()),
            # Full precision kept; callers round only for display. Rounding each
            # bucket here then summing would drift (see reconcile()).
            "guaranteed_usd": float((dv * days).sum()),
        })
    return pd.DataFrame(rows)


def reconcile(engine: Engine | None = None, as_of=None) -> None:
    """Prove the weekly buckets sum to the remaining contracted value, exactly."""
    engine = engine or get_engine()
    as_of = pd.Timestamp(as_of or date.today()).normalize()

    df = _load_recurring(engine)
    eff_end = df["end_date"].where(df["cancel_date"].isna(),
                                   df[["end_date", "cancel_date"]].min(axis=1))
    eff_start = df["start_date"].clip(lower=as_of)
    daily = df["arr_usd"] / DAYS_PER_YEAR
    rem_days = np.maximum((eff_end - eff_start).dt.days.to_numpy() + 1, 0)
    direct_total = float((daily.to_numpy() * rem_days).sum())

    grid_total = float(weekly_runoff(engine, as_of)["guaranteed_usd"].sum())

    # Same number, different summation order -> compare within a floating tolerance,
    # not for exact equality.
    ok = bool(np.isclose(direct_total, grid_total, rtol=0, atol=0.01))
    print("===== RECONCILIATION — weekly buckets vs direct remaining value =====")
    print(f"sum of weekly buckets : ${grid_total:,.2f}")
    print(f"direct per-contract   : ${direct_total:,.2f}")
    print(f"difference            : ${abs(direct_total - grid_total):.6f}")
    print(f"  [{'PASS' if ok else 'FAIL'}] buckets sum to the whole (within 1c)")
    if not ok:
        raise SystemExit("Runoff reconciliation FAILED — bucketing is wrong.")


if __name__ == "__main__":
    runoff = weekly_runoff()
    total = runoff["guaranteed_usd"].sum()
    print(f"Guaranteed (contracted) revenue still to recognize: ${total:,.2f}")
    print(f"Weeks in runoff: {len(runoff)}  "
          f"({runoff['week_start'].iloc[0]} -> {runoff['week_start'].iloc[-1]})\n")
    display = runoff.assign(guaranteed_usd=runoff["guaranteed_usd"].round(2))
    print("--- first 8 weeks ---")
    print(display.head(8).to_string(index=False))
    print("\n--- last 3 weeks (the tail / cliff) ---")
    print(display.tail(3).to_string(index=False))
    print()
    reconcile()
