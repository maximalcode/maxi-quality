"""THE ABLATION FOR ruff's `line-length = 100`.

Formatted correctly under configs/python/ruff.toml and incorrectly under ruff's
own default of 88, with line length the only setting separating the two
verdicts.

The return statement below is 95 characters wide: one line at our 100, split
across several at ruff's default 88. `bad_format.py` cannot prove this on its
own — ruff's defaults reject that file too, so it stays red even if
configs/python/ruff.toml is deleted.

Keep the long line between 89 and 100 characters or the ablation stops
separating anything.
"""


def describe_endpoint(name: str, port: int, secure: bool) -> str:
    return format_endpoint_description(name, port, secure, "the width is the entire point")


def format_endpoint_description(name: str, port: int, secure: bool, note: str) -> str:
    scheme = "https" if secure else "http"
    return f"{name}:{port} {scheme} — {note}"
