"""Level 2 — Transform: Product A (legacy licenses).

Takes the raw, all-text frame from L1 and conforms it to the unified schema:
  map  -> rename A's columns onto the common schema
  clean-> type values, strip whitespace, drop exact dupes, backfill region
  derive-> revenue_type, arr_usd, provenance

Decisions locked for A (see PROGRESS.md):
  [2] blank region -> backfilled from the same customer's known region
  [3] 16 exact-duplicate rows -> dropped (keep first)
  [4] Perpetual = one-time (arr 0); Maintenance Renewal = recurring (arr = net_amount)
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from etl.extract.sources import PRODUCT_A_PATH, load_product_a
from etl.schema import conform
from etl.transform.validation import compare, profile

OUTPUT_DIR = Path(__file__).resolve().parents[3] / "data" / "processed"

# Product A's license types -> how they behave financially.
REVENUE_TYPE_BY_LICENSE = {
    "Perpetual": "one-time",
    "Maintenance Renewal": "recurring",
}


def _backfill_from_customer(df: pd.DataFrame, col: str, fallback: str) -> pd.Series:
    """Fill a column's blanks from the same customer's known value for it.

    Verified safe for both region and customer_name: every blank-valued
    customer has exactly one known value elsewhere, with no conflicts. The
    `fallback` guards the (currently empty) case of a customer with no value
    anywhere, so nothing is ever invented.
    """
    known = (
        df[df[col] != ""]
        .groupby("cust_id")[col]
        .agg(lambda s: s.mode().iat[0])
    )
    filled = df[col].copy()
    blank = filled == ""
    filled.loc[blank] = df.loc[blank, "cust_id"].map(known)
    return filled.replace("", fallback).fillna(fallback)


def transform_product_a(raw: pd.DataFrame) -> pd.DataFrame:
    df = raw.copy()

    # --- CLEAN: drop the 16 verified exact-duplicate rows ---
    df = df.drop_duplicates(keep="first")

    # --- CLEAN: types (raise loudly if any value won't convert) ---
    df["seats"] = pd.to_numeric(df["seats"], errors="raise").astype("int64")
    df["net_amount_usd"] = pd.to_numeric(df["net_amount_usd"], errors="raise")
    df["sold_date"] = pd.to_datetime(df["sold_date"], format="%Y-%m-%d", errors="raise")

    # --- CLEAN: whitespace + backfill blanks from the same customer ---
    df["customer_name"] = df["customer_name"].str.strip()
    df["region"] = df["region"].str.strip()
    df["customer_name"] = _backfill_from_customer(df, "customer_name", fallback="Unknown")
    df["region"] = _backfill_from_customer(df, "region", fallback="Unknown")

    # --- CLEAN: normalize SKU — source has case drift (ia-core vs IA-CORE). SKUs
    # are codes, so canonical form is upper-cased + stripped. ---
    df["sku"] = df["sku"].str.strip().str.upper()

    # --- DERIVE: revenue_type + arr ---
    revenue_type = df["license_type"].map(REVENUE_TYPE_BY_LICENSE)
    if revenue_type.isna().any():
        bad = sorted(df.loc[revenue_type.isna(), "license_type"].unique())
        raise ValueError(f"Unmapped license_type values: {bad}")
    arr = df["net_amount_usd"].where(revenue_type == "recurring", 0.0)

    # --- DERIVE: coverage window end_date ---
    # Maintenance Renewal = 1-year term from start. Perpetual has no term (NaT).
    # This is the only real new fact; is_active is NOT stored — it's computed at
    # view time from [start_date, end_date] by active_as_of() for a chosen date.
    end_date = (df["sold_date"] + pd.DateOffset(years=1)).where(
        revenue_type == "recurring", pd.NaT
    )

    # --- MAP: onto the unified schema ---
    out = pd.DataFrame(
        {
            "contract_id": df["license_id"],
            "product": "A",
            "product_subtype": df["sku"],
            "customer_id": df["cust_id"],
            "customer_name": df["customer_name"],
            "region": df["region"],
            "booking_date": df["sold_date"],
            "start_date": df["sold_date"],
            "end_date": end_date,               # maintenance = +1yr; perpetual = NaT
            "seats": df["seats"],
            "currency_orig": "USD",
            "value_orig": df["net_amount_usd"],
            "booking_value_usd": df["net_amount_usd"],
            "arr_usd": arr,
            "revenue_type": revenue_type,
            "status": pd.NA,                    # derived at view time (not a stored fact)
            "is_active": pd.NA,                 # derived at view time by active_as_of()
            "is_renewal": pd.NA,                # not applicable to A
            "is_renewal_inferred": False,
            "booking_date_inferred": False,     # A dates are all source-given
            "source_file": PRODUCT_A_PATH.name,
            "loaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
    )
    return conform(out)


def reconcile(raw: pd.DataFrame, clean: pd.DataFrame) -> None:
    """Prove the only rows that disappeared are the 16 known exact dupes,
    and that seats/value/customers are otherwise preserved."""
    raw_dedup = raw.drop_duplicates(keep="first")

    before = profile(raw_dedup, value_cols=("seats", "net_amount_usd"), key_col="cust_id")
    after = profile(clean, value_cols=("seats", "booking_value_usd"), key_col="customer_id")
    # rename after-keys so the table lines up
    after = {
        "rows": after["rows"],
        "sum_seats": after["sum_seats"],
        "sum_net_amount_usd": after["sum_booking_value_usd"],
        "nunique_cust_id": after["nunique_customer_id"],
    }
    compare(before, after, label="Product A (raw de-duped vs clean)")

    checks = {
        "rows preserved after dedup": before["rows"] == after["rows"],
        "seats total preserved": round(before["sum_seats"], 2) == round(after["sum_seats"], 2),
        "value total preserved": round(before["sum_net_amount_usd"], 2)
        == round(after["sum_net_amount_usd"], 2),
        "distinct customers preserved": before["nunique_cust_id"] == after["nunique_cust_id"],
        "no blank/null regions": (clean["region"].notna() & (clean["region"] != "")).all(),
        "no blank/null customer names": (
            clean["customer_name"].notna() & (clean["customer_name"] != "")
        ).all(),
        "product_subtype normalized (no case/space variants)": bool(
            (clean["product_subtype"] == clean["product_subtype"].str.strip().str.upper()).all()
        ),
        "no names invented (all names appear in source)": set(clean["customer_name"])
        <= set(raw["customer_name"].str.strip()) | {"Unknown"},
        "arr == value for recurring only": round(
            float(clean.loc[clean["revenue_type"] == "recurring", "booking_value_usd"].sum()), 2
        )
        == round(float(clean["arr_usd"].sum()), 2),
        "arr == 0 for one-time": float(
            clean.loc[clean["revenue_type"] == "one-time", "arr_usd"].sum()
        )
        == 0.0,
        "recurring has a 1yr window": bool(
            (
                clean.loc[clean["revenue_type"] == "recurring", "end_date"]
                == clean.loc[clean["revenue_type"] == "recurring", "start_date"]
                + pd.DateOffset(years=1)
            ).all()
        ),
        "one-time/perpetual has no end_date": bool(
            clean.loc[clean["revenue_type"] == "one-time", "end_date"].isna().all()
        ),
    }
    print("\nCHECKS")
    for name, ok in checks.items():
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    if not all(checks.values()):
        raise SystemExit("Reconciliation FAILED — stopping.")
    print("\nAll reconciliation checks passed. ✅")


if __name__ == "__main__":
    raw = load_product_a()
    clean = transform_product_a(raw)
    reconcile(raw, clean)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / "clean_product_a.csv"
    clean.to_csv(out_path, index=False)
    print(f"\nWrote {len(clean):,} rows -> {out_path}")
    print("\n--- preview ---")
    print(clean.head(5).to_string())
