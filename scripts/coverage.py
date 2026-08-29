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

AND IT HAS TO EXIST. Recording the first floor is a deliberate act (--write),
so a repo that never performs it has a ratchet comparing against nothing and
reporting ok at any coverage at all. That was the DOCUMENTED setup: the action
defaults raise:false and the README snippet did not override it. --require-floor
turns that state into an error instead of a permanent pass, and the composite
action always passes it.

WHAT IS MEASURED

Line coverage only, deliberately. Branch coverage is reported inconsistently
across lcov and Cobertura producers, and a ratchet built on a number that two
tools disagree about will fire on tool upgrades rather than on real regressions.

PATCH COVERAGE (--diff-file)

The ratchet asks whether the AGGREGATE got worse, and a PR that adds one
untested function to a well-covered repo does not make it worse: four uncovered
lines against 8,000 measured ones move the number by 0.05pp, which is inside the
ratchet's own tolerance. `samples/coverage/patch` is exactly that change, and
the ratchet reports `ok` on it.

The number that would have said something is coverage of the CHANGED lines, and
it needs no new data — the reports already carry per-line hits, and a unified
diff already carries the added-line ranges. Intersecting the two is the whole
computation.

Zero measurable changed lines is NOT 100% and not 0%, it is `n/a`. A docs-only
PR reporting 0% gates on nothing anyone can fix; one reporting 100% gates on a
lie. Both are how a patch gate gets switched off in week two.

`--diff-file` alone only MEASURES. Gating it is `--patch-threshold`, below.

GATING THE PATCH NUMBER (--patch-threshold)

`--patch-threshold N` fails the run when coverage of the added lines is below N
percent. It needs `--diff-file`: a threshold with no diff would gate nothing
while looking like a gate.

WHY A FIXED THRESHOLD HERE, WHEN THE AGGREGATE GETS A RATCHET

Read the ratchet argument at the top again before assuming this contradicts it.
That argument is about an EXISTING codebase: a fixed bar there is either below
where the repo already sits, gating nothing, or above it, and every PR is red
until someone runs a coverage sprint.

Neither failure mode exists for changed lines. Lines a PR just added have no
backlog to grandfather and no history to be unfair about — the author is
writing them right now, and "test what you just wrote" is answerable on every
PR, including the first one. The two numbers get two different shapes on
purpose. It is the same argument, applied where it points the other way.

The default bar is 50, not 100. At 100 every defensive guard and every
unreachable branch is a blocker, and a gate that cannot be satisfied honestly
gets satisfied dishonestly. `0` switches the gate off and keeps the number.

NOT APPLICABLE IS NOT A FAILURE. A diff with no measurable added lines cannot
be below any bar. It reports n/a and exits 0 — see the paragraph above.

Reads lcov and Cobertura. Does no network I/O and never writes unless asked.

Exit codes: 0 every gate passed · 1 a gate failed (the aggregate dropped, or
the patch number is below the bar) · 3 usage/parse error
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET
from typing import NamedTuple

DEFAULT_FLOOR_FILE = ".maxi-quality/coverage.json"


class ParseError(Exception):
    pass


class Report(NamedTuple):
    """One parsed coverage report.

    `lines` is the per-file hit map: {source path: {line number: hits}}. The
    ratchet has never needed it — `found`/`hit` are the producer's own totals
    and are what the floor compares against. Patch coverage needs nothing else.
    """

    found: int
    hit: int
    lines: dict[str, dict[int, int]]


def normalise_path(path: str) -> str:
    """Windows separators and `./` prefixes are noise, not identity."""
    path = path.replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    return path


def path_parts(path: str) -> list[str]:
    return [part for part in path.split("/") if part not in ("", ".")]


