"""Level 2 — Transform: Product B (CAD subscriptions).

Raw all-text frame from L1 -> unified schema.

Decisions locked for B (see PROGRESS.md):
  [1] currency -> convert to USD at the rate on the BOOKING date (cached FX, ffill)
  [2] mixed dates (US mm/dd/yyyy + ISO) -> parsed to datetime, like A
  [3] 4 exact-duplicate contract_nos -> dropped (keep first); 0 conflicts
  [4] status (Active/Expired/Cancelled) normalised; is_active, is_renewal, cancel_date set

B is entirely subscriptions, so revenue_type = recurring and arr_usd = annual_value
(converted). booking_value_usd = annual_value (converted) too.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from etl.extract.sources import PRODUCT_B_PATH, load_product_b
from etl.fx import to_usd
from etl.schema import conform
from etl.transform.validation import compare, profile

OUTPUT_DIR = Path(__file__).resolve().parents[3] / "data" / "processed"

STATUS_MAP = {"Active": "active", "Expired": "expired", "Cancelled": "cancelled"}
RENEWAL_MAP = {"Y": True, "N": False}

# A contract is a renewal if the same customer has a prior contract whose term
# ended within this many days of its start (ends day X, renews day X+1).
# Validated against known labels: precision 98.76%, recall 100%, 6 FPs / 1079.
RENEWAL_GAP_DAYS = 1


def _parse_mixed_date(s: pd.Series) -> pd.Series:
    """Parse a column holding both US (mm/dd/yyyy) and ISO (yyyy-mm-dd) dates.

    Keyed off the separator so there is no day/month ambiguity. Empty strings
    become NaT.
    """
    s = s.astype(str).str.strip()
    out = pd.Series(pd.NaT, index=s.index, dtype="datetime64[ns]")
    iso = s.str.contains("-", na=False)
    us = s.str.contains("/", na=False)
    out[iso] = pd.to_datetime(s[iso], format="%Y-%m-%d", errors="raise")
    out[us] = pd.to_datetime(s[us], format="%m/%d/%Y", errors="raise")
    return out


def _map_strict(series: pd.Series, mapping: dict, name: str) -> pd.Series:
    """Map values, raising loudly if any value is unmapped."""
    out = series.map(mapping)
    if out.isna().any():
        bad = sorted(series[out.isna()].unique())
        raise ValueError(f"Unmapped {name} values: {bad}")
    return out


def _infer_renewal(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Resolve is_renewal, filling source blanks by inference.

    Source Y/N labels are kept verbatim. Where the source is blank, infer:
    a contract is a renewal if the same customer has a PRIOR contract whose
    end_date is within RENEWAL_GAP_DAYS of this contract's start_date.

    Returns (is_renewal: bool, is_renewal_inferred: bool). Known labels are
    never overwritten; only blanks get the inferred value and the flag.
    """
    known = df["is_renewal"].str.strip().map(RENEWAL_MAP)  # True / False / NaN(blank)

    inferred = pd.Series(False, index=df.index)
    ordered = df.sort_values(["account_number", "start_date"])
    for _, grp in ordered.groupby("account_number", sort=False):
        starts = grp["start_date"].to_numpy()
        ends = grp["end_date"].to_numpy()
        idx = grp.index.to_numpy()
        for i in range(len(grp)):
            gap = np.abs((ends[:i] - starts[i]) / np.timedelta64(1, "D"))
            inferred.loc[idx[i]] = bool((gap <= RENEWAL_GAP_DAYS).any())

    is_inferred = known.isna()
    resolved = known.copy()
    resolved[is_inferred] = inferred[is_inferred]
    return resolved.astype(bool), is_inferred


