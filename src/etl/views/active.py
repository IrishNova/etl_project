"""Level 4 — View helper: is a contract live as of a given date?

`is_active` is NOT a stored fact — it depends on the date you ask about. The
unified table stores only the immutable coverage window (start_date, end_date,
cancel_date) and revenue_type. This helper derives, for ANY as-of date, whether
each contract is live and what its status is on that date.

Rule (recurring contracts only):
    as_of < start_date ............................... future   (is_active False)
    cancel_date <= as_of ............................. cancelled(is_active False)
    start_date <= as_of <= end_date .................. active   (is_active True)
    as_of > end_date ................................. expired  (is_active False)

One-time / perpetual rows have no coverage window, so "active" does not apply:
    status = "n/a", is_active = <NA>.

Validation anchor: Product B's source ships its own Active/Expired/Cancelled
label as of their 2026-09-30 snapshot. Running this helper at that date must
reproduce B's labels exactly — see validate_against_b().
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Product B's vendor status snapshot (reverse-engineered: Expired ends on/before
# 2026-09-29, Active ends on/after 2026-10-01, clean gap -> snapshot = 2026-09-30).
B_SNAPSHOT = pd.Timestamp("2026-09-30")


def active_as_of(df: pd.DataFrame, as_of) -> pd.DataFrame:
    """Return a frame (indexed like df) with `status_asof` and `is_active`.

    `is_active` is a nullable boolean: True/False for recurring rows, <NA> for
    non-recurring rows (where the concept doesn't apply).
    """
    as_of = pd.Timestamp(as_of)
    start = pd.to_datetime(df["start_date"])
    end = pd.to_datetime(df["end_date"])
    cancel = pd.to_datetime(df["cancel_date"])
    recurring = df["revenue_type"] == "recurring"

    status = pd.Series("n/a", index=df.index, dtype="object")

    # Evaluate only recurring rows; order matters (cancel beats window).
    future = recurring & (as_of < start)
    cancelled = recurring & cancel.notna() & (cancel <= as_of)
    expired = recurring & (as_of > end)
    active = recurring & (start <= as_of) & (as_of <= end)

    # Precedence: future -> cancelled -> expired -> active (last write wins, so
    # assign in reverse precedence).
    status[active] = "active"
    status[expired] = "expired"
    status[cancelled] = "cancelled"
    status[future] = "future"

    is_active = pd.Series(pd.NA, index=df.index, dtype="boolean")
    is_active[recurring] = status[recurring] == "active"

    return pd.DataFrame({"status_asof": status, "is_active": is_active})


def validate_against_b(clean_b: pd.DataFrame, as_of=B_SNAPSHOT) -> None:
    """Prove the rule reproduces Product B's own status labels at its snapshot.

    B's source `status` (active/expired/cancelled) is the vendor's ground truth.
    If our date logic is right, active_as_of(B, 2026-09-30) matches it row-for-row.
    """
    derived = active_as_of(clean_b, as_of)["status_asof"]
    truth = clean_b["status"]

    match = derived == truth
    n_mismatch = int((~match).sum())

    print(f"===== validate_against_b (as_of={pd.Timestamp(as_of).date()}) =====")
    print("vendor label vs derived status:")
    xtab = pd.crosstab(truth, derived)
    print(xtab.to_string())
    print(f"\nrows: {len(clean_b):,}   matched: {int(match.sum()):,}   mismatched: {n_mismatch}")

    if n_mismatch:
        print("\n--- mismatches ---")
        cols = ["contract_id", "start_date", "end_date", "cancel_date", "status"]
        bad = clean_b.loc[~match, cols].copy()
        bad["derived"] = derived[~match]
        print(bad.head(20).to_string(index=False))
        raise SystemExit(f"Validation FAILED — {n_mismatch} rows disagree with B's labels.")
    print("\nRule reproduces B's labels exactly. ✅")


if __name__ == "__main__":
    from pathlib import Path

    processed = Path(__file__).resolve().parents[3] / "data" / "processed"
    b = pd.read_csv(processed / "clean_product_b.csv")
    validate_against_b(b)