def parse_lcov(text: str) -> Report:
    """Return the totals and the per-file hit map from an lcov tracefile.

    Prefers the per-record LF:/LH: summary lines over counting DA: entries.
    Both are present in practice, but a single source file can be emitted more
    than once (one record per test target); the producer's own summary is what
    the producer considers correct, and counting DA: would double-count.

    The per-file map SUMS repeated DA: entries for the same line, which is the
    same de-duplication seen from the other side: a line executed by any test
    target is covered, however many targets reported it.
    """
    found = hit = 0
    da_found = da_hit = 0
    saw_lf = False
    lines: dict[str, dict[int, int]] = {}
    current: dict[int, int] | None = None
    for line in text.splitlines():
        if line.startswith("SF:"):
            current = lines.setdefault(normalise_path(line[3:].strip()), {})
        elif line.startswith("LF:"):
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
                if current is not None:
                    number = int(parts[0])
                    current[number] = current.get(number, 0) + int(parts[1])
        elif line.startswith("end_of_record"):
            current = None
    if saw_lf:
        # Including the LF:0 case: an instrumented run that measured nothing is
        # a broken run, and main() has the right words for that.
        return Report(found, hit, lines)
    if da_found:
        return Report(da_found, da_hit, lines)
    raise ParseError("lcov file has neither LF:/LH: nor DA: records")


def parse_cobertura(root: ET.Element) -> Report:
    """Return the totals and the per-file hit map from a Cobertura report.

    Prefers the root's lines-valid/lines-covered attributes. Counting <line>
    elements looks more honest but is not: coverlet emits one <class> per TYPE,
    so a file holding two classes lists its lines twice and the count inflates.
    The producer already de-duplicated for the root attributes.

    That same duplication is why the per-file map keeps the HIGHEST hit count
    for a line rather than the last one parsed. A line listed under two <class>
    entries for one file — or once under <class> and again under <method> — is
    covered if either says so; taking the last would let element order decide
    whether a line is a finding.
    """
    lines: dict[str, dict[int, int]] = {}
    for cls in root.iter("class"):
        filename = cls.get("filename")
        if not filename:
            continue
        per_file = lines.setdefault(normalise_path(filename), {})
        for el in cls.iter("line"):
            number = el.get("number")
            if number is None:
                continue
            hits = int(el.get("hits", "0"))
            key = int(number)
            per_file[key] = max(per_file.get(key, 0), hits)

    valid = root.get("lines-valid")
    covered = root.get("lines-covered")
    if valid is not None and covered is not None and int(valid) > 0:
        return Report(int(valid), int(covered), lines)

    found = hit = 0
    for el in root.iter("line"):
        found += 1
        if int(el.get("hits", "0")) > 0:
            hit += 1
    if found:
        return Report(found, hit, lines)
    raise ParseError("Cobertura report has no lines-valid attribute and no <line> elements")


def read_report(path: str) -> Report:
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


class PatchResult(NamedTuple):
    """Changed lines, intersected with what the reports measured."""

    found: int
    hit: int
    unmeasured: list[str]
    # {path: uncovered added line numbers}. The gate has to name the lines to
    # write a test for; "patch coverage 43%" alone is an unactionable red X.
    misses: dict[str, list[int]]


def parse_diff(text: str) -> dict[str, set[int]]:
    """Return {path: added line numbers} from a unified diff.

    ADDED lines only. A deleted line has nothing left to measure, and a context
    line was not written by this change — "is the code this PR adds tested?" is
    the question, and everything it did not touch is backlog. Same
    grandfathering rule as Semgrep's --changed-only.

    Paths come from the `+++` side, because that is the file the added lines
    live in: a rename writes `--- a/old` and `+++ b/new`, and the new path is
    the one the coverage report knows. `+++ /dev/null` is a deletion and
    contributes nothing.

    Hunk lengths are TRACKED, not skipped past, because a unified diff is
    ambiguous without them: a change that adds the line `++ x` emits `+++ x`,
    which is indistinguishable from a file header by prefix alone. Inside a
    hunk the declared counts say how many lines are body, so the header can
    only be read where a header can occur. The counts are then asserted — a
    hunk that does not contain what it declared is a truncated or hand-edited
    diff, and the added lines it is missing would otherwise be silently
    unmeasured, which is the failure mode of reporting a number at all.

    Git's default a/ b/ prefixes are stripped, and `--no-prefix` diffs parse
    too. What does not parse is a combined diff (`@@@`, from a merge commit):
    its two prefix columns mean a different grammar, and it fails loudly here
    rather than being half-read.
    """
    changed: dict[str, set[int]] = {}
    current: set[int] | None = None
    number = 0
    old_left = new_left = 0

    def end_of_hunk(header: str) -> None:
        if old_left or new_left:
            raise ParseError(
                f"hunk ended {old_left + new_left} line(s) short of what its "
                f"header declared, at: {header.strip() or '<end of diff>'}"
            )

    for line in text.splitlines():
        if old_left or new_left:
            # Inside a hunk: the counts decide what these lines are, not their
            # first character.
            if line.startswith("+"):
                if current is not None:
                    current.add(number)
                number += 1
                new_left -= 1
            elif line.startswith("-"):
                old_left -= 1
            elif line.startswith("\\"):
                continue  # "\ No newline at end of file" is not a line
            else:
                # Context. An empty line is one whose single leading space some
                # producers strip.
                number += 1
                old_left -= 1
                new_left -= 1
            continue

        if line.startswith("+++ "):
            end_of_hunk(line)
            path = line[4:].split("\t")[0].strip()
            if path == "/dev/null":
                current = None
                continue
            if path.startswith("b/"):
                path = path[2:]
            current = changed.setdefault(normalise_path(path), set())
        elif line.startswith("@@"):
            # @@ -<old start>[,<len>] +<new start>[,<len>] @@ [section heading]
            fields = line.split()
            if line.startswith("@@@") or len(fields) < 3 or not fields[2].startswith("+"):
                raise ParseError(f"unparseable hunk header: {line}")
            try:
                number, new_left = _hunk_range(fields[2])
                _, old_left = _hunk_range(fields[1])
            except ValueError as exc:
                raise ParseError(f"unparseable hunk header: {line}") from exc
            # A hunk that declares zero lines on both sides adds nothing.

    end_of_hunk("")
    # A file whose hunks removed lines only has nothing to measure and must not
    # be reported as an unmeasured file — that reads as a coverage hole.
    return {path: numbers for path, numbers in changed.items() if numbers}


