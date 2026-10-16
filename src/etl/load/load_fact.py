"""Load (L) layer — load the star schema into Postgres with idempotent upserts.

The upsert (INSERT .. ON CONFLICT DO UPDATE on the primary key) is the heart of
"add new data": re-running loads nothing new if the input is unchanged, and merges
new/changed rows on their key with no duplicates. This is the same discipline as
an orderbook ingest — the pipeline is safe to run as many times as you like.

Load order respects the FKs: dim_company first (the parent), then fact_contracts
and map_customer (which reference it).

Row coercion is driven by the SQLAlchemy column types in tables.py, so dates,
money, booleans and ""->NULL are all handled consistently and can't drift from
the DDL.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import Boolean, Date, DateTime, Engine, Integer, Numeric, Table, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from etl.load.db import get_engine
from etl.load.tables import create_schema, dim_company, fact_contracts, map_customer, metadata

PROCESSED = Path(__file__).resolve().parents[3] / "data" / "processed"


def _read(name: str) -> pd.DataFrame:
    # keep_default_na=False so region "NA" (North America) is NOT read as NaN;
    # genuine blanks arrive as "" and are turned into NULL by the type coercion.
    return pd.read_csv(PROCESSED / name, keep_default_na=False, na_values=[])


def _read_crosswalk() -> pd.DataFrame:
    x = _read("customer_crosswalk.csv")
    # needs_review is already read as a real bool dtype (pandas infers True/False
    # text), so it is left as-is; _records handles the Boolean column on insert.
    x["company_legal_entities"] = pd.to_numeric(x["company_legal_entities"], errors="coerce").astype("Int64")
    x["match_score"] = pd.to_numeric(x["match_score"], errors="coerce")
    x["company_id"] = x["company_id"].replace("", pd.NA)
    x["company_name"] = x["company_name"].replace("", pd.NA)
    return x


def build_dim_company(xwalk: pd.DataFrame) -> pd.DataFrame:
    """One row per company (drops the un-placeable C-only rows that have no id)."""
    placed = xwalk[xwalk["company_id"].notna()]
    return (
        placed.groupby("company_id", as_index=False)
        .agg(
            company_name=("company_name", "first"),
            region=("region", "first"),
            needs_review=("needs_review", "max"),       # flagged if ANY member is
            n_legal_entities=("company_legal_entities", "max"),
        )
    )


def _py(v):
    """One scalar -> a Postgres-friendly native (None for any NA, unwrap numpy)."""
    if v is None or v is pd.NA:
        return None
    if isinstance(v, float) and np.isnan(v):
        return None
    if isinstance(v, np.generic):
        return v.item()
    return v


def _records(table: Table, df: pd.DataFrame) -> list[dict]:
    """Coerce df to row dicts typed per the table's columns; NA -> None."""
    df = df.copy()
    for col in table.columns:
        if col.name not in df.columns:
            continue
        s = df[col.name]
        if isinstance(col.type, (Date, DateTime)):
            s = pd.to_datetime(s, errors="coerce")
            if isinstance(col.type, Date):
                s = s.dt.date
            df[col.name] = s
        elif isinstance(col.type, Integer):
            df[col.name] = pd.to_numeric(s, errors="coerce").astype("Int64")
        elif isinstance(col.type, Numeric):
            df[col.name] = pd.to_numeric(s, errors="coerce")
        elif isinstance(col.type, Boolean):
            df[col.name] = s.map({"True": True, "False": False, True: True, False: False})
        else:  # Text
            df[col.name] = s.replace("", pd.NA)

    cols = [c.name for c in table.columns if c.name in df.columns]
    df = df[cols].replace({pd.NaT: None})
    return [{k: _py(v) for k, v in rec.items()} for rec in df.to_dict("records")]


def upsert(engine: Engine, table: Table, df: pd.DataFrame, update: bool = True) -> int:
    """INSERT .. ON CONFLICT (pk). Idempotent.

    update=True  -> DO UPDATE every non-key column (merge changes on the key).
    update=False -> DO NOTHING (insert new keys only; never clobber existing rows,
                    e.g. don't overwrite an existing company's attributes).
    """
    records = _records(table, df)
    if not records:
        return 0
    stmt = pg_insert(table)
    pk = [c.name for c in table.primary_key.columns]
    if update:
        updates = {c.name: stmt.excluded[c.name] for c in table.columns if c.name not in pk}
        stmt = stmt.on_conflict_do_update(index_elements=pk, set_=updates)
    else:
        stmt = stmt.on_conflict_do_nothing(index_elements=pk)
    with engine.begin() as conn:
        conn.execute(stmt, records)
    return len(records)


def load_all(engine: Engine | None = None) -> None:
    engine = engine or get_engine()
    create_schema(engine)  # create_all is idempotent; no-op if tables exist

    xwalk = _read_crosswalk()
    fact = _read("unified_fact.csv")
    dim = build_dim_company(xwalk)

    n_dim = upsert(engine, dim_company, dim)          # parent first (FK)
    n_fact = upsert(engine, fact_contracts, fact)
    n_map = upsert(engine, map_customer, xwalk)

    print("upserted:")
    print(f"  dim_company    : {n_dim:>5}")
    print(f"  fact_contracts : {n_fact:>5}")
    print(f"  map_customer   : {n_map:>5}")

    _reconcile(engine, fact)


def _reconcile(engine: Engine, src_fact: pd.DataFrame) -> None:
    with engine.connect() as conn:
        db_rows = conn.execute(select(func.count()).select_from(fact_contracts)).scalar_one()
        db_value = conn.execute(select(func.sum(fact_contracts.c.booking_value_usd))).scalar_one()
        db_companies = conn.execute(select(func.count()).select_from(dim_company)).scalar_one()
        orphans = conn.execute(
            select(func.count())
            .select_from(fact_contracts)
            .where(
                fact_contracts.c.company_id.isnot(None),
                fact_contracts.c.company_id.notin_(select(dim_company.c.company_id)),
            )
        ).scalar_one()

    src_value = round(float(src_fact["booking_value_usd"].sum()), 2)
    checks = {
        "fact rows == source": db_rows == len(src_fact),
        "booking_value matches source": round(float(db_value), 2) == src_value,
        "no orphan company_id (FK holds)": orphans == 0,
        "dim has companies": db_companies > 0,
    }
    print("\n===== RECONCILIATION — Postgres vs source =====")
    print(f"fact rows: db={db_rows}  source={len(src_fact)}")
    print(f"booking_value_usd: db=${float(db_value):,.2f}  source=${src_value:,.2f}")
    print(f"companies: {db_companies}   orphan company_ids: {orphans}")
    print("\nCHECKS")
    for name, ok in checks.items():
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    if not all(checks.values()):
        raise SystemExit("Load reconciliation FAILED — stopping.")
    print("\nLoad reconciled. ✅")


if __name__ == "__main__":
    load_all()
