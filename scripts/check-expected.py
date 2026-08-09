#!/usr/bin/env python3
"""Assert a tool's findings against a committed manifest, per rule id.

WHY THIS EXISTS — A SCALAR TOTAL ABSORBS REGRESSIONS

Every gate in this repo used to assert a count: "8 problems", "13 Error(s)",
"32 findings", "Found 14 errors". A count answers "did roughly the right amount
of stuff fire?" and nothing else. Three things it cannot see:

  1. A rule stops firing while another fires one more time. The total holds.
     This is not hypothetical — `sql-string-concat-ts` shipped with only its
     double-quoted branch, so `db.query('SELECT ... ' + id)` was silently exempt
     and 28/19 stayed green over the gap for months (docs/STATUS.md §4).
  2. A rule that was never covered in the first place. configs/typescript
     enables 140 ESLint rules; the "8 problems" grep pinned 8 of them, so 94% of
     the TypeScript baseline could be deleted with CI green.
  3. A substring match. `grep -q '3 Error(s)'` matches "13 Error(s)", so the
     Tests sample passed on a build with thirteen errors.

So the assertion is now the SET of findings — rule id, file and line — diffed
against a committed manifest. A regression names the rule that stopped firing
instead of showing a number that moved, and adding a fixture shows up in review
as a new manifest entry rather than as "the number went from 32 to 33".

WHY LINE NUMBERS ARE IN THE MANIFEST

They churn when a fixture is edited, and that is the point: `samples/` is the
test suite and CONTRIBUTING.md forbids weakening it, so a fixture edit is always
deliberate and always worth reading. `--update` regenerates the manifest so the
churn lands in one reviewable diff. CI never passes `--update` — a gate that can
rewrite its own expectations is not a gate.

Reads a tool's own machine-readable output. Does no network I/O and writes
nothing unless `--update` is given.

Exit codes: 0 manifest matches · 1 findings drifted · 3 usage/parse error
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

# dotnet has no JSON diagnostic output, so its build log is parsed. MSBuild
# prints each diagnostic twice (once inline, once in the summary) — the caller
# gets a de-duplicated set, so counting matters here, not just membership.
DOTNET_RE = re.compile(
    r"(?P<file>[^\s(]+\.cs)\((?P<line>\d+),\d+\): error (?P<rule>[A-Za-z]+\d+)"
)

# tsc has no JSON diagnostic output either. Anchored at the start of a line
# because tsc indents the explanatory continuation lines of a nested type error
# ("Types of property 'retries' are incompatible.") and those are not findings.
TSC_RE = re.compile(
    r"^(?P<file>\S+?\.[cm]?tsx?)\((?P<line>\d+),\d+\): error (?P<rule>TS\d+)", re.M
)


# Maven has no JSON diagnostic output either, so the build log is parsed. javac
# writes `path/File.java:[LINE,COL] [CheckName] message`, and Maven prefixes the
# line with its own [ERROR]/[WARNING]. Both prefixes are findings: Error Prone's
# warning tier gates through -Werror, so dropping the [WARNING] half would make
# a manifest that cannot see two of the four tiers.
#
# javac's own -Xlint uses the identical shape ([rawtypes], [cast]), which is
# what lets one regex cover the compiler and both plugins.
JAVAC_RE = re.compile(
    r"^\[(?:ERROR|WARNING)\]\s+(?P<file>\S+?\.java):\[(?P<line>\d+),\d+\]\s+"
    r"\[(?P<rule>[A-Za-z][\w.]*)\]",
    re.M,
)


class ParseError(Exception):
    pass


def _rel(path: str) -> str:
    """Manifests are repo-relative so they do not encode anyone's home directory."""
    return os.path.relpath(path, os.getcwd()) if os.path.isabs(path) else path


def parse_semgrep(text: str) -> list[dict]:
    data = json.loads(text)
    # A semgrep run that errored and scanned nothing reports `results: []`, which
    # is indistinguishable from a clean repo unless the errors are read.
    if data.get("errors"):
        raise ParseError(
            f"semgrep reported {len(data['errors'])} error(s); refusing to treat "
            f"the result as a finding set: {data['errors'][0].get('message', '?')}"
        )
    return [
        # The check_id is prefixed by the config path it was loaded from; the
        # last dotted segment is the rule id as written in semgrep/.
        {"rule": r["check_id"].split(".")[-1], "file": _rel(r["path"]), "line": r["start"]["line"]}
        for r in data.get("results", [])
    ]