def _hunk_range(field: str) -> tuple[int, int]:
    """`+12,7` -> (12, 7); `+12` -> (12, 1), which is what omitting the length means."""
    start, _, length = field[1:].partition(",")
    return int(start), int(length) if length else 1


def match_report_path(diff_path: str, measured: dict[str, dict[int, int]]) -> str | None:
    """Which report entry measures this changed file — or None if that is not
    answerable.

    The two sides name the same file differently and always have. `git diff`
    emits repo-relative paths; coverage producers emit whatever their working
    directory was — absolute paths from coverlet, `src/`-relative paths from a
    monorepo package, forward or backward slashes. Requiring equality would
    report every file as unmeasured, which reads as "nothing to gate".

    So: exact match first, then a unique path-component SUFFIX match in either
    direction. Uniqueness is the whole safety property — two report entries
    ending in `utils/index.ts` mean the answer is unknown, and an unknown
    answer is returned as one (None), never guessed. main() counts those and
    says so; a silently guessed file is a wrong number nobody can see.
    """
    if diff_path in measured:
        return diff_path
    wanted = path_parts(diff_path)
    if not wanted:
        return None
    candidates = []
    for path in measured:
        parts = path_parts(path)
        if not parts:
            continue
        # `[-n:]` on a shorter list returns all of it, so the comparison is a
        # plain equality check in that direction — which is what is wanted.
        if parts[-len(wanted):] == wanted or wanted[-len(parts):] == parts:
            candidates.append(path)
    return candidates[0] if len(candidates) == 1 else None


def measure_changed_lines(changed: dict[str, set[int]], reports: list[Report]) -> PatchResult:
    """Intersect the added lines with the per-line hit maps.

    A changed line the reports do not mention is not a miss — comments, blank
    lines, type declarations and `}` are not executable, and counting them as
    uncovered would put a floor under the score that no test could lift.
    Only measured lines count, on both sides of the ratio.
    """
    merged: dict[str, dict[int, int]] = {}
    for report in reports:
        for path, hits in report.lines.items():
            per_file = merged.setdefault(path, {})
            for number, count in hits.items():
                per_file[number] = per_file.get(number, 0) + count

    found = hit = 0
    unmeasured: list[str] = []
    misses: dict[str, list[int]] = {}
    for path in sorted(changed):
        match = match_report_path(path, merged)
        if match is None:
            unmeasured.append(path)
            continue
        for number in sorted(changed[path]):
            if number in merged[match]:
                found += 1
                if merged[match][number] > 0:
                    hit += 1
                else:
                    misses.setdefault(path, []).append(number)
    return PatchResult(found, hit, unmeasured, misses)


