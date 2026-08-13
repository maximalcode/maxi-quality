"""Member code, src layout.

`bs4` from `beautifulsoup4` — the import-name ≠ package-name control, kept here
as well as in samples/deptry so the per-package runs cannot pass by being
trivially empty.
"""

import bs4


def parse(html: str) -> str:
    """Return the document text, so the import is genuinely used."""
    return bs4.BeautifulSoup(html, "html.parser").get_text()
