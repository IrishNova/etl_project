"""Incremental ingest — the FAST LOOP entrypoint (cron, every n minutes).

Pulls any new batches from the (mock) product APIs, runs each through the same
transform the seed data uses, resolves every customer to a company, and UPSERTS into
the warehouse. Idempotent: re-running a batch changes nothing; a brand-new contract
is inserted; a changed contract is updated in place — no duplicates, ever.

Load order respects the FKs: new companies into dim_company first (insert-only, so an
existing company's attributes are never clobbered), then facts, then the customer map.

Note (the "true incremental" wrinkle): B's renewal inference normally needs a
customer's history. Here the API supplies is_renewal on each record, so the batch is
self-contained. Inferring against warehouse history is a future enhancement; likewise
fuzzy name matching + needs_review flagging (the incremental path currently does exact
company match, else creates a new company).
"""

from __future__ import annotations

import pandas as pd
from sqlalchemy import Engine, select

from etl.extract.mock_api import archive_batch, iter_incoming_batches
from etl.load.db import get_engine
from etl.load.load_fact import upsert
from etl.load.tables import dim_company, fact_contracts, map_customer
from etl.transform.product_b import transform_product_b
from etl.unify.names import normalize_name


def _company(norm: str, region: str) -> tuple[str, str]:
    cid = f"{norm}|{region}"
    cname = f"{norm.title()} ({region})" if norm else f"(unknown) ({region})"
    return cid, cname


def ingest_batch(engine: Engine, path, raw: pd.DataFrame) -> dict:
    # --- Transform (same code path as the seed) ---
    clean = transform_product_b(raw)
    clean["source_file"] = path.name  # provenance: this batch, not the seed file

    # --- Resolve each customer to a company (Model 2: norm name + region) ---
    norms = clean["customer_name"].map(normalize_name)
    pairs = [_company(n, r) for n, r in zip(norms, clean["region"])]
    clean["company_id"] = [cid for cid, _ in pairs]
    company_names = [cname for _, cname in pairs]

    with engine.connect() as conn:
        existing = set(conn.execute(select(dim_company.c.company_id)).scalars())

    # New companies only -> dim rows (dedup within the batch)
    dim_rows, seen = [], set()
    for (cid, cname), region in zip(pairs, clean["region"]):
        if cid not in existing and cid not in seen:
            seen.add(cid)
            dim_rows.append(
                {"company_id": cid, "company_name": cname, "region": region,
                 "needs_review": False, "n_legal_entities": 1}
            )
    dim_df = pd.DataFrame(dim_rows)

    # Customer-map rows (audit): exact if the company already existed, else b_only
    map_df = pd.DataFrame(
        {
            "source": "B",
            "source_customer_id": clean["customer_id"].astype(str),
            "customer_name": clean["customer_name"],
            "region": clean["region"],
            "company_id": clean["company_id"],
            "company_name": company_names,
            "match_method": ["exact" if c in existing else "b_only" for c in clean["company_id"]],
            "match_score": pd.NA,
            "needs_review": False,
            "company_legal_entities": pd.NA,
        }
    )

    # --- Upsert: dim (insert-only) -> fact -> map ---
    n_new_comp = upsert(engine, dim_company, dim_df, update=False)
    n_fact = upsert(engine, fact_contracts, clean)
    n_map = upsert(engine, map_customer, map_df)
    return {"new_companies": n_new_comp, "facts": n_fact, "mappings": n_map}


def run(product: str = "B") -> None:
    engine = get_engine()
    batches = list(iter_incoming_batches(product))
    if not batches:
        print("No incoming batches — nothing to ingest.")
        return
    for path, raw in batches:
        print(f"ingesting {path.name}  ({len(raw)} records)")
        res = ingest_batch(engine, path, raw)
        print(f"  new companies: {res['new_companies']}   "
              f"facts upserted: {res['facts']}   mappings upserted: {res['mappings']}")
        dest = archive_batch(path)
        print(f"  archived -> {dest.relative_to(dest.parents[3])}")


if __name__ == "__main__":
    run()