def parse_eslint(text: str) -> list[dict]:
    return [
        {"rule": m["ruleId"] or "<fatal>", "file": _rel(f["filePath"]), "line": m["line"]}
        for f in json.loads(text)
        for m in f.get("messages", [])
    ]


def parse_ruff(text: str) -> list[dict]:
    return [
        {"rule": r["code"], "file": _rel(r["filename"]), "line": r["location"]["row"]}
        for r in json.loads(text)
    ]


def parse_mypy(text: str) -> list[dict]:
    """mypy --output=json emits JSONL — one object per line, not an array."""
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        d = json.loads(line)
        if d.get("severity") != "error":
            continue
        out.append({"rule": d.get("code") or "<no-code>", "file": _rel(d["file"]), "line": d["line"]})
    return out


def parse_knip(text: str) -> list[dict]:
    """knip --reporter json. One entry per issue *type* per file; the type name
    (files, exports, types, dependencies, unlisted, ...) is the rule id, so a
    manifest diff says WHICH kind of detection was lost, not just where.

    knip prints paths relative to its own working directory, and CI runs it
    from inside the fixture — so these manifests are fixture-relative where
    every other manifest is repo-relative. Whole-file findings (`files`) have
    no line; 0 marks them, deliberately outside any real file's range."""
    out = []
    for issue in json.loads(text).get("issues", []):
        for rule, entries in issue.items():
            if rule == "file" or not isinstance(entries, list):
                continue
            for entry in entries:
                # `duplicates` nests one level deeper: a list of clone groups.
                for e in entry if isinstance(entry, list) else [entry]:
                    out.append(
                        {"rule": rule, "file": _rel(issue["file"]), "line": e.get("line") or 0}
                    )
    return out


def parse_deptry(text: str) -> list[dict]:
    """deptry --json-output. DEP002 (declared but unused) points at
    pyproject.toml with a null line — 0 in the manifest, same convention as
    knip's whole-file findings."""
    return [
        {
            "rule": r["error"]["code"],
            "file": _rel(r["location"]["file"]),
            "line": r["location"]["line"] or 0,
        }
        for r in json.loads(text)
    ]


def parse_clippy(text: str) -> list[dict]:
    """`cargo clippy --message-format=json` — JSONL, one object per line.

    Like the knip manifests, clippy's are FIXTURE-relative: cargo runs from
    inside the fixture and prints paths relative to the workspace root.

    Deduplicated like dotnet's, and for the same shape of reason: with
    `--all-targets` the crate is compiled once as a binary and once as a test
    harness, and every lint fires in both units. When a forbid-level error
    stops cargo early, the second unit may be skipped entirely — deduping makes
    "one unit reported" and "both units reported" the same set, so the
    manifest cannot flap on build scheduling."""
    seen = set()
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        d = json.loads(line)
        if d.get("reason") != "compiler-message":
            continue
        m = d["message"]
        code = (m.get("code") or {}).get("code")
        if not code or m.get("level") not in ("warning", "error"):
            continue
        primary = [s for s in m.get("spans", []) if s.get("is_primary")]
        if not primary:
            continue
        key = (code, _rel(primary[0]["file_name"]), primary[0]["line_start"])
        if key in seen:
            continue
        seen.add(key)
        out.append({"rule": key[0], "file": key[1], "line": key[2]})
    return out


def parse_dotnet(text: str) -> list[dict]:
    seen = set()
    out = []
    for m in DOTNET_RE.finditer(text):
        key = (m["rule"], _rel(m["file"]), int(m["line"]))
        if key in seen:
            continue
        seen.add(key)
        out.append({"rule": key[0], "file": key[1], "line": key[2]})
    return out


def parse_tsc(text: str) -> list[dict]:
    """tsc prints paths relative to the CWD, so run it as `tsc -p <dir>` from the
    repo root rather than cd-ing in — same reason the dotnet job does not use
    `working-directory:`."""
    return [
        {"rule": m["rule"], "file": _rel(m["file"]), "line": int(m["line"])}
        for m in TSC_RE.finditer(text)
    ]


