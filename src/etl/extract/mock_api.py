"""Mock API extract — stand-in for pulling new data from the product APIs.

In production this would be an authenticated HTTP call to each ERP/CRM API,
returning records changed since the last watermark. Here a (simulated) poller has
already dropped the API response as a batch file into the landing zone, and we read
it. The downstream contract is identical either way: raw text records in -> DataFrame
out, same shape the batch transform expects.

Watermark: a file sitting in the landing zone = not yet ingested. After a successful
load, archive_batch() moves it to the archive zone, so it is never processed twice.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pandas as pd

from etl.config import load_config, resolve_path


def iter_incoming_batches(product: str = "B") -> Iterator[tuple[Path, pd.DataFrame]]:
    """Yield (path, raw_df) for each un-ingested batch file for a product.

    Read as all-text (dtype=str, no NA coercion) so the batch transform sees exactly
    what it sees for the seed file — region "NA" stays "NA", blanks stay "".
    """
    cfg = load_config()
    zone = resolve_path(cfg["ingest"]["landing_zone"])
    zone.mkdir(parents=True, exist_ok=True)
    for path in sorted(zone.glob(f"product_{product.lower()}_*.csv")):
        raw = pd.read_csv(path, dtype=str, keep_default_na=False, na_values=[])
        yield path, raw


def archive_batch(path: Path) -> Path:
    """Move an ingested batch out of the landing zone (advances the watermark)."""
    cfg = load_config()
    archive = resolve_path(cfg["ingest"]["archive_zone"])
    archive.mkdir(parents=True, exist_ok=True)
    dest = archive / path.name
    path.rename(dest)
    return dest
