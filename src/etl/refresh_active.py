"""Nightly is_active / status refresh — the SLOW LOOP entrypoint (cron).

A contract can only flip active<->expired at a day boundary, so recomputing on the
n-minute ingest loop would be wasted work. This job runs nightly: it reads the stored
coverage window (start/end/cancel) for every contract, evaluates active_as_of() at the
configured as-of date (default: today), and writes is_active + status back into
fact_contracts.

active_as_of() stays the single definition of "active"; this job merely materializes
its output on the cadence it can change, so the Flask API / front end read a ready-made
column instead of recomputing per request.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
from sqlalchemy import Engine, bindparam, select, update

from etl.config import load_config
from etl.load.db import get_engine
from etl.load.tables import fact_contracts
from etl.views.active import active_as_of


def _resolve_as_of(cfg: dict) -> pd.Timestamp:
    val = cfg.get("active_refresh", {}).get("as_of", "today")
    return pd.Timestamp(date.today()) if val == "today" else pd.Timestamp(val)


def refresh(engine: Engine | None = None, as_of: pd.Timestamp | None = None) -> dict:
    engine = engine or get_engine()
    if as_of is None:
        as_of = _resolve_as_of(load_config())

    cols = ["product", "contract_id", "revenue_type", "start_date", "end_date", "cancel_date"]
    sel = select(*[fact_contracts.c[c] for c in cols])
    with engine.connect() as conn:
        df = pd.DataFrame(conn.execute(sel).mappings().all())

    derived = active_as_of(df, as_of)
    df["is_active"] = derived["is_active"]
    df["status"] = derived["status_asof"]

    params = [
        {
            "_product": r.product,
            "_contract_id": r.contract_id,
            "_is_active": None if pd.isna(r.is_active) else bool(r.is_active),
            "_status": None if (r.status is None or pd.isna(r.status)) else str(r.status),
        }
        for r in df.itertuples(index=False)
    ]

    stmt = (
        update(fact_contracts)
        .where(fact_contracts.c.product == bindparam("_product"))
        .where(fact_contracts.c.contract_id == bindparam("_contract_id"))
        .values(is_active=bindparam("_is_active"), status=bindparam("_status"))
    )
    with engine.begin() as conn:
        conn.execute(stmt, params)

    return {
        "as_of": as_of.date().isoformat(),
        "rows": len(df),
        "by_status": df["status"].value_counts(dropna=False).to_dict(),
    }


if __name__ == "__main__":
    res = refresh()
    print(f"is_active/status refreshed as of {res['as_of']}  ({res['rows']:,} rows)")
    for status, n in sorted(res["by_status"].items(), key=lambda kv: str(kv[0])):
        print(f"  {str(status):>10}: {n:>5}")
