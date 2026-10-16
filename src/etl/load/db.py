"""Load (L) layer — the one place that builds the database connection.

12-factor: the connection comes from DATABASE_URL in the environment — loaded from
.env in local dev, injected directly by Docker in deployment. The same code runs
unchanged in both. Everything that talks to Postgres imports get_engine() here, so
there is a single pooled engine per process and one place to change connection logic.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import Engine, create_engine, text

# Load .env from the project root if present. No-op when the vars are already in
# the environment (e.g. inside a container), so Docker never needs the file.
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(_PROJECT_ROOT / ".env")


def database_url() -> str:
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. Copy .env.example to .env (local dev), "
            "or inject it into the environment (Docker)."
        )
    return url


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Return a process-wide SQLAlchemy engine (connection-pooled, created once).

    pool_pre_ping checks a connection is alive before handing it out, so a
    container restart or idle timeout doesn't surface as a stale-connection error.
    """
    return create_engine(database_url(), pool_pre_ping=True, future=True)


def ping() -> bool:
    """True if the database answers a trivial query."""
    with get_engine().connect() as conn:
        return conn.execute(text("SELECT 1")).scalar_one() == 1


if __name__ == "__main__":
    eng = get_engine()
    print(f"engine: {eng.url.render_as_string(hide_password=True)}")
    with eng.connect() as conn:
        version = conn.execute(text("SELECT version()")).scalar_one()
        db = conn.execute(text("SELECT current_database()")).scalar_one()
        who = conn.execute(text("SELECT current_user")).scalar_one()
    print(f"connected: db={db}  user={who}")
    print(f"server: {version.split(',')[0]}")
    print("ping:", "OK ✅" if ping() else "FAILED")
