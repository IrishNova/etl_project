"""Level 3 — customer identity: assign every customer a canonical company_id.

MODEL 2 (company grain): a "company" = normalized base name + region. Legal-entity
suffixes (Corp/Inc/LLC/GmbH) are treated as sub-entities of one company, which is
the right grain for "licenses BY COMPANY" reporting and resolves 100% of customers
(no ambiguous leftovers). The legal-entity name is kept as a detail column.

Linking across sources:
  - A: company_id from its own (normalized name, region).
  - C: shares A's C-100xx id scheme -> inherits A's company_id by customer_id join.
       C-only ids (no A record, and C has no name) can't be placed -> flagged.
  - B: own numeric ids -> matched to A companies by name:
       exact (norm, region) -> fuzzy >= FUZZY_THRESHOLD within region -> else B-only.

needs_review = True on the uncertain assignments (fuzzy matches and C-only-unmatched),
so a later build step can trigger a manual-review notification on exactly those.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from rapidfuzz import fuzz, process

from etl.unify.names import normalize_name

PROCESSED = Path(__file__).resolve().parents[3] / "data" / "processed"
FUZZY_THRESHOLD = 90  # empty score gap 83..96 in the data makes this safe


def _read_clean(name: str) -> pd.DataFrame:
    # keep_default_na=False so region "NA" (North America) is NOT read as NaN.
    return pd.read_csv(PROCESSED / name, keep_default_na=False, na_values=[])


def _company_id(norm: str, region: str) -> str:
    return f"{norm}|{region}"


def _company_name(norm: str, region: str) -> str:
    return f"{norm.title()} ({region})" if norm else f"(unknown) ({region})"


def build_customer_crosswalk() -> pd.DataFrame:
    a = _read_clean("clean_product_a.csv")
    b = _read_clean("clean_product_b.csv")
    c = _read_clean("clean_product_c.csv")

    # --- A: the company registry ---
    a_cust = a[["customer_id", "customer_name", "region"]].drop_duplicates().copy()
    a_cust["norm"] = a_cust["customer_name"].map(normalize_name)
    a_cust["company_id"] = [_company_id(n, r) for n, r in zip(a_cust["norm"], a_cust["region"])]
    # A company set for B matching, and id->company map for C inheritance
    a_companies = set(zip(a_cust["norm"], a_cust["region"]))
    a_id_to_company = dict(zip(a_cust["customer_id"], a_cust["company_id"]))
    # distinct legal-entity names per company (for review context)
    legal_count = a_cust.groupby("company_id")["customer_name"].nunique().to_dict()
    a_norms_by_region: dict[str, list[str]] = (
        a_cust.groupby("region")["norm"].apply(lambda s: sorted(set(s))).to_dict()
    )

    rows: list[dict] = []

    def add(source, src_id, name, region, norm, company_id, method, review, score=pd.NA):
        rows.append({
            "source": source, "source_customer_id": src_id, "customer_name": name,
            "region": region, "company_id": company_id,
            "company_name": _company_name(norm, region),
            "match_method": method, "match_score": score, "needs_review": review,
        })

    # --- A rows: exact by construction ---
    for r in a_cust.itertuples(index=False):
        add("A", r.customer_id, r.customer_name, r.region, r.norm, r.company_id, "exact", False)

    # --- C rows: inherit A's company via shared customer_id ---
    c_cust = c[["customer_id"]].drop_duplicates()
    for cid in c_cust["customer_id"]:
        if cid in a_id_to_company:
            comp = a_id_to_company[cid]
            norm, region = comp.rsplit("|", 1)
            add("C", cid, pd.NA, region, norm, comp, "id_join", False)
        else:
            add("C", cid, pd.NA, pd.NA, "", pd.NA, "c_only_unmatched", True)

    # --- B rows: name match to A companies ---
    b_cust = b[["customer_id", "customer_name", "region"]].drop_duplicates().copy()
    b_cust["norm"] = b_cust["customer_name"].map(normalize_name)
    for r in b_cust.itertuples(index=False):
        if (r.norm, r.region) in a_companies:
            add("B", r.customer_id, r.customer_name, r.region, r.norm,
                _company_id(r.norm, r.region), "exact", False)
            continue
        pool = a_norms_by_region.get(r.region, [])
        hit = process.extractOne(r.norm, pool, scorer=fuzz.token_sort_ratio) if pool else None
        if hit and hit[1] >= FUZZY_THRESHOLD:
            matched_norm = hit[0]
            add("B", r.customer_id, r.customer_name, r.region, matched_norm,
                _company_id(matched_norm, r.region), "fuzzy", True, round(hit[1], 1))
        else:
            # genuine B-only company — it gets its own company_id, no review needed
            add("B", r.customer_id, r.customer_name, r.region, r.norm,
                _company_id(r.norm, r.region), "b_only", False)

    xwalk = pd.DataFrame(rows)
    xwalk["company_legal_entities"] = xwalk["company_id"].map(legal_count).fillna(1).astype(int)
    return xwalk


if __name__ == "__main__":
    x = build_customer_crosswalk()
    print("crosswalk rows (customers across A/B/C):", len(x))
    print("\nby source x method:")
    print(x.groupby(["source", "match_method"]).size().to_string())
    print(f"\ndistinct companies: {x['company_id'].nunique(dropna=True)}")
    print(f"customers flagged needs_review: {int(x['needs_review'].sum())}")
    print("\n--- needs_review sample ---")
    print(x[x["needs_review"]][["source", "customer_name", "company_name", "match_method", "match_score"]].head(10).to_string(index=False))

    out = PROCESSED / "customer_crosswalk.csv"
    x.to_csv(out, index=False)
    print(f"\nWrote crosswalk -> {out}")
