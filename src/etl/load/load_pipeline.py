"""Level 3/Load — load the conformed pipeline into Postgres.

Two tables in the same warehouse (reusing the type-driven upsert from load_fact):
  - fact_opportunity        : one row per opportunity (upsert on opportunity_id)
  - pipeline_stage_history  : stage-change event log (insert-only; events are immutable)

Idempotent: re-running merges, never duplicates.
"""

from __future__ import annotations

from sqlalchemy import Engine, func, select

from etl.extract.pipeline import load_opportunities, load_stage_history
from etl.load.db import get_engine
from etl.load.load_fact import upsert
from etl.load.tables import create_schema, fact_opportunity, pipeline_stage_history
from etl.transform.pipeline import transform_pipeline, transform_stage_history


def load_all(engine: Engine | None = None) -> None:
    engine = engine or get_engine()
    create_schema(engine)  # idempotent; creates the two new tables if absent

    opps = transform_pipeline(load_opportunities())
    hist = transform_stage_history(load_stage_history())

    n_opp = upsert(engine, fact_opportunity, opps)
    n_hist = upsert(engine, pipeline_stage_history, hist, update=False)
    print(f"upserted: fact_opportunity {n_opp:,} | pipeline_stage_history {n_hist:,}")

    with engine.connect() as c:
        db_opp = c.execute(select(func.count()).select_from(fact_opportunity)).scalar_one()
        db_hist = c.execute(select(func.count()).select_from(pipeline_stage_history)).scalar_one()
        db_usd = c.execute(select(func.sum(fact_opportunity.c.amount_usd))).scalar_one()

    checks = {
        "opportunity rows == source": db_opp == len(opps),
        "stage-history rows == source": db_hist == len(hist),
        "amount_usd preserved": round(float(db_usd), 2) == round(float(opps["amount_usd"].sum()), 2),
    }
    print(f"\ndb: opportunities {db_opp:,} | stage events {db_hist:,} | pipe ${float(db_usd):,.0f}")
    for name, ok in checks.items():
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    if not all(checks.values()):
        raise SystemExit("Pipeline load reconciliation FAILED.")
    print("\nPipeline loaded. ✅")


if __name__ == "__main__":
    load_all()
