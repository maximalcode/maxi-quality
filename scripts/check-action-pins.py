#!/usr/bin/env python3
"""Check that third-party GitHub Actions use an immutable commit SHA.

The scan scope deliberately matches the workflow guard this replaces:
``.github/workflows/``, ``actions/`` and ``examples/``.  Local composite-action
calls and this repository's own ``maximalcode/*`` calls are part of the
existing contract and remain exempt.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Iterator

import yaml


SCAN_ROOTS = (Path(".github/workflows"), Path("actions"), Path("examples"))
YAML_SUFFIXES = {".yml", ".yaml"}
TEXT_USES = re.compile(r"(?:^|\s)uses\s*:\s*(?P<value>.*)$")
ACTION_PATH = re.compile(
    r"^(?P<owner>[A-Za-z0-9_.-]+)/"
    r"(?P<repo>[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*)@(?P<ref>.+)$"
)
OWNER_PATH = re.compile(r"^[A-Za-z0-9_.-]+/")
SHA = re.compile(r"^[0-9a-f]{40}$")


def scan_files(root: Path) -> Iterator[Path]:
    """Yield all files beneath one of the intentionally narrow scan roots."""

    if not root.is_dir():
        return
    for path in sorted(root.rglob("*")):
        if path.is_file():
            yield path


def uses_nodes(node: yaml.Node) -> Iterator[tuple[yaml.Node, yaml.Node]]:
    """Yield ``uses`` key/value nodes from a composed YAML document."""

    if isinstance(node, yaml.MappingNode):
        for key, value in node.value:
            if isinstance(key, yaml.ScalarNode) and key.value == "uses":
                yield key, value
            yield from uses_nodes(key)
            yield from uses_nodes(value)
    elif isinstance(node, yaml.SequenceNode):
        for child in node.value:
            yield from uses_nodes(child)


def diagnostic(path: Path, node: yaml.Node, message: str) -> str:
    line = node.start_mark.line + 1
    return f"::error file={path},line={line}::{message}"


def check_ref(path: Path, line: int, ref: str) -> str | None:
    """Return a diagnostic for an out-of-policy third-party action, if any."""

    # These are existing, deliberate exemptions.  Docker actions have no
    # GitHub commit ref in this syntax and are outside this guard's policy.
    if ref.startswith(("./", "../", "docker://", "${{")):
        return None
    if ref.startswith("maximalcode/"):
        return None

    # Only GitHub action-shaped values are in scope.  This preserves the old
    # grep guard's scope while making malformed refs fail once they look like
    # an owner/repository path.
    if not OWNER_PATH.match(ref):
        return None

    match = ACTION_PATH.fullmatch(ref)
    if match is None:
        return f"::error file={path},line={line}::third-party action {ref!r} must use owner/repository@<40 lowercase hex>"
    commit = match.group("ref")
    if not SHA.fullmatch(commit):
        return (
            f"::error file={path},line={line}::third-party action {ref!r} must use exactly "
            "40 lowercase hex characters after @"
        )
    return None


def check_value(path: Path, value: yaml.Node) -> str | None:
    if not isinstance(value, yaml.ScalarNode) or not isinstance(value.value, str):
        return diagnostic(path, value, "the uses value must be a scalar action reference")
    return check_ref(path, value.start_mark.line + 1, value.value)


def check_text_file(path: Path, display_path: Path) -> list[str]:
    """Keep the old directory-wide grep coverage for non-YAML examples/docs."""

    issues: list[str] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        return [f"::error file={display_path}::cannot read workflow: {exc}"]
    for line_number, line in enumerate(lines, 1):
        if line.lstrip().startswith("#"):
            continue
        found = TEXT_USES.search(line)
        if found is None:
            continue
        raw = found.group("value").strip()
        if not raw:
            continue
        # Let PyYAML perform the same quote/comment handling as YAML files.
        try:
            node = yaml.compose(f"uses: {raw}\n")
            value = node.value[0][1] if isinstance(node, yaml.MappingNode) else None
            ref = value.value if isinstance(value, yaml.ScalarNode) else raw
        except yaml.YAMLError:
            ref = raw
        if not (OWNER_PATH.match(ref) or ref.startswith(("./", "../", "maximalcode/"))):
            continue
        issue = check_ref(display_path, line_number, ref)
        if issue:
            issues.append(issue)
    return issues


def check_file(path: Path, display_path: Path | None = None) -> list[str]:
    display = display_path or path
    if path.suffix.lower() not in YAML_SUFFIXES:
        return check_text_file(path, display)
    try:
        documents = yaml.compose_all(path.read_text(encoding="utf-8"))
        issues: list[str] = []
        for document in documents:
            if document is None:
                continue
            for key, value in uses_nodes(document):
                issue = check_value(display, value)
                if issue:
                    issues.append(issue)
        return issues
    except (OSError, UnicodeDecodeError) as exc:
        return [f"::error file={display}::cannot read workflow: {exc}"]
    except yaml.YAMLError as exc:
        return [f"::error file={display}::cannot parse YAML: {exc}"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="repository root to scan (default: current directory)",
    )
    args = parser.parse_args(argv)

    issues: list[str] = []
    scanned = 0
    for relative in SCAN_ROOTS:
        for path in scan_files(args.root / relative):
            scanned += 1
            issues.extend(check_file(path, path.relative_to(args.root)))

    if issues:
        print("::error::third-party actions must be pinned to a full commit SHA:")
        print("\n".join(issues))
        print("Keep a release tag as a trailing YAML comment for Dependabot.")
        return 1

    print(f"OK: every third-party action in {scanned} workflow/action/example files is pinned")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