def transform_product_b(raw: pd.DataFrame) -> pd.DataFrame:
    df = raw.copy()

    # --- CLEAN: drop the 4 verified exact-duplicate rows ---
    df = df.drop_duplicates(keep="first")

    # --- CLEAN: types ---
    df["seats"] = pd.to_numeric(df["seats"], errors="raise").astype("int64")
    df["annual_value"] = pd.to_numeric(df["annual_value"], errors="raise")
    df["start_date"] = _parse_mixed_date(df["start_date"])
    df["end_date"] = _parse_mixed_date(df["end_date"])
    df["cancel_date"] = _parse_mixed_date(df["cancel_date"])
    df["account_name"] = df["account_name"].str.strip()

    # --- DERIVE: status / renewal flags ---
    status = _map_strict(df["status"], STATUS_MAP, "status")
    is_renewal, is_renewal_inferred = _infer_renewal(df)

    # --- DERIVE: currency -> USD at booking (start) date ---
    value_usd = to_usd(df["annual_value"], df["currency"], df["start_date"])

    # --- MAP: onto the unified schema ---
    out = pd.DataFrame(
        {
            "contract_id": df["contract_no"],
            "product": "B",
            "product_subtype": df["plan"],
            "customer_id": df["account_number"],
            "customer_name": df["account_name"],
            "region": df["country_region"].str.strip(),
            "booking_date": df["start_date"],
            "start_date": df["start_date"],
            "end_date": df["end_date"],
            "cancel_date": df["cancel_date"],
            "seats": df["seats"],
            "currency_orig": df["currency"],
            "value_orig": df["annual_value"],
            "booking_value_usd": value_usd,
            "arr_usd": value_usd,                 # all B is recurring annual value
            "revenue_type": "recurring",
            "status": status,
            "is_active": status == "active",
            "is_renewal": is_renewal,
            "is_renewal_inferred": is_renewal_inferred,
            "booking_date_inferred": False,     # B dates are all source-given
            "source_file": PRODUCT_B_PATH.name,
            "loaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
    )
    return conform(out)


def _fx_conversion_ok(clean: pd.DataFrame) -> bool:
    """Verify booking_value_usd == value_orig * (rate on the booking date).

    Independently re-looks-up each row's rate from the cached FX table, so a
    wrong-date join would be caught. No directional assumption (EUR dipped
    below parity in 2022, so conversions can legitimately go down).
    """
    from etl.fx import load_fx_rates

    rates = load_fx_rates()
    day = clean["booking_date"].dt.normalize()
    expected = pd.Series(index=clean.index, dtype="float64")
    for cur in clean["currency_orig"].unique():
        mask = clean["currency_orig"] == cur
        expected.loc[mask] = clean.loc[mask, "value_orig"].to_numpy() * rates.loc[day[mask], cur].to_numpy()
    return bool(np.isclose(expected, clean["booking_value_usd"], rtol=1e-9).all())


def _known_labels_untouched(raw_dedup: pd.DataFrame, clean: pd.DataFrame) -> bool:
    """Every source-given Y/N label must survive unchanged in the output."""
    src = raw_dedup.set_index("contract_no")["is_renewal"].str.strip().map(RENEWAL_MAP).dropna()
    got = clean.set_index("contract_id")["is_renewal"].reindex(src.index)
    return bool((src.astype(bool) == got.astype(bool)).all())


def reconcile(raw: pd.DataFrame, clean: pd.DataFrame) -> None:
    raw_dedup = raw.drop_duplicates(keep="first")

    before = profile(raw_dedup, value_cols=("seats", "annual_value"), key_col="account_number")
    after = profile(clean, value_cols=("seats", "value_orig"), key_col="customer_id")
    after = {
        "rows": after["rows"],
        "sum_seats": after["sum_seats"],
        "sum_annual_value": after["sum_value_orig"],
        "nunique_account_number": after["nunique_customer_id"],
    }
    compare(before, after, label="Product B (raw de-duped vs clean, original currency)")

    usd = clean["currency_orig"] == "USD"
    checks = {
        "rows preserved after dedup": before["rows"] == after["rows"],
        "seats total preserved": round(before["sum_seats"], 2) == round(after["sum_seats"], 2),
        "value_orig total preserved": round(before["sum_annual_value"], 2)
        == round(after["sum_annual_value"], 2),
        "distinct customers preserved": before["nunique_account_number"]
        == after["nunique_account_number"],
        "USD converts 1:1": bool(
            (clean.loc[usd, "booking_value_usd"] == clean.loc[usd, "value_orig"]).all()
        ),
        "FX matches rate on booking date": _fx_conversion_ok(clean),
        "arr == booking_value (all recurring)": bool(
            (clean["arr_usd"] == clean["booking_value_usd"]).all()
        ),
        "no NaT booking_date": clean["booking_date"].notna().all(),
        "no blank/null region": (clean["region"].notna() & (clean["region"] != "")).all(),
        "is_active == (status active)": bool(
            (clean["is_active"] == (clean["status"] == "active")).all()
        ),
        "cancel_date iff cancelled": bool(
            (clean["cancel_date"].notna() == (clean["status"] == "cancelled")).all()
        ),
        "is_renewal fully populated": clean["is_renewal"].notna().all(),
        "inferred count == source blanks (36)": int(clean["is_renewal_inferred"].sum()) == 36,
        "known labels untouched": _known_labels_untouched(raw_dedup, clean),
    }
    print("\nCHECKS")
    for name, ok in checks.items():
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    if not all(checks.values()):
        raise SystemExit("Reconciliation FAILED — stopping.")
    print("\nAll reconciliation checks passed. ✅")


if __name__ == "__main__":
    raw = load_product_b()
    clean = transform_product_b(raw)
    reconcile(raw, clean)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / "clean_product_b.csv"
    clean.to_csv(out_path, index=False)
    print(f"\nWrote {len(clean):,} rows -> {out_path}")
    print("\n--- preview (currency conversion) ---")
    cols = ["contract_id", "customer_name", "region", "booking_date",
            "currency_orig", "value_orig", "booking_value_usd", "status", "is_renewal"]
    print(clean[cols].head(6).to_string())
