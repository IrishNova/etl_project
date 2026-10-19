"""Level 1 — Extract: sales pipeline (CRM opportunities + stage-change history).

Two source files, loaded as raw all-text so Transform owns every parsing decision
(keep_default_na=False so blanks stay "" and nothing is silently coerced):
  - pipeline_opportunities.csv : one row per opportunity, from TWO CRMs (HS-ACQ, SF-LEG)
    with different stage vocabularies, product spellings, date/amount/probability formats.
  - pipeline_stage_history.csv : stage-change event log (opportunity_id, from/to, timestamp)
    — the basis for point-in-time ("as of date T") reconstruction in backtesting.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parents[3] / "_data"
OPPORTUNITIES_PATH = DATA_DIR / "pipeline_opportunities.csv"
STAGE_HISTORY_PATH = DATA_DIR / "pipeline_stage_history.csv"

_AS_TEXT = dict(dtype=str, keep_default_na=False, na_values=[])


def load_opportunities() -> pd.DataFrame:
    return pd.read_csv(OPPORTUNITIES_PATH, **_AS_TEXT)


def load_stage_history() -> pd.DataFrame:
    return pd.read_csv(STAGE_HISTORY_PATH, **_AS_TEXT)


if __name__ == "__main__":
    opps = load_opportunities()
    hist = load_stage_history()
    print(f"opportunities: {len(opps):,} rows x {opps.shape[1]} cols  ({OPPORTUNITIES_PATH.name})")
    print(f"stage history: {len(hist):,} rows x {hist.shape[1]} cols  ({STAGE_HISTORY_PATH.name})")
    print("\nopportunity crm_source split:", opps["crm_source"].value_counts().to_dict())