def read_diff(path: str) -> dict[str, set[int]]:
    """Read a unified diff from a file.

    An EMPTY diff is not an error. "This change touched nothing measurable" is a
    real state — a docs-only change, a revert, a merge commit — and it has an
    answer: not applicable. Only a diff that cannot be READ is an error.
    """
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError as exc:
        raise ParseError(f"cannot read diff {path}: {exc}") from exc
    return parse_diff(text)


def format_ranges(numbers: list[int]) -> str:
    """Collapse [62, 63, 64, 65] to '62-65'.

    A gate that prints four hundred line numbers one per comma does not get
    read, and an unread failure message is the same as no message.
    """
    out: list[str] = []
    start = prev = None
    for number in sorted(numbers):
        if start is None:
            start = prev = number
        elif number == prev + 1:
            prev = number
        else:
            out.append(str(start) if start == prev else f"{start}-{prev}")
            start = prev = number
    if start is not None:
        out.append(str(start) if start == prev else f"{start}-{prev}")
    return ", ".join(out)


def patch_gate_message(patch: PatchResult, threshold: float) -> str:
    """Why the patch gate failed, and which lines to write a test for."""
    pct = 100.0 * patch.hit / patch.found
    lines = [
        f"PATCH COVERAGE BELOW THE BAR: {pct:.2f}% of the lines this change "
        f"adds are covered ({patch.hit} of {patch.found}), and the bar is "
        f"{threshold:.2f}%.",
        "  Untested lines this change added:",
    ]
    for path in sorted(patch.misses):
        lines.append(f"    {path}: {format_ranges(patch.misses[path])}")
    lines.append(
        "  Write a test that reaches them, or lower patch-threshold in the "
        "workflow and say why in the PR."
    )
    return "\n".join(lines)


