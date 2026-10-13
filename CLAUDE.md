# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Project

An ETL (Extract, Transform, Load) pipeline. Currently scaffolding only — no
dependencies installed and no pipeline logic written yet.

## Environment

- Python 3.12, virtual environment at `.venv/`.
- Activate with `source .venv/bin/activate` before running anything.
- Dependencies live in `requirements.txt` (currently empty). Install with
  `pip install -r requirements.txt`.

## Layout

- `src/etl/extract/` — read from data sources.
- `src/etl/transform/` — clean / reshape data.
- `src/etl/load/` — write to destinations.
- `config/` — configuration and connection settings.
- `data/raw/`, `data/processed/` — input and output data (git-ignored).
- `tests/` — test suite.
- `logs/` — run logs (git-ignored).

## Conventions

- Keep secrets in `.env` (git-ignored); see `.env.example`.
- Add new runtime packages to `requirements.txt`, don't install ad hoc.

## Notes

(Add project-specific context, decisions, and gotchas here as the pipeline grows.)
