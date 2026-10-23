"""Emit dashboard metrics as JSON for the portfolio web app.

Reuses the ``*_data`` compute functions (single source of truth with the PNG charts) and
writes one JSON file per metric to ``data/processed/``. If the portfolio backend's data
directory exists, the files are copied there too so the Flask app can serve them.

Run:  PYTHONPATH=src python -m etl.metrics.emit
"""

from __future__ import annotations

import json
import math
import shutil
from datetime import date
from pathlib import Path

import pandas as pd

from etl.metrics import dashboard as dash
from etl.metrics.arr_bridge import arr_bridge

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "data" / "processed"
PORTFOLIO_DATA = Path.home() / "Desktop" / "portfolio" / "backend" / "data"


def _clean(obj):
    """Recursively replace NaN/inf with None so the output is valid JSON."""
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean(v) for v in obj]
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    return obj


def _bridge_payload() -> dict:
    t1 = pd.Timestamp(date.today()).normalize()
    t0 = t1 - pd.DateOffset(years=1)
    b = arr_bridge(t0, t1)
    start = b["start"] or 1.0
    return {
        "t0": b["t0"].isoformat(), "t1": b["t1"].isoformat(),
        "start": b["start"], "new": b["new"], "expansion": b["expansion"],
        "contraction": b["contraction"], "churn": b["churn"], "end": b["end"],
        "residual": b["residual"],
        "grr_pct": (b["start"] - b["churn"] - b["contraction"]) / start * 100,
        "nrr_pct": (b["start"] - b["churn"] - b["contraction"] + b["expansion"]) / start * 100,
    }


def build() -> dict[str, dict]:
    rec = dash._rec()
    return {
        "retention": {"as_of": date.today().isoformat(),
                      "quarters": dash.retention_trend_data(rec)},
        "concentration": dash.concentration_data(rec),
        "logos": {"quarters": dash.logos_data(rec)},
        "cohort": dash.cohort_retention_data(rec),
        "revenue_mix": dash.revenue_mix_data(rec),
        "bookings": {"quarters": dash.bookings_winrate_data()},
        "arr_bridge": _bridge_payload(),
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    payloads = build()
    for name, payload in payloads.items():
        text = json.dumps(_clean(payload), indent=2)
        (OUT / f"{name}.json").write_text(text)
        if PORTFOLIO_DATA.is_dir():
            (PORTFOLIO_DATA / f"{name}.json").write_text(text)
    # keep the already-emitted projection series in sync with the backend too
    proj = OUT / "projection_series.json"
    if proj.exists() and PORTFOLIO_DATA.is_dir():
        shutil.copyfile(proj, PORTFOLIO_DATA / "projection.json")
    dest = "data/processed/" + (f" and {PORTFOLIO_DATA}" if PORTFOLIO_DATA.is_dir() else "")
    print(f"wrote {len(payloads)} metric JSONs to {dest}")


if __name__ == "__main__":
    main()
