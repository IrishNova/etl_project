#!/usr/bin/env bash
# NIGHTLY LOOP — recompute is_active / status (as-of today) and write them back.
# Enable on deployment via cron (see scripts/crontab.example). Self-locating: cron
# can call it by absolute path from any working directory.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# shellcheck disable=SC1091
source .venv/bin/activate
export PYTHONPATH=src

echo "[$(date -Is)] refresh_active: start"
python -m etl.refresh_active
echo "[$(date -Is)] refresh_active: done"
