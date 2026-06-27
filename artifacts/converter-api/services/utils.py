"""
Shared utility helpers for the converter pipeline.

Centralises _str / _bool / _float / _int / _is_url so every module imports
from a single location instead of duplicating the logic.
"""
from __future__ import annotations

import re
import pandas as pd


def _str(val: object) -> str:
    """Convert any value to a stripped string; NaN/None → empty string."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    return str(val).strip()


def _bool(val: object) -> bool:
    """Parse a Shopify boolean column value (true/yes/1 → True)."""
    return _str(val).lower() in ("true", "yes", "1")


def _float(val: object, default: float = 0.0) -> float:
    """Parse a float; return *default* on empty or non-numeric input."""
    s = _str(val)
    if not s:
        return default
    try:
        return float(s)
    except ValueError:
        return default


def _int(val: object, default: int = 0) -> int:
    """Parse an int (via float to handle '5.0'); return *default* on failure."""
    s = _str(val)
    if not s:
        return default
    try:
        return int(float(s))
    except ValueError:
        return default


def _is_url(s: str) -> bool:
    """Return True if *s* looks like an absolute HTTP(S) URL."""
    return s.startswith("http://") or s.startswith("https://")


def _has_malformed_html(html: str) -> bool:
    """
    Detect obvious HTML malformation patterns without relying on BeautifulSoup
    (which silently repairs rather than raising exceptions).

    Checks:
    - Unclosed angle bracket on a line (tag opened but never closed).
    - Bare & not followed by a valid XML/HTML entity reference.
    """
    if not html:
        return False
    if re.search(r"<[^>]*$", html, re.MULTILINE):
        return True
    if re.search(r"&(?!(?:#\d+|#x[\da-fA-F]+|[a-zA-Z]\w{0,30});)", html):
        return True
    return False
