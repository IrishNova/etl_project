"""Pipeline configuration (non-secret operational settings from config/pipeline.yml).

Secrets stay in .env (loaded in etl.load.db); this is the knobs an operator tunes:
ingest cadence, landing-zone paths, the active-refresh schedule. Paths returned by
resolve_path() are absolute, anchored at the project root, so code works regardless
of the current working directory (host or container).
"""

from __future__ import annotations

from pathlib import Path

import yaml

# src/etl/config.py -> parents[2] = project root
PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "config" / "pipeline.yml"


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def resolve_path(rel: str | Path) -> Path:
    """Absolutise a config path against the project root (passthrough if absolute)."""
    p = Path(rel)
    return p if p.is_absolute() else PROJECT_ROOT / p
