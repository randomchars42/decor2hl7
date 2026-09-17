"""Small text helpers shared by setup-time matching passes."""

from __future__ import annotations

import re
import unicodedata


def normalize_match_text(value: str) -> str:
    """Return an accent- and punctuation-insensitive matching key."""
    ascii_value = (
        unicodedata.normalize("NFKD", value)
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    return re.sub(r"[^a-z0-9]+", "", ascii_value.casefold())
