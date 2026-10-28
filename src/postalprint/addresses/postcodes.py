"""Looks up Danish postcodes (postcode → city) from postnumre.json (next to this module)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

POSTCODES_FILE = Path(__file__).resolve().parent / "postnumre.json"


@lru_cache(maxsize=1)
def load(path: Path = POSTCODES_FILE) -> dict[str, str]:
    """Loads all postcodes once and reuses them afterwards.

    Returns:
        A dict mapping four-digit postcodes to official city names, e.g. {"8700": "Horsens"}.
    """
    return json.loads(path.read_text(encoding="utf-8"))


def lookup(postcode: str) -> str | None:
    """Returns the official city name for ``postcode``, or None if it does not exist."""
    return load().get(postcode.strip())
