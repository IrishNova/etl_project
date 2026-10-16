#!/usr/bin/env bash
# FAST LOOP — pull new batches from the (mock) product APIs and upsert them.
# Enable on deployment via cron (see scripts/crontab.example). Self-locating: cron
# can call it by absolute path from any working directory.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# shellcheck disable=SC1091
source .venv/bin/activate
export PYTHONPATH=src

echo "[$(date -Is)] ingest: start"
python -m etl.ingest_incremental
echo "[$(date -Is)] ingest: done"
