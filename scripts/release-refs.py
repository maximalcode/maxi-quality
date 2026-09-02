#!/usr/bin/env python3
"""Close a release wrapper over one immutable maxi-quality payload.

The reusable workflows are wrappers around composite actions.  A tag-shaped
reference in a wrapper is therefore not a pin: it can resolve a different
payload from the wrapper that introduced it.  A release wrapper records its
payload commit in ``release-payload.sha`` and every first-party
``uses:`` reference must name that exact commit.

``verify-wrapper`` additionally makes the relationship executable.  The
payload must be an ancestor of the release revision, and the executable
delivery closure in that revision must equal the payload. That prevents a
commit from claiming to wrap P while silently changing an action, its shipped
scripts, baseline configuration, or the Semgrep rules consumers execute.

This has no network dependency.  It deliberately reads YAML as text: the
property being checked is GitHub's ``uses:`` syntax, and preserving the exact
line is what makes ``rewrite`` safe for a release finalization.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import subprocess
import sys
from dataclasses import dataclass


SHA = re.compile(r"[0-9a-f]{40}\Z")
USES = re.compile(
    r"^(?P<prefix>\s*(?:-\s*)?uses:\s*)(?P<quote>['\"]?)"
    r"(?P<target>maximalcode/maxi-quality/(?P<path>[^@\s'\"]+))@"
    r"(?P<ref>[^\s#'\"]+)(?P=quote)(?P<suffix>\s*(?:#.*)?)$"
)
WORKFLOW_DIR = pathlib.Path(".github/workflows")
PAYLOAD_FILE = pathlib.Path("release-payload.sha")
PAYLOAD_PREFIXES = ("actions/", "scripts/", "configs/", "semgrep/")


class CheckError(Exception):
    pass


@dataclass(frozen=True)
class Ref:
    file: pathlib.Path
    line: int
    target: str
    path: str
    ref: str


def require_sha(value: str, label: str = "SHA") -> str:
    if not SHA.fullmatch(value):
        raise CheckError(f"{label} must be a lowercase, full 40-character commit SHA; got {value!r}")
    return value


def run_git(root: pathlib.Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args], text=True, capture_output=True
    )
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        raise CheckError(f"git {' '.join(args)} failed{': ' + detail if detail else ''}")
    return result.stdout


def workflow_files(root: pathlib.Path) -> list[pathlib.Path]:
    directory = root / WORKFLOW_DIR
    if not directory.is_dir():
        raise CheckError(f"missing {WORKFLOW_DIR}/")
    # A reusable workflow is identified by the GitHub trigger it exposes, not
    # by a filename.  A local CI workflow may legitimately exercise @v1.
    found = []
    for pattern in ("*.yml", "*.yaml"):
        for path in directory.glob(pattern):
            text = path.read_text(encoding="utf-8")
            if is_reusable_workflow(text):
                found.append(path)
    if not found:
        raise CheckError("found no reusable workflows (no workflow_call trigger)")
    return sorted(found)


def is_reusable_workflow(text: str) -> bool:
    """Recognise workflow_call only inside the real top-level ``on`` key.

    CI contains here-doc fixtures that deliberately look like complete
    workflows. Searching for ``workflow_call`` anywhere made those test strings
    part of the release surface and let rewrite mutate a fixture.
    """
    lines = text.splitlines()
    top_on = re.compile(r"^(?:on|['\"]on['\"])\s*:\s*(?P<value>.*)$")
    child_key = re.compile(r"^(?:workflow_call|['\"]workflow_call['\"])\s*:")
    for index, line in enumerate(lines):
        match = top_on.match(line)
        if not match:
            continue
        # A comment after `on:` still introduces an indented trigger map.
        # Strip it before deciding whether this is block or flow YAML.
        value = match["value"].split("#", 1)[0].strip()
        if value:
            return bool(re.search(
                r"(?:^|[\s,[{])['\"]?workflow_call['\"]?(?:$|[\s,:\]}])", value
            ))
        child_indent: int | None = None
        for child in lines[index + 1:]:
            if not child.strip() or child.lstrip().startswith("#"):
                continue
            indent = len(child) - len(child.lstrip())
            if indent == 0:
                break
            if child_indent is None:
                child_indent = indent
            if indent == child_indent and child_key.match(child.lstrip()):
                return True
        return False
    return False


def reject_unparsed_first_party(text: str, display: pathlib.Path) -> None:
    """Fail closed if valid-but-unhandled YAML hides a first-party ref.

    The rewriter intentionally preserves formatting and has no YAML dependency.
    It must therefore never certify a quoted key or a folded scalar that its
    line grammar cannot rewrite. Comments are excluded because this repository
    documents examples of the same syntax beside the actual workflow steps.
    """
    errors = []
    for number, line in enumerate(text.splitlines(), 1):
        if "maximalcode/maxi-quality/" not in line or line.lstrip().startswith("#"):
            continue
        if not USES.match(line):
            errors.append(f"{display}:{number}: unsupported first-party uses syntax; use a plain uses: line")
    if errors:
        raise CheckError("\n".join(errors))


def parse_ref_text(text: str, display: pathlib.Path) -> list[Ref]:
    refs = []
    for number, line in enumerate(text.splitlines(), 1):
        match = USES.match(line)
        if match:
            refs.append(Ref(display, number, match["target"], match["path"], match["ref"]))
    return refs


def direct_refs(root: pathlib.Path) -> list[Ref]:
    refs = []
    for workflow in workflow_files(root):
        text = workflow.read_text(encoding="utf-8")
        display = workflow.relative_to(root)
        reject_unparsed_first_party(text, display)
        refs.extend(parse_ref_text(text, display))
    if not refs:
        raise CheckError("found no first-party uses: references in reusable workflows")
    return sorted(refs, key=lambda ref: (ref.file.as_posix(), ref.line, ref.target))


def revision_refs(root: pathlib.Path, revision: str) -> list[Ref]:
    paths = [
        pathlib.Path(line) for line in run_git(root, "ls-tree", "-r", "--name-only", revision, "--", str(WORKFLOW_DIR)).splitlines()
        if line.endswith((".yml", ".yaml"))
    ]
    refs = []
    for path in paths:
        content = run_git(root, "show", f"{revision}:{path.as_posix()}")
        if is_reusable_workflow(content):
            reject_unparsed_first_party(content, path)
            refs.extend(parse_ref_text(content, path))
    if not refs:
        raise CheckError("found no first-party uses: references in reusable workflows")
    return sorted(refs, key=lambda ref: (ref.file.as_posix(), ref.line, ref.target))


def payload_action_path(path: str) -> str:
    if path.startswith("actions/"):
        return f"{path}/action.yml"
    if path.startswith(".github/workflows/"):
        return path
    raise CheckError(f"unsupported first-party reusable target: {path}")


def payload_refs(root: pathlib.Path, initial: list[Ref]) -> list[Ref]:
    """Walk first-party references reached through the pinned payload tree."""
    result = list(initial)
    pending = [(ref.ref, ref.path) for ref in initial]
    seen: set[tuple[str, str]] = set()
    while pending:
        revision, target = pending.pop()
        key = (revision, target)
        if key in seen:
            continue
        seen.add(key)
        source = payload_action_path(target)
        content = run_git(root, "show", f"{revision}:{source}")
        virtual = pathlib.Path(f"{revision}:{source}")
        reject_unparsed_first_party(content, virtual)
        for number, line in enumerate(content.splitlines(), 1):
            match = USES.match(line)
            if not match:
                continue
            ref = Ref(virtual, number, match["target"], match["path"], match["ref"])
            result.append(ref)
            pending.append((ref.ref, ref.path))
    return sorted(result, key=lambda ref: (ref.file.as_posix(), ref.line, ref.target))


def read_payload_file(root: pathlib.Path, revision: str | None = None) -> str:
    path = root / PAYLOAD_FILE
    if revision:
        try:
            value = run_git(root, "show", f"{revision}:{PAYLOAD_FILE}")
        except CheckError as error:
            raise CheckError(f"missing {PAYLOAD_FILE} in {revision}; a release wrapper must record its payload commit") from error
    elif not path.is_file():
        raise CheckError(f"missing {PAYLOAD_FILE}; a release wrapper must record its payload commit")
    else:
        value = path.read_text(encoding="utf-8")
    if not value.endswith("\n") or value.count("\n") != 1:
        raise CheckError(f"{PAYLOAD_FILE} must contain exactly one SHA followed by a newline")
    return require_sha(value[:-1], PAYLOAD_FILE.as_posix())


def check_refs(root: pathlib.Path, payload: str | None) -> None:
    direct = direct_refs(root)
    failures = []
    for ref in direct:
        if not SHA.fullmatch(ref.ref):
            failures.append(f"{ref.file}:{ref.line}: mutable first-party ref {ref.target}@{ref.ref}")
        # A wrapper's direct references must resolve its declared payload. A
        # reference found *inside* that payload cannot in general name the
        # payload itself: doing so would be a self-referential git commit. It
        # is still required to be immutable, and is walked so no nested @v1
        # can hide behind a direct pin.
        elif payload and ref in direct and ref.ref != payload:
            failures.append(f"{ref.file}:{ref.line}: {ref.target}@{ref.ref} does not target payload {payload}")
    if failures:
        raise CheckError("\n".join(failures))
    if not payload:
        return
    # Do this only after direct refs have been established as P. Otherwise a
    # stale SHA reports as a missing git object and hides the actionable error.
    for ref in payload_refs(root, direct):
        if not SHA.fullmatch(ref.ref):
            failures.append(f"{ref.file}:{ref.line}: mutable first-party ref {ref.target}@{ref.ref}")
    if failures:
        raise CheckError("\n".join(failures))


def rewrite(root: pathlib.Path, payload: str) -> int:
    changed = 0
    for workflow in workflow_files(root):
        original = workflow.read_text(encoding="utf-8")
        lines = original.splitlines(keepends=True)
        rewritten = []
        for line in lines:
            body = line[:-1] if line.endswith("\n") else line
            match = USES.match(body)
            if not match:
                rewritten.append(line)
                continue
            ending = "\n" if line.endswith("\n") else ""
            rewritten.append(
                f"{match['prefix']}{match['quote']}{match['target']}@{payload}"
                f"{match['quote']}{match['suffix']}{ending}"
            )
        updated = "".join(rewritten)
        if updated != original:
            workflow.write_text(updated, encoding="utf-8")
            changed += 1
    return changed


def verify_wrapper(root: pathlib.Path, revision: str) -> None:
    run_git(root, "cat-file", "-e", f"{revision}^{{commit}}")
    payload = read_payload_file(root, revision)
    run_git(root, "cat-file", "-e", f"{payload}^{{commit}}")
    if subprocess.run(
        ["git", "-C", str(root), "merge-base", "--is-ancestor", payload, revision],
        capture_output=True,
    ).returncode:
        raise CheckError(
            f"{PAYLOAD_FILE} names {payload}, but that payload is not an ancestor of {revision}"
        )
    # Compare P to the release revision, rather than HEAD to P. GitHub tests a
    # synthetic PR merge and promotion creates another merge on main; P remains
    # an ancestor in both cases. No tree is checked out: the release workflow
    # deliberately never materialises its triggering SHA.
    changed = {
        pathlib.Path(line)
        for line in run_git(root, "diff", "--name-only", payload, revision, "--", *PAYLOAD_PREFIXES).splitlines()
        if line
    }
    for prefix in PAYLOAD_PREFIXES:
        altered = sorted(path for path in changed if path.as_posix().startswith(prefix))
        if altered:
            raise CheckError(
                "release wrapper changes executable payload files:\n"
                + "\n".join(f"  {path}" for path in altered)
            )
    direct = revision_refs(root, revision)
    failures = []
    for ref in direct:
        if not SHA.fullmatch(ref.ref):
            failures.append(f"{ref.file}:{ref.line}: mutable first-party ref {ref.target}@{ref.ref}")
        elif ref in direct and ref.ref != payload:
            failures.append(f"{ref.file}:{ref.line}: {ref.target}@{ref.ref} does not target payload {payload}")
    if failures:
        raise CheckError("\n".join(failures))
    for ref in payload_refs(root, direct):
        if not SHA.fullmatch(ref.ref):
            failures.append(f"{ref.file}:{ref.line}: mutable first-party ref {ref.target}@{ref.ref}")
    if failures:
        raise CheckError("\n".join(failures))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=pathlib.Path, default=pathlib.Path("."), help="repository root (default: .)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="list first-party refs in reusable workflows")
    check = sub.add_parser("check", help="require immutable refs, optionally to one payload")
    check.add_argument("--payload", help="expected payload commit SHA")
    rewrite_parser = sub.add_parser("rewrite", help="rewrite reusable-workflow refs to a payload SHA")
    rewrite_parser.add_argument("--payload", required=True, help="payload commit SHA")
    record = sub.add_parser("record", help="write release-payload.sha for a release wrapper")
    record.add_argument("--payload", required=True, help="payload commit SHA")
    verify = sub.add_parser("verify-wrapper", help="verify release-payload.sha and a closed release revision")
    verify.add_argument("--revision", default="HEAD", help="release commit to inspect through git plumbing (default: HEAD)")
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        if args.command == "list":
            for ref in direct_refs(root):
                print(f"{ref.file}:{ref.line}: {ref.target}@{ref.ref}")
        elif args.command == "check":
            payload = require_sha(args.payload, "--payload") if args.payload else None
            check_refs(root, payload)
            print("OK: every first-party reusable-workflow ref is immutable"
                  + (f" and targets {payload}" if payload else ""))
        elif args.command == "rewrite":
            payload = require_sha(args.payload, "--payload")
            changed = rewrite(root, payload)
            print(f"rewrote first-party refs in {changed} reusable workflow(s) to {payload}")
        elif args.command == "record":
            payload = require_sha(args.payload, "--payload")
            (root / PAYLOAD_FILE).write_text(payload + "\n", encoding="utf-8")
            print(f"recorded {payload} in {PAYLOAD_FILE}")
        else:
            verify_wrapper(root, args.revision)
            print("OK: release wrapper is closed over its recorded immutable payload")
    except CheckError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
