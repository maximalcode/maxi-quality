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

Reads Semgrep JSON, emits Markdown. Deliberately does no network I/O — the
workflow does the GitHub side, so this stays unit-testable with a fixture.
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


def load_findings(path: str) -> collections.Counter[str]:
    with open(path) as fh:
        data = json.load(fh)
    return collections.Counter(
        r["check_id"].split(".")[-1] for r in data.get("results", [])
    )


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


def build(counts, date, gitleaks, osv, previous, target, licenses="not run", sbom=None) -> str:
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
        f"## Current — {date}",
        "",
        "| Tool | Result |",
        "|---|---|",
        f"| Semgrep | **{total}** findings |",
        f"| Gitleaks | {gitleaks} |",
        f"| OSV-Scanner | {osv} |",
        f"| Licenses | {licenses} |",
        "",
    ]

    if counts:
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
    history[date] = f"| {date} | {total} | {top_txt} |"
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

    print(
        build(
            load_findings(args.json),
            args.date,
            args.gitleaks,
            args.osv,
            previous_history(body),
            args.target,
            args.licenses,
            load_sbom(args.sbom),
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
