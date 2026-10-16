"""Load (L) layer — the Postgres star schema, defined in SQLAlchemy Core.

Keeping the schema in Python (not a loose .sql file) means the loader references
these exact typed Table objects, so column names/types can never drift between
"what we created" and "what we insert into".

Grain:
  dim_company      one row per COMPANY (Model 2: normalised base name + region)
  fact_contracts   one row per CONTRACT (the measures); company_id -> dim_company
  map_customer     one row per source customer id -> company (match audit + the
                   manual-review hook)

FKs enforce referential integrity: a contract/mapping can only point at a company
that exists in dim_company (company_id is nullable for the 11 un-placeable C-only).
"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Engine,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    PrimaryKeyConstraint,
    Table,
    Text,
)

metadata = MetaData()

MONEY = Numeric(18, 6)  # preserves FX-converted decimals; exact (not float)

dim_company = Table(
    "dim_company",
    metadata,
    Column("company_id", Text, primary_key=True),      # e.g. "inland systems|NA"
    Column("company_name", Text, nullable=False),      # e.g. "Inland Systems (NA)"
    Column("region", Text),
    Column("needs_review", Boolean, nullable=False, server_default="false"),
    Column("n_legal_entities", Integer, nullable=False, server_default="1"),
)

fact_contracts = Table(
    "fact_contracts",
    metadata,
    # --- identity / dimensions ---
    Column("contract_id", Text, nullable=False),
    Column("product", Text, nullable=False),
    Column("product_subtype", Text),
    Column("customer_id", Text),
    Column("customer_name", Text),
    Column("region", Text),
    # --- dates ---
    Column("booking_date", Date),
    Column("start_date", Date),
    Column("end_date", Date),
    Column("cancel_date", Date),
    # --- measures ---
    Column("seats", Integer),
    Column("currency_orig", Text),
    Column("value_orig", MONEY),
    Column("booking_value_usd", MONEY),
    Column("arr_usd", MONEY),
    # --- classification / provenance ---
    Column("revenue_type", Text),
    Column("status", Text),                 # as stated by source (B only); else NULL
    Column("is_active", Boolean),           # as stated by source (B only); else NULL
    Column("is_renewal", Boolean),
    Column("is_renewal_inferred", Boolean),
    Column("booking_date_inferred", Boolean),
    Column("source_file", Text),
    Column("loaded_at", DateTime(timezone=True)),
    # --- star join ---
    Column("company_id", Text, ForeignKey("dim_company.company_id")),
    PrimaryKeyConstraint("product", "contract_id", name="pk_fact_contracts"),
)

map_customer = Table(
    "map_customer",
    metadata,
    Column("source", Text, nullable=False),            # A / B / C
    Column("source_customer_id", Text, nullable=False),
    Column("customer_name", Text),
    Column("region", Text),
    Column("company_id", Text, ForeignKey("dim_company.company_id")),
    Column("company_name", Text),
    Column("match_method", Text, nullable=False),      # exact / fuzzy / id_join / ...
    Column("match_score", Numeric(5, 1)),
    Column("needs_review", Boolean, nullable=False, server_default="false"),
    Column("company_legal_entities", Integer),
    PrimaryKeyConstraint("source", "source_customer_id", name="pk_map_customer"),
)

# Indexes for the queries the metrics layer will run.
Index("ix_fact_company", fact_contracts.c.company_id)
Index("ix_fact_booking_date", fact_contracts.c.booking_date)
Index("ix_fact_revenue_type", fact_contracts.c.revenue_type)


def create_schema(engine: Engine, drop: bool = False) -> None:
    """Create all tables (optionally dropping them first for a clean rebuild)."""
    if drop:
        metadata.drop_all(engine)
    metadata.create_all(engine)


if __name__ == "__main__":
    from etl.load.db import get_engine

    engine = get_engine()
    create_schema(engine, drop=True)
    print("Schema created. Tables:")
    for t in metadata.sorted_tables:
        print(f"  - {t.name} ({len(t.columns)} cols)")
