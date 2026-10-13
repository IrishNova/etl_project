"""Level 2 — Transform: Product C (simulation orders).

Raw all-text frame from L1 (loaded header=None) -> unified schema.

C is the messiest to *read* but simplest to *model*:
  - junk rows: a 2-line preamble, blank spacers, and a `TOTAL` footer -> dropped
    by detecting the real header and keeping only `SO-` order rows
  - `Seats` is contaminated ("4 seats") -> stripped to int
  - all orders are one-time, USD; arr_usd = 0, revenue_type = one-time

Decision locked (see PROGRESS.md): C has no customer_name/region columns, so
those stay null here and are ENRICHED in L3 from A by Customer ID (same
C-100xx scheme). 11 C-only customers can't be named by id -> handled in L3.

Reconciliation anchor: the source's own `TOTAL` footer (9,158,875) must equal
SUM(booking_value_usd) over the clean rows.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from etl.extract.sources import PRODUCT_C_PATH, load_product_c
from etl.schema import conform
from etl.transform.validation import compare, profile

OUTPUT_DIR = Path(__file__).resolve().parents[3] / "data" / "processed"

HEADER_MARKER = "Order Ref"
FOOTER_MARKER = "TOTAL"


def _locate_header(raw: pd.DataFrame) -> int:
    """Find the row index of the real header (don't hardcode a skip count)."""
    hits = raw.index[raw[0].astype(str).str.strip() == HEADER_MARKER]
    if len(hits) != 1:
        raise ValueError(f"Expected exactly one header row, found {len(hits)}")
    return int(hits[0])


def _footer_total(raw: pd.DataFrame) -> float:
    """Read the source's TOTAL footer value (column index 5 = Order Total)."""
    row = raw[raw[0].astype(str).str.strip() == FOOTER_MARKER]
    return float(row.iloc[0, 5])


def _seats_to_int(s: pd.Series) -> pd.Series:
    """'4 seats' / '4' -> 4. Raise if anything isn't a plain seat count."""
    cleaned = s.astype(str).str.replace(r"\s*seats?\s*", "", regex=True).str.strip()
    if not cleaned.str.fullmatch(r"\d+").all():
        bad = sorted(s[~cleaned.str.fullmatch(r"\d+")].unique())
        raise ValueError(f"Unparseable seats values: {bad}")
    return cleaned.astype("int64")


def _impute_booking_dates(order_ref: pd.Series, date: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Fill blank order dates by interpolating against the order-ref sequence.

    Order refs run in rough date order (corr 0.98). Validated by leave-one-out:
    median error ~9 days (p90 ~20). Good enough for the quarter/year grain FP&A
    uses, not day-exact. Known dates are never changed; only blanks are filled
    and flagged via the returned boolean.
    """
    inferred = date.isna()
    if not inferred.any():
        return date, inferred

    ref = order_ref.str.replace("SO-", "", regex=False).astype(int).to_numpy(float)
    known = (~inferred).to_numpy()
    xk = ref[known]
    yk = date[known].map(lambda d: d.toordinal()).to_numpy(float)
    order = np.argsort(xk)
    est = np.interp(ref[inferred.to_numpy()], xk[order], yk[order])

    filled = date.copy()
    filled.loc[inferred] = [pd.Timestamp.fromordinal(int(round(o))) for o in est]
    return filled, inferred


def transform_product_c(raw: pd.DataFrame) -> pd.DataFrame:
    hdr = _locate_header(raw)
    df = raw.iloc[hdr + 1 :].copy()
    df.columns = raw.iloc[hdr].tolist()

    # Keep only real order rows -> drops blank spacers and the TOTAL footer.
    df = df[df["Order Ref"].astype(str).str.startswith("SO-")].copy()

    # --- CLEAN: types ---
    df["Seats"] = _seats_to_int(df["Seats"])
    df["Order Total (USD)"] = pd.to_numeric(df["Order Total (USD)"], errors="raise")
    df["Order Date"] = pd.to_datetime(df["Order Date"], errors="raise")  # blanks -> NaT
    df["Rep"] = df["Rep"].astype(str).str.strip().replace({"": pd.NA, "nan": pd.NA})

    # --- DERIVE: impute the 16 blank order dates from the ref sequence ---
    booking_date, booking_date_inferred = _impute_booking_dates(df["Order Ref"], df["Order Date"])

    # --- MAP: onto the unified schema ---
    out = pd.DataFrame(
        {
            "contract_id": df["Order Ref"],
            "product": "C",
            "product_subtype": df["Module"],
            "customer_id": df["Customer ID"],
            "customer_name": pd.NA,            # enriched in L3 from A by Customer ID
            "region": pd.NA,                   # enriched in L3 from A by Customer ID
            "booking_date": booking_date,
            "start_date": booking_date,
            "end_date": pd.NaT,                # one-time order, no coverage window
            "cancel_date": pd.NaT,
            "seats": df["Seats"],
            "currency_orig": "USD",
            "value_orig": df["Order Total (USD)"],
            "booking_value_usd": df["Order Total (USD)"],
            "arr_usd": 0.0,                    # one-time -> no recurring value
            "revenue_type": "one-time",
            "status": pd.NA,                   # set with active-rule (L3)
            "is_active": pd.NA,                # set with active-rule (L3)
            "is_renewal": pd.NA,               # not applicable to one-off orders
            "is_renewal_inferred": False,
            "booking_date_inferred": booking_date_inferred,
            "source_file": PRODUCT_C_PATH.name,
            "loaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
    )
    return conform(out)


def reconcile(raw: pd.DataFrame, clean: pd.DataFrame) -> None:
    footer = _footer_total(raw)

    before = profile(clean, value_cols=("seats", "booking_value_usd"), key_col="customer_id")
    compare(
        {"rows": 375, "footer_total_usd": footer},
        {"rows": before["rows"], "footer_total_usd": float(clean["booking_value_usd"].sum())},
        label="Product C (source footer vs clean)",
    )

    checks = {
        "375 order rows": len(clean) == 375,
        "value total == footer TOTAL": round(float(clean["booking_value_usd"].sum()), 2)
        == round(footer, 2),
        "no junk leaked (all SO- ids)": clean["contract_id"].str.startswith("SO-").all(),
        "seats all positive ints": (clean["seats"] > 0).all(),
        "booking_date fully populated": clean["booking_date"].notna().all(),
        "16 dates imputed": int(clean["booking_date_inferred"].sum()) == 16,
        "imputed dates within data range": bool(
            (clean["booking_date"].min() >= pd.Timestamp("2023-03-09"))
            and (clean["booking_date"].max() <= pd.Timestamp("2026-09-29"))
        ),
        "all one-time / arr 0": bool(
            (clean["revenue_type"] == "one-time").all() and (clean["arr_usd"] == 0).all()
        ),
        "all USD": bool((clean["currency_orig"] == "USD").all()),
        "order_total <= seats * unit_price (discount >= 0)": _discount_non_negative(raw),
    }
    print("\nCHECKS")
    for name, ok in checks.items():
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    if not all(checks.values()):
        raise SystemExit("Reconciliation FAILED — stopping.")
    print("\nAll reconciliation checks passed. ✅")


def _discount_non_negative(raw: pd.DataFrame) -> bool:
    """Sanity check: Order Total <= Seats * Unit Price (a discount, never a markup).

    C orders carry discounts (0/5/10/15%), so total == seats*unit does NOT hold,
    but total should never exceed the undiscounted list amount.
    """
    hdr = _locate_header(raw)
    df = raw.iloc[hdr + 1 :].copy()
    df.columns = raw.iloc[hdr].tolist()
    df = df[df["Order Ref"].astype(str).str.startswith("SO-")]
    seats = _seats_to_int(df["Seats"])
    unit = pd.to_numeric(df["Unit Price (USD)"], errors="raise")
    total = pd.to_numeric(df["Order Total (USD)"], errors="raise")
    return bool((total <= seats * unit).all())


if __name__ == "__main__":
    raw = load_product_c()
    clean = transform_product_c(raw)
    reconcile(raw, clean)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / "clean_product_c.csv"
    clean.to_csv(out_path, index=False)
    print(f"\nWrote {len(clean):,} rows -> {out_path}")
    print("\n--- preview ---")
    cols = ["contract_id", "product_subtype", "customer_id", "booking_date",
            "seats", "booking_value_usd", "arr_usd", "revenue_type"]
    print(clean[cols].head(6).to_string())
