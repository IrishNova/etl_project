"""Reconciliation helpers — prove a transform changed only what we intended.

The job of these functions is to let us compare a source BEFORE and AFTER
transform and account for every difference. If a total moves and we can't
explain it, that's a bug caught.
"""

from __future__ import annotations

import pandas as pd


def profile(
    df: pd.DataFrame,
    *,
    value_cols: tuple[str, ...] = (),
    key_col: str | None = None,
) -> dict[str, float | int]:
    """Simple comparable stats for a DataFrame.

    value_cols are summed (coerced to numeric); key_col is counted distinct.
    """
    stats: dict[str, float | int] = {"rows": len(df)}
    for col in value_cols:
        stats[f"sum_{col}"] = float(pd.to_numeric(df[col], errors="coerce").sum())
    if key_col is not None:
        stats[f"nunique_{key_col}"] = int(df[key_col].nunique())
    return stats


def compare(before: dict, after: dict, label: str = "") -> None:
    """Print a before/after table of two profile() dicts."""
    header = f" RECONCILIATION {label} ".center(60, "=")
    print(header)
    print(f"{'metric':<28}{'before':>15}{'after':>15}")
    print("-" * 58)
    keys = list(dict.fromkeys([*before, *after]))
    for k in keys:
        b = before.get(k, "-")
        a = after.get(k, "-")
        b_s = f"{b:,.2f}" if isinstance(b, float) else f"{b:,}" if isinstance(b, int) else str(b)
        a_s = f"{a:,.2f}" if isinstance(a, float) else f"{a:,}" if isinstance(a, int) else str(a)
        print(f"{k:<28}{b_s:>15}{a_s:>15}")
    print("=" * 58)
