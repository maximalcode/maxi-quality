#!/usr/bin/env python3
"""Enumerate the PER-PACKAGE deptry invocations under a directory (#97).

WHY THIS EXISTS

#52 adopted deptry with exactly one condition, and it is a granularity
condition: **per package, never at a workspace root.** Measured in #39 — at a
monorepo root deptry reported 125 findings, 118 of them one first-party
artifact; on the member package it reported 3. A gate that ships 94% noise on
day one gets deleted, which is worse than no gate. So the condition has to be
encoded somewhere, and `deptry .` in the directory `quality.yml` detected is
precisely the invocation that was measured and rejected.

THE MECHANISM, AND WHY IT IS THE EXCLUSION RATHER THAN THE DETECTION

What makes a root run noisy is not that the root is a "workspace" — it is that
deptry walks every .py file beneath the root and checks each import against the
ROOT's manifest. A member's own dependency, and a member importing a sibling,
are both undeclared from up there. So the load-bearing part of this script is
that every target EXCLUDES the package directories nested inside it. Getting
the root/package distinction slightly wrong then costs a little redundancy;
getting the exclusion wrong is the 118 findings.

`--extend-exclude`, never `--exclude`. MEASURED against deptry 0.25.1's own
`--help`: plain `--exclude` "overwrites the defaults", which are
`venv, \\.venv, \\.direnv, tests, \\.git, setup\\.py`. Passing the member list
through `--exclude` would therefore silently start scanning every virtualenv in
the tree. Same shape as Ruff's bare `select` replacing what it inherits
(configs/python/ruff.toml says so at length) and it is worth naming twice.

The patterns are REGEXES matched with `re.match`, i.e. anchored at the start of
the path — not globs — so they are escaped here rather than passed through.

Output: a JSON list of {dir, roots, extend_exclude}, one entry per package,
sorted. Empty list = nothing here deptry can read, which the caller reports
rather than treating as clean.

Exit codes: 0 fine · 3 usage error
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

# Directories that are never source. `target` and `build` are here because a
# Java or Rust consumer's build output can contain vendored Python.
PRUNE = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "site-packages",
    "target",
    "venv",
}

# What deptry can actually read as a dependency manifest, restricted to the two
# forms quality.yml's detection already accepts. setup.py and Pipfile projects
# are not in v1's Python scope, so claiming to enumerate them would be a promise
# the rest of the baseline does not keep.
MANIFESTS = ("pyproject.toml", "requirements.txt")


def _load_toml():
    """tomllib (3.11+), then tomli, then None.

    None is the degraded path, and it is degraded in a bounded way: see
    `is_package`. The Rust branch of quality.yml refuses to guess at TOML
    because its guess HARD-FAILS a consumer's build; this one only chooses
    which directory to scan, and it says out loud when it is guessing.
    """
    try:
        import tomllib  # noqa: PLC0415 — optional by design

        return tomllib
    except ImportError:
        pass
    try:
        import tomli  # noqa: PLC0415

        return tomli
    except ImportError:
        return None


# A TOML table header is the one construct that is unambiguous at the start of a
# line, which is what makes this fallback bounded rather than a parser.
TABLE_RE = re.compile(r"^\[(project|tool\.poetry)[\].]", re.M)


def is_package(directory: str, toml_mod) -> bool:
    """Does this directory declare dependencies deptry can check?

    A uv/poetry workspace root may be "virtual" — `[tool.uv.workspace]` and no
    `[project]` — and deptry cannot run there at all. Those are skipped, which
    is #52's condition falling straight out of the manifest rather than out of a
    special case named after it.
    """
    if os.path.isfile(os.path.join(directory, "requirements.txt")):
        return True
    pyproject = os.path.join(directory, "pyproject.toml")
    if not os.path.isfile(pyproject):
        return False
    if toml_mod is None:
        try:
            with open(pyproject, encoding="utf-8") as fh:
                return TABLE_RE.search(fh.read()) is not None
        except OSError:
            return False
    try:
        with open(pyproject, "rb") as fh:
            doc = toml_mod.load(fh)
    except (OSError, ValueError) as exc:
        print(f"::error::{pyproject} could not be parsed as TOML: {exc}", file=sys.stderr)
        raise SystemExit(3)
    return "project" in doc or "poetry" in doc.get("tool", {})


def find_packages(base: str, toml_mod) -> list:
    packages = []
    for root, dirs, files in os.walk(base):
        dirs[:] = sorted(d for d in dirs if d not in PRUNE)
        if any(m in files for m in MANIFESTS) and is_package(root, toml_mod):
            packages.append(os.path.relpath(root, base))
    return sorted(packages)


def build_targets(base: str, toml_mod) -> list:
    packages = find_packages(base, toml_mod)
    pkgset = set(packages)
    targets = []
    for pkg in packages:
        pkg_dir = os.path.join(base, pkg)
        # `src` when the project uses the src layout — that is the one case
        # where the package's own code is already fenced off from everything
        # else in its directory, and it is what samples/deptry does.
        if os.path.isdir(os.path.join(pkg_dir, "src")):
            roots, exclude = ["src"], []
        else:
            roots = ["."]
            # Every OTHER package nested inside this one. Their code belongs to
            # their own manifest; scanned against this one it is 118 findings.
            nested = sorted(
                os.path.relpath(other, pkg)
                for other in pkgset
                if other != pkg
                and (pkg == "." or other.startswith(pkg + os.sep))
            )
            exclude = [re.escape(n.replace(os.sep, "/")) + "/" for n in nested]
        targets.append({"dir": pkg, "roots": roots, "extend_exclude": exclude})
    return targets


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", required=True, help="the directory quality.yml detected")
    ap.add_argument(
        "--format",
        choices=("json", "tsv"),
        default="json",
        help="json is the asserted form (CI diffs it against a committed "
        "expectation); tsv is what actions/deadcode reads, because a block "
        "scalar in a workflow cannot hold an unindented python heredoc and a "
        "second parser embedded in YAML is a second thing to get wrong.",
    )
    args = ap.parse_args()

    if not os.path.isdir(args.dir):
        print(f"error: not a directory: {args.dir}", file=sys.stderr)
        return 3

    toml_mod = _load_toml()
    if toml_mod is None:
        print(
            "::warning::no tomllib or tomli available, so pyproject.toml is being "
            "matched by table header rather than parsed. deptry targets may be "
            "over-inclusive on an unusual layout. Run the python job on 3.11+, or "
            "add tomli to the project's dev dependencies, to remove the guess.",
            file=sys.stderr,
        )

    targets = build_targets(args.dir, toml_mod)
    if args.format == "tsv":
        for t in targets:
            print("\t".join([t["dir"], " ".join(t["roots"]), " ".join(t["extend_exclude"])]))
    else:
        print(json.dumps(targets, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
