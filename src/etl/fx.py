"""Historical FX reference table, cached locally for reproducibility.

Foreign-currency amounts are converted at the rate on their BOOKING date.
Rates are pulled once from yfinance and cached to data/reference/fx_rates.csv,
so the pipeline is deterministic and does not depend on a live API every run.

Market-closed days (weekends/holidays) have no quote, so we forward-fill from
the prior trading day, then back-fill any leading gap. Stored values are
USD per 1 unit of the currency (USD = 1.0).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

FX_PATH = Path(__file__).resolve().parents[2] / "data" / "reference" / "fx_rates.csv"

# yfinance tickers: "XXXUSD=X" = USD per 1 unit of XXX.
TICKERS = {"GBP": "GBPUSD=X", "EUR": "EURUSD=X"}


def build_fx_cache(start: str = "2021-10-01", end: str = "2026-10-02") -> pd.DataFrame:
    """Fetch daily GBP/EUR→USD rates once and cache them. Returns the table."""
    import yfinance as yf

    raw = yf.download(
        list(TICKERS.values()),
        start=start,
        end=end,
        interval="1d",
        progress=False,
        auto_adjust=False,
    )["Close"].rename(columns={v: k for k, v in TICKERS.items()})

    calendar = pd.date_range(start=start, end=end, freq="D")
    filled = raw.reindex(calendar).ffill().bfill()
    filled["USD"] = 1.0
    filled.index.name = "date"

    FX_PATH.parent.mkdir(parents=True, exist_ok=True)
    filled.to_csv(FX_PATH)

    n_quoted = raw.dropna(how="all").shape[0]
    print(f"FX: {n_quoted} quoted trading days -> {len(filled)} daily rows "
          f"({len(filled) - n_quoted} filled). Saved to {FX_PATH}")
    return filled


def load_fx_rates() -> pd.DataFrame:
    """Load the cached FX table (date-indexed, columns GBP/EUR/USD)."""
    return pd.read_csv(FX_PATH, parse_dates=["date"], index_col="date")


def to_usd(amount: pd.Series, currency: pd.Series, date: pd.Series) -> pd.Series:
    """Convert amounts to USD using the rate on each row's date."""
    rates = load_fx_rates()
    day = pd.to_datetime(date).dt.normalize()
    multiplier = pd.Series(index=amount.index, dtype="float64")
    for cur in currency.unique():
        mask = currency == cur
        if cur not in rates.columns:
            raise ValueError(f"No FX rate column for currency {cur!r}")
        multiplier.loc[mask] = rates.loc[day[mask], cur].to_numpy()
    return amount.astype(float) * multiplier


if __name__ == "__main__":
    build_fx_cache()
