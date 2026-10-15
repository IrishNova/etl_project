"""Level 3 — Unify: stack the three clean sources into one fact table.

This is the payoff: the single source of truth. Every source was already
conformed to the same 23-col schema in L2, so the stack itself is a concat.
Two enrichments turn the pile of rows into a queryable table:

  1. company_id — join the customer crosswalk (Model 2) so every row knows which
     COMPANY it belongs to, across A/B/C's incompatible id schemes.
  2. C's customer_name/region — C ships neither; inherit them from A by the
     shared C-100xx customer_id. The 11 C-only customers (no A record) stay null
     and keep their needs_review flag.

`status`/`is_active` are left exactly as each source stated them (B = vendor
label; A/C = <NA>). They are NOT the canonical activity answer — that is derived
for any date by views.active.active_as_of(). The stored window (start/end/cancel)
is what makes that derivation possible.

Output: data/processed/unified_fact.csv — one row per contract, 4,150 rows.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from etl.schema import UNIFIED_COLUMNS

PROCESSED = Path(__file__).resolve().parents[3] / "data" / "processed"

SOURCES = {"A": "clean_product_a.csv", "B": "clean_product_b.csv", "C": "clean_product_c.csv"}


def _read_clean(name: str) -> pd.DataFrame:
    # keep_default_na=False so region "NA" (North America) is NOT read as NaN;
    # genuine blanks come in as "" and are normalised to NA below.
    return pd.read_csv(PROCESSED / name, keep_default_na=False, na_values=[])


def _crosswalk_lookup() -> pd.DataFrame:
    """One row per (source, source_customer_id) -> company identity.

    Raises if a single customer maps to more than one company_id (would mean the
    crosswalk is ambiguous and the join could fan out).
    """
    x = _read_clean("customer_crosswalk.csv")
    key = ["source", "source_customer_id"]
    nun = x.groupby(key)["company_id"].nunique(dropna=False)
    if (nun > 1).any():
        bad = nun[nun > 1].index.tolist()
        raise ValueError(f"Crosswalk maps a customer to >1 company: {bad[:5]}")
    cols = key + ["company_id", "company_name", "needs_review"]
    return x[cols].drop_duplicates(subset=key)


def build_unified_fact() -> pd.DataFrame:
    # --- STACK: concat the three conformed sources ---
    frames = []
    for product, fname in SOURCES.items():
        df = _read_clean(fname)
        missing = set(UNIFIED_COLUMNS) - set(df.columns)
        if missing:
            raise ValueError(f"{fname} missing schema columns: {sorted(missing)}")
        frames.append(df[UNIFIED_COLUMNS])
    fact = pd.concat(frames, ignore_index=True)
    # B's customer_id reads back as int; A/C are "C-100xx" strings. Normalise to
    # string so the crosswalk join (its source_customer_id is string) matches.
    fact["customer_id"] = fact["customer_id"].astype(str)

    # --- ENRICH 1: C inherits customer_name/region from A by shared customer_id ---
    a = frames[0]  # clean_product_a, already in schema order
    name_by_id = a.drop_duplicates("customer_id").set_index("customer_id")["customer_name"]
    region_by_id = a.drop_duplicates("customer_id").set_index("customer_id")["region"]

    is_c = fact["product"] == "C"
    blank = lambda s: s.isna() | (s.astype(str).str.strip() == "")
    fill_name = is_c & blank(fact["customer_name"])
    fill_region = is_c & blank(fact["region"])
    fact.loc[fill_name, "customer_name"] = fact.loc[fill_name, "customer_id"].map(name_by_id)
    fact.loc[fill_region, "region"] = fact.loc[fill_region, "customer_id"].map(region_by_id)

    # --- ENRICH 2: attach company identity from the crosswalk ---
    xwalk = _crosswalk_lookup()
    fact = fact.merge(
        xwalk,
        how="left",
        left_on=["product", "customer_id"],
        right_on=["source", "source_customer_id"],
    ).drop(columns=["source", "source_customer_id"])

    # The crosswalk stores unmatched C-only identity as NA -> empty string in CSV.
    # We read with na_values=[] (to protect region "NA"), so restore those to NA.
    for col in ["company_id", "company_name"]:
        fact[col] = fact[col].replace("", pd.NA)

    return fact


def reconcile(fact: pd.DataFrame, frames: dict[str, pd.DataFrame]) -> None:
    n_a, n_b, n_c = (len(frames[k]) for k in "ABC")
    expected_rows = n_a + n_b + n_c
    src_value = sum(float(frames[k]["booking_value_usd"].sum()) for k in "ABC")

    print("===== RECONCILIATION — L3 unified fact =====")
    print(f"rows: A={n_a} + B={n_b} + C={n_c} = {expected_rows}   got: {len(fact)}")
    print(f"booking_value_usd: sources=${src_value:,.2f}   fact=${fact['booking_value_usd'].sum():,.2f}")

    c = fact[fact["product"] == "C"]
    c_named = int((~(c["customer_name"].isna() | (c["customer_name"].astype(str).str.strip() == ""))).sum())
    print(f"\nC rows: {len(c)}   enriched with a name: {c_named}   still null (C-only): {len(c) - c_named}")
    print(f"rows missing company_id: {int(fact['company_id'].isna().sum())}  (should equal the 11 C-only)")
    print(f"rows flagged needs_review: {int(fact['needs_review'].fillna(False).sum())}")

    checks = {
        "row count == sum of sources": len(fact) == expected_rows,
        "no rows invented/lost": len(fact) == expected_rows,
        "booking_value preserved": round(src_value, 2) == round(float(fact["booking_value_usd"].sum()), 2),
        "no duplicate contract_id within a product": not fact.duplicated(["product", "contract_id"]).any(),
        "every A/B row has company_id": bool(
            fact.loc[fact["product"].isin(["A", "B"]), "company_id"].notna().all()
        ),
        "only C-only rows lack company_id": bool(
            (fact["company_id"].isna() == ((fact["product"] == "C") & _c_only_mask(fact))).all()
        ),
        "every non-C-only row has a region": bool(
            fact.loc[fact["company_id"].notna(), "region"].notna().all()
        ),
        "schema columns all present": set(UNIFIED_COLUMNS) <= set(fact.columns),
    }
    print("\nCHECKS")
    for name, ok in checks.items():
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    if not all(checks.values()):
        raise SystemExit("Reconciliation FAILED — stopping.")
    print("\nAll reconciliation checks passed. ✅")


def _c_only_mask(fact: pd.DataFrame) -> pd.Series:
    """True where a C row's customer_id has no match in A (the 11 C-only)."""
    a_ids = set(fact.loc[fact["product"] == "A", "customer_id"])
    return ~fact["customer_id"].isin(a_ids)


if __name__ == "__main__":
    frames = {k: _read_clean(v)[UNIFIED_COLUMNS] for k, v in SOURCES.items()}
    fact = build_unified_fact()
    reconcile(fact, frames)

    out = PROCESSED / "unified_fact.csv"
    fact.to_csv(out, index=False)
    print(f"\nWrote {len(fact):,} rows x {fact.shape[1]} cols -> {out}")
    print("\n--- preview (one row per product) ---")
    cols = ["product", "contract_id", "customer_name", "region", "company_id",
            "booking_value_usd", "arr_usd", "revenue_type", "status"]
    print(fact.groupby("product").head(1)[cols].to_string(index=False))
