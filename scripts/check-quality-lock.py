#!/usr/bin/env python3
"""Check that a consumer's reusable workflows agree with its optional release lock."""

from __future__ import annotations

import argparse
import importlib.util
import pathlib
import re
import sys

import yaml


def runtime_module():
    path = pathlib.Path(__file__).with_name("quality-runtime.py")
    spec = importlib.util.spec_from_file_location("quality_runtime", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RUNTIME = runtime_module()
REFERENCE = re.compile(
    r"^maximalcode/maxi-quality/[^@\s]+@(?P<commit>[0-9a-f]{40})$"
)


def uses_nodes(node, seen=None):
    """Read YAML structure, including quoted keys and folded scalar values."""
    if seen is None:
        seen = set()
    if node is None or id(node) in seen:
        return
    seen.add(id(node))
    if isinstance(node, yaml.MappingNode):
        for key, value in node.value:
            if isinstance(key, yaml.ScalarNode) and key.value == "uses":
                if isinstance(value, yaml.ScalarNode):
                    yield value
            else:
                yield from uses_nodes(value, seen)
    elif isinstance(node, yaml.SequenceNode):
        for value in node.value:
            yield from uses_nodes(value, seen)


def check(root: pathlib.Path) -> list[str]:
    if not (root / RUNTIME.LOCK_NAME).exists():
        return []
    lock = RUNTIME.read_lock(root, require_guard=False)
    errors = []
    directory = root / ".github" / "workflows"
    paths = sorted({*directory.glob("*.yml"), *directory.glob("*.yaml")})
    for path in paths:
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        for node in uses_nodes(yaml.compose(text, Loader=yaml.SafeLoader)):
            value = node.value
            if not value.startswith("maximalcode/maxi-quality/"):
                continue
            ref = REFERENCE.fullmatch(value)
            number = node.start_mark.line + 1
            version_comment = re.search(r"#\s*" + re.escape(lock["version"]) + r"\s*$",
                                        lines[number - 1])
            if ref is None or ref["commit"] != lock["commit"] or not version_comment:
                errors.append(
                    f"{path.relative_to(root)}:{number}: expected maxi-quality "
                    f"@{lock['commit']} # {lock['version']} from {RUNTIME.LOCK_NAME}"
                )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", type=pathlib.Path, default=pathlib.Path.cwd())
    args = parser.parse_args()
    try:
        errors = check(args.root.resolve())
    except (OSError, ValueError, yaml.YAMLError, RUNTIME.RuntimeError_) as exc:
        print(f"quality release lock: {exc}", file=sys.stderr)
        return 1
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print("quality release lock: consistent (or legacy consumer without a lock)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
