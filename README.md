# ETL Project

An ETL (Extract, Transform, Load) pipeline.

## Status

Scaffolding only. No dependencies installed and no pipeline logic implemented yet.

## Layout

```
etl_project/
├── src/etl/          # Pipeline package
│   ├── extract/      # Data source readers
│   ├── transform/    # Cleaning / reshaping steps
│   └── load/         # Destination writers
├── config/           # Configuration (connections, settings)
├── data/
│   ├── raw/          # Untouched source data
│   └── processed/    # Pipeline output
├── tests/            # Test suite
├── logs/             # Run logs
└── .venv/            # Python virtual environment (not committed)
```

## Getting started

```bash
source .venv/bin/activate
# add dependencies to requirements.txt, then:
# pip install -r requirements.txt
```

## Scheduled jobs — ENABLE ON DEPLOYMENT

The pipeline runs two recurring jobs. They are **not** scheduled automatically —
wire them into cron when deploying:

| Job | Script | Cadence | What it does |
|-----|--------|---------|--------------|
| Fast loop | `scripts/ingest.sh` | every `n` min (see `config/pipeline.yml` → `ingest.interval_minutes`) | pull new API batches from the landing zone and upsert them |
| Nightly loop | `scripts/refresh_active.sh` | nightly | recompute `is_active` / `status` as-of today and write back |

**To enable:** open `scripts/crontab.example`, fill in the schedule and the
absolute repo path, and add the lines via `crontab -e`. Both scripts are
self-locating (activate the venv, set `PYTHONPATH`), so cron can call them by
absolute path from any working directory. Keep the fast-loop cron cadence in sync
with `ingest.interval_minutes`.