def parse_javac(text: str) -> list[dict]:
    """Maven's compiler log — javac's own -Xlint, Error Prone and NullAway.

    Deduplicated like dotnet's and clippy's: Maven prints the compiler's
    diagnostics once inline and once again in the goal-failure summary, so an
    un-deduped parse doubles every ERROR while leaving every WARNING alone.

    Paths are ABSOLUTE in Maven's output — javac is forked, so it reports what
    it was handed. `_rel` folds them back to repo-relative, which is why CI must
    run this from the repo root rather than from inside the fixture.

    Deliberately NOT a finding: `error: warnings found and -Werror specified`.
    It carries no file and no rule id, it is a consequence of the findings
    above it rather than one of them, and counting it would put a phantom entry
    in every manifest whose fixture happens to trip the warning tier."""
    seen = set()
    out = []
    for m in JAVAC_RE.finditer(text):
        key_ = (m["rule"], _rel(m["file"]), int(m["line"]))
        if key_ in seen:
            continue
        seen.add(key_)
        out.append({"rule": key_[0], "file": key_[1], "line": key_[2]})
    return out


PARSERS = {
    "clippy": parse_clippy,
    "javac": parse_javac,
    "semgrep": parse_semgrep,
    "eslint": parse_eslint,
    "ruff": parse_ruff,
    "mypy": parse_mypy,
    "dotnet": parse_dotnet,
    "tsc": parse_tsc,
    "knip": parse_knip,
    "deptry": parse_deptry,
}


def canonical(findings: list[dict]) -> list[dict]:
    return sorted(findings, key=lambda f: (f["file"], f["line"], f["rule"]))


def key(f: dict) -> tuple:
    return (f["file"], f["line"], f["rule"])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tool", required=True, choices=sorted(PARSERS))
    ap.add_argument("--input", required=True, metavar="FILE", help="the tool's output ('-' for stdin)")
    ap.add_argument("--expected", required=True, metavar="FILE", help="the committed manifest")
    ap.add_argument(
        "--update",
        action="store_true",
        help="rewrite the manifest from this run. Never use in CI — a gate that "
        "can rewrite its own expectations is not a gate.",
    )
    args = ap.parse_args()

    try:
        text = sys.stdin.read() if args.input == "-" else open(args.input, encoding="utf-8").read()
    except OSError as exc:
        print(f"error: cannot read {args.input}: {exc}", file=sys.stderr)
        return 3

    try:
        actual = canonical(PARSERS[args.tool](text))
    except (ParseError, json.JSONDecodeError, KeyError, TypeError) as exc:
        print(f"error: cannot parse {args.tool} output from {args.input}: {exc}", file=sys.stderr)
        return 3

    if args.update:
        with open(args.expected, "w", encoding="utf-8") as fh:
            json.dump({"tool": args.tool, "findings": actual}, fh, indent=2)
            fh.write("\n")
        print(f"wrote {len(actual)} findings to {args.expected}", file=sys.stderr)
        return 0

    try:
        with open(args.expected, encoding="utf-8") as fh:
            expected = canonical(json.load(fh)["findings"])
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        # An unreadable manifest is NOT "nothing expected" — that would make a
        # deleted manifest a passing gate.
        print(f"error: manifest {args.expected} is unusable: {exc}", file=sys.stderr)
        return 3

    exp_keys = {key(f) for f in expected}
    act_keys = {key(f) for f in actual}
    missing = sorted(exp_keys - act_keys)
    unexpected = sorted(act_keys - exp_keys)

    print(f"{args.tool}_expected={len(expected)}")
    print(f"{args.tool}_actual={len(actual)}")
    print(f"{args.tool}_missing={len(missing)}")
    print(f"{args.tool}_unexpected={len(unexpected)}")

    if not missing and not unexpected:
        print(f"OK: {args.tool} matches {args.expected} exactly ({len(actual)} findings)", file=sys.stderr)
        return 0

    # A rule that vanished ENTIRELY is the regression that matters most: it means
    # a detection was lost, not that a fixture moved. Say so first and loudest.
    gone = sorted({f["rule"] for f in expected} - {f["rule"] for f in actual})
    if gone:
        for rule in gone:
            print(f"::error::{args.tool}: rule '{rule}' no longer fires anywhere — a detection was LOST", file=sys.stderr)

    for f, ln, rule in missing:
        print(f"  MISSING     {rule:<50} {f}:{ln}", file=sys.stderr)
    for f, ln, rule in unexpected:
        print(f"  UNEXPECTED  {rule:<50} {f}:{ln}", file=sys.stderr)
    print(
        f"\n{args.tool} drifted from {args.expected}: "
        f"{len(missing)} missing, {len(unexpected)} unexpected.\n"
        "If this is a deliberate fixture or rule change, regenerate with --update "
        "and say in the commit message what changed and why the new set is correct "
        "(CONTRIBUTING.md rule 2). Never regenerate to make a red build green.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
