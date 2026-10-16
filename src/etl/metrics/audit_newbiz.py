"""Step 0 for the new-business layer — audit net-new bookings. READ-ONLY.

New business = bookings that are NOT renewals (renewals are already in the GRR layer).
Classification:
  - recurring (A maintenance, B subs): a RENEWAL if the same company+product has an
    earlier contract ending near this one's start (the same [-30,+60]d window as GRR);
    otherwise NEW.
  - one-time (A perpetual, C orders): always NEW (fresh purchases).

Then: how much net-new per quarter, is it growing/flat/declining, is there seasonality,
and can the data support a forecast at all. Measure before we assume.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from etl.load.db import get_engine
from etl.metrics.retention import WINDOW_AFTER, WINDOW_BEFORE

SQL = """
    SELECT product, revenue_type, is_renewal, company_id,
           booking_date, start_date, end_date, cancel_date, booking_value_usd
    FROM fact_contracts
"""


def _load() -> pd.DataFrame:
    df = pd.read_sql(SQL, get_engine())
    for c in ("booking_date", "start_date", "end_date", "cancel_date"):
        df[c] = pd.to_datetime(df[c])
    df["eff_end"] = df["end_date"].where(df["cancel_date"].isna(),
                                         df[["end_date", "cancel_date"]].min(axis=1))
    return df


def classify_new(df: pd.DataFrame) -> pd.DataFrame:
    """Add is_new. B uses its source is_renewal flag (truth); A recurring uses the
    chain heuristic (no flag); one-time (A perpetual, C) is always new."""
    df = df.copy()
    df["is_new"] = True
    # B: renewal iff source flag says so.
    b = df["product"] == "B"
    df.loc[b, "is_new"] = ~df.loc[b, "is_renewal"].fillna(False).astype(bool)
    # A recurring (maintenance): chain continuation = renewal.
    rec_a = df[(df["revenue_type"] == "recurring") & (df["product"] == "A")]
    renewal_idx = []
    for _, g in rec_a.groupby("company_id"):
        g = g.sort_values("start_date")
        starts = g["start_date"].to_numpy("datetime64[D]")
        ends = g["eff_end"].to_numpy("datetime64[D]")
        idx = g.index.to_numpy()
        for i in range(len(g)):
            for j in range(len(g)):
                if j == i or starts[j] >= starts[i]:
                    continue
                gap = int((starts[i] - ends[j]).astype(int))
                if -WINDOW_BEFORE <= gap <= WINDOW_AFTER:
                    renewal_idx.append(idx[i])
                    break
    df.loc[renewal_idx, "is_new"] = False
    return df


def audit() -> None:
    df = classify_new(_load())
    new = df[df["is_new"]]

    print(f"=== NEW-BUSINESS UNIVERSE: {len(new):,} of {len(df):,} bookings "
          f"(${new['booking_value_usd'].sum():,.0f}) ===\n")

    print("new bookings by product x type:")
    piv = (new.groupby(["product", "revenue_type"])
              .agg(n=("booking_value_usd", "size"), value=("booking_value_usd", "sum")))
    piv["value"] = piv["value"].round(0).astype(int)
    print(piv.to_string(), "\n")

    print("booking_date coverage:",
          df["booking_date"].min().date(), "->", df["booking_date"].max().date(), "\n")

    new = new.copy()
    new["q"] = new["booking_date"].dt.to_period("Q")
    byq = new.groupby("q")["booking_value_usd"].agg(["size", "sum"])
    byq.columns = ["n", "value"]
    print("=== NEW BOOKINGS PER QUARTER (value $, count) ===")
    show = byq.copy()
    show["value"] = (show["value"] / 1000).round(0).astype(int)
    show.columns = ["n", "value_$k"]
    print(show.to_string(), "\n")

    # Trend: compare first half vs second half of complete quarters (drop last, partial).
    full = byq.iloc[:-1]
    half = len(full) // 2
    early, late = full["value"].iloc[:half].mean(), full["value"].iloc[half:].mean()
    yrs = (len(full) / 4)
    cagr = ((full["value"].iloc[-1] / full["value"].iloc[0]) ** (1 / max(yrs, 1)) - 1) * 100
    print("=== TREND ===")
    print(f"avg new $/qtr  first half: ${early:,.0f}   second half: ${late:,.0f}   "
          f"({'up' if late > early else 'down'} {abs(late/early-1)*100:.0f}%)")
    print(f"rough CAGR (first vs last full qtr): {cagr:+.1f}%/yr   "
          f"(last quarter dropped as partial)\n")

    print("=== SEASONALITY — avg new $ by calendar quarter ===")
    new["qoy"] = new["booking_date"].dt.quarter
    seas = new.groupby("qoy")["booking_value_usd"].mean()
    seas = (seas / seas.mean() * 100).round(0).astype(int)
    print("index vs avg (100 = average):")
    print(seas.rename(index={1: "Q1", 2: "Q2", 3: "Q3", 4: "Q4"}).to_string(), "\n")

    print("=== VALIDATION — B is_new vs source ~is_renewal ===")
    b = df[df["product"] == "B"]
    agree = (b["is_new"] == ~b["is_renewal"].fillna(False).astype(bool)).mean()
    print(f"agreement: {agree:.1%}")


if __name__ == "__main__":
    audit()
