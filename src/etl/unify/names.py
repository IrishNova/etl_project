"""Company-name normalization for cross-source customer matching (L3).

Lowercases, strips punctuation, and removes legal-entity suffixes so that
near-identical names collapse to a comparable key. Deliberately conservative:
it standardises formatting but does NOT merge distinct base names — that job is
left to region disambiguation and (later) fuzzy scoring + review.
"""

from __future__ import annotations

import re

# Legal-entity suffixes to strip. These carry region signal (GmbH≈EU, Ltd≈UK),
# which is why matching also keys on region — the suffix alone must not merge
# "Cascade Tooling GmbH" (EU) with "Cascade Tooling Corp" (NA).
LEGAL_SUFFIXES = {
    "corp", "corporation", "inc", "incorporated", "llc", "ltd", "limited",
    "gmbh", "co", "company", "plc", "lp", "llp", "ag", "sa", "bv",
}


def normalize_name(name: str) -> str:
    """'Cascade Aerospace Corp.' -> 'cascade aerospace'. Non-strings -> ''."""
    if not isinstance(name, str):
        return ""
    s = re.sub(r"[^a-z0-9\s]", " ", name.lower())
    tokens = [t for t in s.split() if t not in LEGAL_SUFFIXES]
    return " ".join(tokens).strip()
