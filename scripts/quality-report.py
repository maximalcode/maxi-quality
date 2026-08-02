#!/usr/bin/env python3
"""Build the Markdown body of a repo's standing quality-report issue.

WHY A GITHUB ISSUE IS THE DATABASE

This baseline has no server and no cloud by design (zero spend is a success
criterion, not a preference). But a gate has no memory: `quality.yml` answers
"is this PR clean?" and nothing answers "what is still wrong from before?".
SonarQube's real advantage over this setup was never detection — it was that
it kept state. See docs/EVAL-vs-sonarqube.md.

GitHub code scanning would be the better store, but on a private repo owned by
a personal account it needs Advanced Security, which is the paid path. So the
store is a single GitHub issue, updated in place: the body holds the current
breakdown, and a history table that grows one row per run. Free, no infra, and
the trend lives where the work already is.

ONE issue, updated forever — never a new issue per run. A weekly bot that opens
issues is noise, and noise gets muted, and a muted report is worse than none.

A SCAN THAT BROKE IS NOT A SCAN THAT FOUND NOTHING

Semgrep reports a run that failed to load a rule, or crashed part-way, as
`results: []` with the reason in `.errors` — so reading only `.results` rendered
`| Semgrep | **0** findings |` and wrote a `0` into the history table, where it
is preserved forever. The reassuring answer was the wrong one, and the table
that exists to show a trend recorded an outage as an achievement. So `.errors`
and `.paths.scanned` are read too, an errored run renders as ERRORED, and the
script exits 2 — after printing the body, so the issue still shows what happened
rather than the workflow dying with the news.

Reads Semgrep JSON, emits Markdown. Deliberately does no network I/O — the
workflow does the GitHub side, so this stays unit-testable with a fixture.

Exit codes: 0 rendered · 2 rendered, but the scan had ERRORED · 3 the results
file could not be read at all (nothing is printed, so nothing overwrites the
standing issue)
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import sys

MARKER = "<!-- maxi-quality:report -->"
HISTORY_HEADING = "## History"
# A row looks like: | 2026-08-01 | 68 | no-ambient-clock (63) |
HISTORY_ROW = re.compile(r"^\|\s*(\d{4}-\d{2}-\d{2})\s*\|.*\|$", re.M)
# Keep the table readable rather than unbounded; the issue is a dashboard, not
# an audit log. Old rows fall off the bottom.
MAX_HISTORY = 52


def load_sbom(path: str | None) -> tuple[int, collections.Counter[str]] | None:
    """Return (component count, license histogram) from a CycloneDX 1.6 SBOM.

    CycloneDX spells a license three different ways and all three are in the
    wild: an SPDX id, a free-text name, or an expression ("MIT OR Apache-2.0").
    A component with none of them is genuinely unknown, which is worth counting
    rather than dropping — an unlicensed dependency is the one you actually
    need to hear about.
    """
    if not path:
        return None
    try:
        with open(path) as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        # The SBOM is an extra, not the point of the report. A missing or
        # malformed one must not cost the repo its Semgrep history.
        return None

    counts: collections.Counter[str] = collections.Counter()
    components = data.get("components", [])
    for comp in components:
        entries = comp.get("licenses") or []
        names = []
        for entry in entries:
            if "expression" in entry:
                names.append(entry["expression"])
            elif isinstance(entry.get("license"), dict):
                lic = entry["license"]
                name = lic.get("id") or lic.get("name")
                if name:
                    names.append(name)
        counts[" / ".join(sorted(set(names))) if names else "UNKNOWN"] += 1
    return len(components), counts


def _first_error(errors: list) -> str:
    """Semgrep's `.errors` entries are objects, but not reliably so across
    versions — and a report that crashes while explaining a crash is useless.

    The result lands inside a Markdown table cell, so a newline or a bare pipe
    from a tool's error text would break the table it is being reported in.
    """
    first = errors[0]
    if isinstance(first, dict):
        text = str(first.get("long_msg") or first.get("message") or first.get("type") or first)
    else:
        text = str(first)
    text = " ".join(text.split()).replace("|", "\\|")
    return text[:197] + "..." if len(text) > 200 else text


def load_findings(path: str) -> tuple[collections.Counter[str], str | None]:
    """Return (counts, reason-this-is-not-a-finding-set).

    The second element is what stops a broken run from rendering as a clean one.
    Two shapes reach here as `results: []`:

      - `.errors` is populated — a rule failed to parse, a target could not be
        read, semgrep aborted. It scanned some or none of the tree and does not
        know what it missed.
      - `.paths.scanned` is empty — it ran to completion over nothing at all,
        which on a full-repo report means the target was wrong, not that the
        repo is empty. (`.paths` absent entirely is an older/leaner output and
        is NOT treated as an error; only an explicit empty list is.)
    """
    with open(path) as fh:
        data = json.load(fh)

    errors = data.get("errors") or []
    if errors:
        return collections.Counter(), f"semgrep reported {len(errors)} error(s): {_first_error(errors)}"

    scanned = (data.get("paths") or {}).get("scanned")
    if scanned is not None and len(scanned) == 0:
        return collections.Counter(), "semgrep scanned 0 files"

    counts = collections.Counter(
        r["check_id"].split(".")[-1] for r in data.get("results", [])
    )
    return counts, None


def previous_history(body: str | None) -> dict[str, str]:
    """Pull the existing history rows out of the last issue body, keyed by date.

    The issue body IS the persistence layer, so this is the read half of it. A
    parse failure must never wipe history — on anything unexpected we return
    what we could find rather than starting over.

    Returns a date -> row mapping rather than a list, which fixes two bugs that
    a real consumer run surfaced:

      - The rendered table is NEWEST-FIRST, so the rows come back in reverse
        chronological order. Treating that list as chronological and reversing
        it again scrambled everything from the third run onward: four runs
        rendered 22, 08, 01, 15. Keying by date and sorting removes the
        assumption entirely.
      - Two runs on the same day appended two identical rows. The history is a
        daily series; one row per date, last write wins.
    """
    if not body or HISTORY_HEADING not in body:
        return {}
    tail = body.split(HISTORY_HEADING, 1)[1]
    return {m.group(1): m.group(0) for m in HISTORY_ROW.finditer(tail)}


def build(counts, date, gitleaks, osv, previous, target, licenses="not run",
          sbom=None, scan_error=None) -> str:
    total = sum(counts.values())
    top = counts.most_common(1)[0] if counts else None
    top_txt = f"{top[0]} ({top[1]})" if top else "—"

    lines = [
        MARKER,
        f"# Quality backlog — `{target}`",
        "",
        "Standing report from the [maxi-quality]"
        "(https://github.com/maximalcode/maxi-quality) baseline. "
        "**Updated in place — do not close.**",
        "",
        "PRs are gated on *new* findings only (the ratchet). This is the other "
        "half: everything already here. A number that stops falling is the "
        "signal worth acting on.",
        "",
    ]

    if scan_error:
        lines += [
            f"> ⚠️ **The Semgrep scan for {date} ERRORED and produced no usable "
            f"result: {scan_error}**",
            ">",
            "> Nothing was measured. This is not a clean repo — it is a repo "
            "nobody looked at. The history table below still holds the last runs "
            "that worked; fix the scan and re-run before reading a trend into it.",
            "",
        ]

    semgrep_cell = f"**ERRORED** — {scan_error}" if scan_error else f"**{total}** findings"
    lines += [
        f"## Current — {date}",
        "",
        "| Tool | Result |",
        "|---|---|",
        f"| Semgrep | {semgrep_cell} |",
        f"| Gitleaks | {gitleaks} |",
        f"| OSV-Scanner | {osv} |",
        f"| Licenses | {licenses} |",
        "",
    ]

    if scan_error:
        # NOT "No Semgrep findings." — that sentence is the bug in prose form.
        lines.append("No Semgrep breakdown: the scan did not complete. ")
    elif counts:
        lines += ["### Semgrep by rule", "", "| Rule | Count |", "|---|---:|"]
        lines += [f"| `{rule}` | {n} |" for rule, n in counts.most_common()]
    else:
        lines.append("No Semgrep findings. ")
    lines.append("")

    if sbom:
        n_components, license_counts = sbom
        unknown = license_counts.get("UNKNOWN", 0)
        lines += [
            "## Dependencies",
            "",
            f"{n_components} resolved components (CycloneDX 1.6 SBOM attached to "
            "the run that produced this report).",
            "",
            "| License | Components |",
            "|---|---:|",
        ]
        lines += [f"| `{lic}` | {n} |" for lic, n in license_counts.most_common()]
        if unknown:
            lines += [
                "",
                f"{unknown} component(s) declare no license. That is the row "
                "worth reading — first-party workspace packages land here too, "
                "so check which before treating it as a risk.",
            ]
        lines.append("")

    # Sort by the ISO date rather than trusting the order rows arrived in —
    # they are read back from a newest-first table, and every ordering bug here
    # has come from assuming otherwise.
    history = dict(previous)
    # An errored run gets a row, and the row says so. Skipping it would hide the
    # outage; writing `0` would record it as the best week the repo ever had and
    # then preserve that forever, since this table is the only store there is.
    history[date] = (
        f"| {date} | ERRORED | — |" if scan_error
        else f"| {date} | {total} | {top_txt} |"
    )
    rows = [history[d] for d in sorted(history)][-MAX_HISTORY:]
    rows.reverse()  # newest first, which is what a reader wants on top

    lines += [
        HISTORY_HEADING,
        "",
        "| Date | Semgrep total | Largest rule |",
        "|---|---:|---|",
        *rows,
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", required=True, help="Semgrep --json-out file")
    ap.add_argument("--date", required=True)
    ap.add_argument("--target", default="repository")
    ap.add_argument("--gitleaks", default="not run")
    ap.add_argument("--osv", default="not run")
    ap.add_argument("--licenses", default="not run")
    ap.add_argument("--sbom", help="CycloneDX 1.6 SBOM (optional)")
    ap.add_argument("--previous-body", help="File holding the current issue body")
    args = ap.parse_args()

    body = None
    if args.previous_body:
        try:
            with open(args.previous_body) as fh:
                body = fh.read()
        except OSError:
            # First run, or the file was not produced. Not an error: it just
            # means there is no history yet.
            body = None

    try:
        counts, scan_error = load_findings(args.json)
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        # Nothing is printed on this path, deliberately: the caller writes
        # stdout over the standing issue, and an empty body would erase the
        # history this script exists to keep.
        print(f"error: cannot read Semgrep results from {args.json}: {exc}", file=sys.stderr)
        return 3

    print(
        build(
            counts,
            args.date,
            args.gitleaks,
            args.osv,
            previous_history(body),
            args.target,
            args.licenses,
            load_sbom(args.sbom),
            scan_error,
        )
    )
    if scan_error:
        # Body first, THEN the failure. The issue has to show the outage; the
        # exit code is what makes the run red so somebody looks.
        print(f"error: {scan_error} — reported as ERRORED, not as a clean scan", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
