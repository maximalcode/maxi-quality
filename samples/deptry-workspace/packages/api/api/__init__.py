"""Member code. Imports exactly what THIS package's manifest declares."""

import requests


def fetch(url: str) -> int:
    """Return the status code, so the import is genuinely used."""
    return requests.get(url, timeout=5).status_code