def patch_message(changed: dict[str, set[int]], patch: PatchResult) -> str:
    """The prose half of the patch numbers, for stderr."""
    added = sum(len(numbers) for numbers in changed.values())
    if patch.found:
        pct = 100.0 * patch.hit / patch.found
        msg = (
            f"patch coverage: {pct:.2f}% — {patch.hit} of {patch.found} added "
            f"lines that the reports measure are covered "
            f"({added} lines added across {len(changed)} file(s); the rest are "
            "comments, blanks or otherwise not executable)"
        )
    elif not changed:
        msg = (
            "patch coverage: not applicable — this diff adds no lines. That is "
            "not 100% and not 0%: there is nothing to have tested."
        )
    else:
        msg = (
            f"patch coverage: not applicable — the {added} line(s) this diff "
            f"adds across {len(changed)} file(s) are not measured by any "
            "report. Not 100% and not 0%: nothing here was instrumented."
        )
    if patch.unmeasured:
        msg += (
            f"\n  WARNING: {len(patch.unmeasured)} changed file(s) match no "
            "report entry, or match more than one, so their added lines are in "
            "neither half of the ratio: "
            + ", ".join(patch.unmeasured[:5])
            + (" ..." if len(patch.unmeasured) > 5 else "")
            + "\n  A wholly new file the test run never loaded looks exactly "
            "like this, and it is the case a patch gate exists to catch."
        )
    return msg


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
        "--diff-file",
        metavar="FILE",
        help="Unified diff of the change under review. Adds the patch_* "
        "outputs: coverage of the lines this change ADDED, which the aggregate "
        "cannot see. Measured and reported, never gated — the gate is a "
        "separate step.",
    )
    ap.add_argument(
        "--patch-threshold",
        type=float,
        metavar="PCT",
        help="Fail when coverage of the lines --diff-file ADDS is below PCT "
        "percent. 0 disables the gate and keeps the measurement. Requires "
        "--diff-file. Unlike the floor this is a fixed bar, and the module "
        "docstring says why the two numbers get different shapes.",
    )
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
    ap.add_argument(
        "--require-floor",
        action="store_true",
        help="Fail when no floor file exists and --write was not given. The "
        "composite action always passes this: without it the documented "
        "configuration never records a floor, so every run compares against "
        "nothing and reports ok forever.",
    )
    args = ap.parse_args()

    # A threshold with no diff would measure nothing, compare nothing, and pass
    # every run — while reading, in the workflow file, exactly like a gate. That
    # is the failure shape this whole milestone exists to remove, so it is a
    # usage error rather than a quiet no-op.
    if args.patch_threshold is not None and not args.diff_file:
        print(
            "error: --patch-threshold needs --diff-file. Without a diff there "
            "are no changed lines to measure, so the gate would pass "
            "everything while looking like a gate.",
            file=sys.stderr,
        )
        return 3

    try:
        reports = [read_report(p) for p in args.report]
        floor = read_floor(args.floor_file)
        # Parsed HERE, with the reports, so a broken diff fails before anything
        # is printed or a floor is written.
        changed = read_diff(args.diff_file) if args.diff_file else None
    except ParseError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3

    found = sum(report.found for report in reports)
    hit = sum(report.hit for report in reports)
    if found == 0:
        print(
            "error: the reports contain 0 measurable lines. That is a broken "
            "coverage run, not 100% coverage — refusing to record a floor.",
            file=sys.stderr,
        )
        return 3

    pct = 100.0 * hit / found

    # A ratchet with no floor is not a gate, and this was the state the
    # DOCUMENTED configuration left every consumer in: the action defaults
    # `raise: false`, the README snippet did not set it, so nothing ever wrote a
    # floor — and a repo measured at 5% against no floor exited 0 with
    # status=ok, run after run, forever. Recording the floor has to be a
    # deliberate act, so refusing here is the only place it can be demanded.
    if floor is None and not args.write and args.require_floor:
        print(
            f"error: no floor at {args.floor_file}, and --write was not given — "
            f"so this run compared {pct:.2f}% against nothing and would have "
            "reported ok whatever the number was. Record the floor once (run "
            "the action with `raise: true`, or this script with --write) and "
            "commit the file it writes.",
            file=sys.stderr,
        )
        return 3

    # stdout is machine-readable (the composite action appends it to
    # $GITHUB_OUTPUT verbatim); prose goes to stderr.
    raised = False
    rc = 0
    # What to REPORT as the floor: the value the floor FILE holds once this run
    # is over, or `none` when it still holds nothing. It used to print the
    # measured percentage whenever there was no floor, which rendered "compared
    # against nothing" identically to "met its floor exactly" — in the one
    # output a reader would use to tell those apart. `raised` says whether this
    # run moved it, so the pair is unambiguous either way.
    floor_out = floor

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
            floor_out = pct
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
            floor_out = pct
            msg += f" — floor raised, commit {args.floor_file}"
        else:
            msg += f" — the floor can be raised to {pct:.2f}%"
    else:
        msg = f"coverage held at {pct:.2f}% (floor {floor:.2f}%)"

    print(f"coverage={pct:.2f}")
    print(f"floor={floor_out:.2f}" if floor_out is not None else "floor=none")
    print(f"lines_hit={hit}")
    print(f"lines_found={found}")
    print(f"raised={'true' if raised else 'false'}")
    print(f"status={'drop' if rc else 'ok'}")

    patch_status = "n/a"
    if changed is not None:
        patch = measure_changed_lines(changed, reports)
        if patch.found:
            print(f"patch_coverage={100.0 * patch.hit / patch.found:.2f}")
        else:
            # NOT 0.00 and not 100.00. See the module docstring.
            print("patch_coverage=n/a")

        if not patch.found:
            # Nothing measurable was added, so no bar can be missed. A docs-only
            # PR is not a coverage failure, and reporting it as one is how a
            # patch gate gets switched off in week two.
            patch_status = "n/a"
        elif args.patch_threshold is None or args.patch_threshold <= 0:
            patch_status = "off"
        elif 100.0 * patch.hit / patch.found + 1e-9 < args.patch_threshold:
            # The epsilon is for the boundary: a change measured at exactly the
            # bar passes it. `>=`, not `>`, and float noise must not decide it.
            patch_status = "below"
            rc = 1
        else:
            patch_status = "ok"

        print(f"patch_status={patch_status}")
        print(f"patch_lines_found={patch.found}")
        print(f"patch_lines_hit={patch.hit}")
        print(f"patch_files_changed={len(changed)}")
        print(f"patch_files_unmeasured={len(patch.unmeasured)}")

    print(msg, file=sys.stderr)
    if changed is not None:
        print(patch_message(changed, patch), file=sys.stderr)
        if patch_status == "below":
            print(
                patch_gate_message(patch, args.patch_threshold), file=sys.stderr
            )
    return rc


if __name__ == "__main__":
    sys.exit(main())
