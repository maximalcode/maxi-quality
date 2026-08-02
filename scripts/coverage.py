#!/usr/bin/env python3
"""Coverage ratchet: compare measured line coverage against a committed floor.

WHY A RATCHET AND NOT A THRESHOLD

A fixed threshold ("must be 80%") is unusable on an existing codebase: it is
either below where you already are, in which case it gates nothing, or above,
in which case every PR is red until someone does a coverage sprint. Both
outcomes end with the number being ignored.

A ratchet asks the only question that is always answerable: *did this change
make it worse?* The floor is whatever the repo already achieves. It may only go
up, and it goes up deliberately — see --write below.

This is the same shape as the Semgrep `--changed-only` adoption gate: grandfather
the backlog, refuse to grow it.

WHERE THE FLOOR LIVES

In a file committed to the consuming repo (default `.maxi-quality/coverage.json`).
Not in a cache (evicted after 7 days — a ratchet that forgets is a threshold of
zero), not in a repository variable (the default GITHUB_TOKEN cannot write one),
and not in the standing report issue (a PR from a fork cannot read-modify-write
it, and two concurrent PRs would race).

A committed file is boring, diffable, and shows up in review — when the floor
moves, someone sees it move.

WHAT IS MEASURED

Line coverage only, deliberately. Branch coverage is reported inconsistently
across lcov and Cobertura producers, and a ratchet built on a number that two
tools disagree about will fire on tool upgrades rather than on real regressions.

Reads lcov and Cobertura. Does no network I/O and never writes unless asked.

Exit codes: 0 at or above the floor · 1 coverage dropped · 3 usage/parse error
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET

DEFAULT_FLOOR_FILE = ".maxi-quality/coverage.json"


class ParseError(Exception):
    pass


def parse_lcov(text: str) -> tuple[int, int]:
    """Return (lines_found, lines_hit) from an lcov tracefile.

    Prefers the per-record LF:/LH: summary lines over counting DA: entries.
    Both are present in practice, but a single source file can be emitted more
    than once (one record per test target); the producer's own summary is what
    the producer considers correct, and counting DA: would double-count.
    """
    found = hit = 0
    da_found = da_hit = 0
    saw_lf = False
    for line in text.splitlines():
        if line.startswith("LF:"):
            saw_lf = True
            found += int(line[3:] or 0)
        elif line.startswith("LH:"):
            hit += int(line[3:] or 0)
        elif line.startswith("DA:"):
            # DA:<line>,<hits>[,<checksum>]
            parts = line[3:].split(",")
            if len(parts) >= 2:
                da_found += 1
                if int(parts[1]) > 0:
                    da_hit += 1
    if saw_lf:
        # Including the LF:0 case: an instrumented run that measured nothing is
        # a broken run, and main() has the right words for that.
        return found, hit
    if da_found:
        return da_found, da_hit
    raise ParseError("lcov file has neither LF:/LH: nor DA: records")


def parse_cobertura(root: ET.Element) -> tuple[int, int]:
    """Return (lines_found, lines_hit) from a Cobertura report.

    Prefers the root's lines-valid/lines-covered attributes. Counting <line>
    elements looks more honest but is not: coverlet emits one <class> per TYPE,
    so a file holding two classes lists its lines twice and the count inflates.
    The producer already de-duplicated for the root attributes.
    """
    valid = root.get("lines-valid")
    covered = root.get("lines-covered")
    if valid is not None and covered is not None and int(valid) > 0:
        return int(valid), int(covered)

    found = hit = 0
    for el in root.iter("line"):
        found += 1
        if int(el.get("hits", "0")) > 0:
            hit += 1
    if found:
        return found, hit
    raise ParseError("Cobertura report has no lines-valid attribute and no <line> elements")


def read_report(path: str) -> tuple[int, int]:
    """Detect the format by content, not by filename.

    `coverage.xml`, `cobertura.xml`, `lcov.info` and `coverage.info` are all in
    circulation, and CI configs rename them freely. Sniffing the first bytes is
    the thing that cannot be wrong.
    """
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError as exc:
        raise ParseError(f"cannot read {path}: {exc}") from exc

    if not text.strip():
        raise ParseError(f"{path} is empty")

    if text.lstrip().startswith("<"):
        try:
            root = ET.fromstring(text)
        except ET.ParseError as exc:
            raise ParseError(f"{path} is not valid XML: {exc}") from exc
        if root.tag != "coverage":
            raise ParseError(f"{path} is XML but its root is <{root.tag}>, not <coverage>")
        return parse_cobertura(root)

    return parse_lcov(text)


def read_floor(path: str) -> float | None:
    """None means 'no floor yet' — the first run, which must not fail."""
    try:
        with open(path) as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as exc:
        # A corrupt floor is NOT treated as "no floor". Silently restarting the
        # ratchet from the current number is how a ratchet dies quietly.
        raise ParseError(f"floor file {path} is unreadable: {exc}") from exc
    try:
        return float(data["line"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ParseError(f"floor file {path} has no numeric \"line\" key") from exc


def write_floor(path: str, pct: float) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w") as fh:
        json.dump({"line": round(pct, 2)}, fh, indent=2)
        fh.write("\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--report",
        action="append",
        required=True,
        metavar="FILE",
        help="lcov or Cobertura report. Repeatable; all are summed.",
    )
    ap.add_argument("--floor-file", default=DEFAULT_FLOOR_FILE)
    ap.add_argument(
        "--tolerance",
        type=float,
        default=0.1,
        help="Percentage points of slack below the floor (default 0.1). Small "
        "refactors move the number a hair; a ratchet that fires on that gets "
        "disabled within a week.",
    )
    ap.add_argument(
        "--write",
        action="store_true",
        help="Raise the floor to the measured value when it improved. Never "
        "lowers it — that is the whole point.",
    )
    args = ap.parse_args()

    try:
        totals = [read_report(p) for p in args.report]
        floor = read_floor(args.floor_file)
    except ParseError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3

    found = sum(f for f, _ in totals)
    hit = sum(h for _, h in totals)
    if found == 0:
        print(
            "error: the reports contain 0 measurable lines. That is a broken "
            "coverage run, not 100% coverage — refusing to record a floor.",
            file=sys.stderr,
        )
        return 3

    pct = 100.0 * hit / found

    # stdout is machine-readable (the composite action appends it to
    # $GITHUB_OUTPUT verbatim); prose goes to stderr.
    raised = False
    rc = 0

    if floor is None:
        msg = (
            f"no floor at {args.floor_file} yet — recording {pct:.2f}% as the "
            "starting point" if args.write else
            f"no floor at {args.floor_file} yet — measured {pct:.2f}%. "
            f"Run with --write to record it."
        )
        if args.write:
            write_floor(args.floor_file, pct)
            raised = True
    elif pct < floor - args.tolerance:
        msg = (
            f"coverage DROPPED: {pct:.2f}% is below the floor of {floor:.2f}% "
            f"(tolerance {args.tolerance}pp). Add tests for what this change "
            f"touched, or explain why the floor should move down."
        )
        rc = 1
    elif pct > floor + args.tolerance:
        msg = f"coverage ROSE: {pct:.2f}% (floor {floor:.2f}%)"
        if args.write:
            write_floor(args.floor_file, pct)
            raised = True
            msg += f" — floor raised, commit {args.floor_file}"
        else:
            msg += f" — the floor can be raised to {pct:.2f}%"
    else:
        msg = f"coverage held at {pct:.2f}% (floor {floor:.2f}%)"

    print(f"coverage={pct:.2f}")
    print(f"floor={floor if floor is not None else pct:.2f}")
    print(f"lines_hit={hit}")
    print(f"lines_found={found}")
    print(f"raised={'true' if raised else 'false'}")
    print(f"status={'drop' if rc else 'ok'}")
    print(msg, file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main())
