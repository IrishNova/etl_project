"""The unified (common) schema every source conforms to before stacking (L3).

One row = one contract. Keeping this list in one place guarantees all three
sources line up column-for-column, so L3 is just a `pd.concat`.
"""

from __future__ import annotations

import pandas as pd

# Column order of the single source of truth.
UNIFIED_COLUMNS: list[str] = [
    # --- identity / dimensions ---
    "contract_id",        # original source id, kept for traceability
    "product",            # A / B / C — which product line
    "product_subtype",    # SKU / plan / module within the product
    "customer_id",        # source customer key (canonicalised later)
    "customer_name",      # cleaned company name
    "region",             # NA / EU / UK (never silently null)
    # --- dates ---
    "booking_date",       # when it was sold — drives bookings / TTM
    "start_date",         # coverage start
    "end_date",           # coverage end; null = perpetual / one-off
    "cancel_date",        # when cancelled, if ever (drives churn timing)
    # --- measures ---
    "seats",              # normalised integer
    "currency_orig",      # what the source charged in
    "value_orig",         # amount in the original currency
    "booking_value_usd",  # total booked amount, converted -> bookings / TTM
    "arr_usd",            # annualised recurring value; 0 for one-time -> ARR
    # --- classification / provenance ---
    "revenue_type",       # recurring / one-time
    "status",             # active / expired / cancelled (set once active-rule is locked)
    "is_active",          # bool as-of a reference date (set with active-rule)
    "is_renewal",         # was this a renewal of a prior contract? (drives churn/retention)
    "is_renewal_inferred",# True if is_renewal was imputed (source blank), not source-given
    "booking_date_inferred",  # True if booking_date was imputed (source blank)
    "source_file",        # provenance
    "loaded_at",          # audit timestamp
]

REVENUE_TYPES = {"recurring", "one-time"}


def conform(df: pd.DataFrame) -> pd.DataFrame:
    """Return df with exactly UNIFIED_COLUMNS, in order.

    Missing columns are added as NA; unexpected columns raise, so a mapping
    typo is caught loudly instead of silently polluting the schema.
    """
    extra = set(df.columns) - set(UNIFIED_COLUMNS)
    if extra:
        raise ValueError(f"Columns not in unified schema: {sorted(extra)}")
    for col in UNIFIED_COLUMNS:
        if col not in df.columns:
            df[col] = pd.NA
    return df[UNIFIED_COLUMNS]
