"""New-business forecast — the third (top, most speculative) stack layer.

New bookings have no maturation lag (a sale is observable at once), so we get many
backtest windows. We predict next quarter's net-new bookings one of two ways and let
the walk-forward decide which is safe to ship:
  - FLAT:   trailing-year average (ignore the trend)
  - DAMPED: flat nudged part-way toward the fitted trend (DAMP of the way)
Full TREND is reported too, as the "undamped" reference we are wary of (Taleb).

If DAMPED does not beat FLAT out of sample, we keep FLAT — adding a trend we can't
justify would be risk, not insight.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from etl.metrics.audit_newbiz import _load, classify_new

MIN_TRAIN_Q = 8      # need 2y before the first forecast
TREND_WINDOW_Q = 8   # fit the trend on the last 2y
DAMP = 0.5           # damped = flat + DAMP*(trend - flat)


def quarterly_new() -> pd.Series:
    """Net-new bookings $ per full quarter (partial final quarter dropped)."""
    df = classify_new(_load())
    new = df[df["is_new"]].copy()
    new["q"] = new["booking_date"].dt.to_period("Q")
    s = new.groupby("q")["booking_value_usd"].sum()
    max_book = new["booking_date"].max()
    return s[[p.end_time <= max_book for p in s.index]]


def _forecasts(train: pd.Series) -> dict:
    flat = train.iloc[-4:].mean()
    tw = train.iloc[-TREND_WINDOW_Q:]
    b1, b0 = np.polyfit(np.arange(len(tw)), tw.to_numpy(), 1)
    trend = b0 + b1 * len(tw)                      # one step past the window
    return {"flat": flat, "trend": trend, "damped": flat + DAMP * (trend - flat)}


def walk_forward(series: pd.Series | None = None) -> pd.DataFrame:
    s = series if series is not None else quarterly_new()
    rows = []
    for i in range(MIN_TRAIN_Q, len(s)):
        f = _forecasts(s.iloc[:i])
        rows.append({"q": str(s.index[i]), "actual": float(s.iloc[i]), **f})
    return pd.DataFrame(rows)


def forward_quarterly(n_q: int, scheme: str = "damped") -> np.ndarray:
    """Project the next n_q quarters of net-new bookings ($) under the chosen scheme.

    DAMPED takes half the fitted trend's deviation from the flat level at every horizon
    (linear, not exponential — bounded growth). FLAT freezes the trailing-year level.
    """
    s = quarterly_new()
    flat0 = s.iloc[-4:].mean()
    if scheme == "flat":
        return np.full(n_q, flat0)
    tw = s.iloc[-TREND_WINDOW_Q:]
    b1, b0 = np.polyfit(np.arange(len(tw)), tw.to_numpy(), 1)
    n = len(tw)
    return np.array([flat0 + DAMP * ((b0 + b1 * (n - 1 + q)) - flat0) for q in range(1, n_q + 1)])


def forward_new_weekly(n_weeks: int, scheme: str = "damped"):
    """Per-week new-business recognized $ (quarterly forecast / 13), + the week->quarter map.

    Simplification: at a steady booking run-rate, recognized ≈ booked per week (one-time
    recognized at sale; new-recurring's over-term spread smooths into the run-rate). Added
    precision would be false given the layer's ~18% inherent uncertainty.
    """
    n_q = n_weeks // 13 + 1
    q = forward_quarterly(n_q, scheme)
    wk_q = np.minimum(np.arange(n_weeks) // 13, n_q - 1)
    return q[wk_q] / 13.0, wk_q, n_q


def trend_sigma() -> float:
    """Data-derived annual-growth uncertainty = how much the trend estimate disagrees
    across reasonable trailing windows. This is NOT a guess about the future — it's the
    spread of what the history itself implies (±2% to +24%/yr), which the band must span.
    """
    s = quarterly_new()
    gs = []
    for w in (6, 8, 10, 12, 16, 20):
        if len(s) >= w:
            x = s.iloc[-w:]
            b1, _ = np.polyfit(np.arange(w), x.to_numpy(), 1)
            gs.append(b1 * 4 / x.mean())          # annualized growth fraction
    return float(np.std(gs))


def newbiz_errors(scheme: str = "damped") -> np.ndarray:
    """Realized one-quarter-ahead relative errors — the per-quarter dispersion the band samples."""
    bt = walk_forward()
    return ((bt["actual"] - bt[scheme]) / bt[scheme]).to_numpy()


def _score(df: pd.DataFrame, col: str) -> dict:
    err = df[col] - df["actual"]
    return {"bias_$k": round(err.mean() / 1000),
            "MAE_$k": round(err.abs().mean() / 1000),
            "MAPE_%": round((err.abs() / df["actual"]).mean() * 100, 1)}


if __name__ == "__main__":
    s = quarterly_new()
    print(f"Quarterly net-new bookings: {len(s)} full quarters "
          f"({s.index[0]}..{s.index[-1]}), recent run-rate ${s.iloc[-4:].mean():,.0f}/qtr\n")

    bt = walk_forward(s)
    print(f"Walk-forward: {len(bt)} one-quarter-ahead forecasts\n")
    print("scheme comparison (lower = better):")
    rows = []
    for col in ("flat", "damped", "trend"):
        rows.append({"scheme": col, **_score(bt, col)})
    print(pd.DataFrame(rows).to_string(index=False))

    print("\n--- per-window (actual vs flat vs damped), $k ---")
    show = bt.copy()
    for c in ("actual", "flat", "damped", "trend"):
        show[c] = (show[c] / 1000).round(0).astype(int)
    print(show[["q", "actual", "flat", "damped", "trend"]].to_string(index=False))
