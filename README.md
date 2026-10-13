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
