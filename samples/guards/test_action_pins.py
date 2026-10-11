#!/usr/bin/env python3
"""Exercise the exact workflow-lint action-pin step in isolated repositories.

The test extracts the named step from ``ci.yml`` and executes its shell body.
That keeps the CI check and this regression test on the same implementation,
while temporary repositories keep bait out of the three scanned roots in this
repository.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import yaml


REPO = Path(__file__).resolve().parents[2]
STEP_NAME = "Third-party actions must be SHA-pinned"
ROOTS = {
    ".github/workflows": Path("workflow.yml"),
    "actions": Path("fixture/action.yml"),
    "examples": Path("fixture.yml"),
}


def read_corpus(name: str) -> list[str]:
    path = REPO / "samples/guards" / name
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def read_history() -> list[tuple[str, str]]:
    path = REPO / "samples/guards/action-pins-historical.txt"
    cases: list[tuple[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            label, ref = line.split("|", 1)
            cases.append((label, ref))
    return cases


def ci_step() -> str:
    workflow = yaml.safe_load((REPO / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    steps = workflow["jobs"]["workflow-lint"]["steps"]
    step = next((step for step in steps if step.get("name") == STEP_NAME), None)
    if step is None or not isinstance(step.get("run"), str):
        raise AssertionError(f"could not extract {STEP_NAME!r} from ci.yml")
    return step["run"]


def fixture(refs: list[str], style: int, labels: list[str] | None = None) -> str:
    lines = [
        "name: action-pin-fixture",
        "on: push",
        "jobs:",
        "  check:",
        "    runs-on: ubuntu-latest",
        "    steps:",
    ]
    for index, ref in enumerate(refs):
        # Exercise all YAML scalar forms. A space before # is a real comment;
        # # with no preceding space remains part of the value and is rejected.
        quote = (style + index) % 3
        if quote == 1:
            value = f"'{ref}'"
        elif quote == 2:
            value = f'"{ref}"'
        else:
            value = ref
        comment = " # real trailing comment" if index == 0 else ""
        if labels:
            lines.append(f"      - name: {labels[index]}")
            lines.append(f"        uses: {value}{comment}")
        else:
            lines.append(f"      - uses: {value}{comment}")
    return "\n".join(lines) + "\n"


def run_step(
    run: str,
    refs: list[str],
    root: str,
    relative: Path,
    style: int,
    labels: list[str] | None = None,
) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory(prefix="maxi-action-pins-") as directory:
        temp = Path(directory)
        target = temp / root / relative
        target.parent.mkdir(parents=True)
        target.write_text(fixture(refs, style, labels), encoding="utf-8")
        checker = temp / "scripts/check-action-pins.py"
        checker.parent.mkdir()
        shutil.copy2(REPO / "scripts/check-action-pins.py", checker)
        return subprocess.run(
            ["bash", "-euo", "pipefail", "-c", run],
            cwd=temp,
            text=True,
            capture_output=True,
            check=False,
        )


def assert_allowed(run: str, refs: list[str]) -> None:
    for root, relative in ROOTS.items():
        for style in range(3):
            result = run_step(run, refs, root, relative, style)
            output = result.stdout + result.stderr
            assert result.returncode == 0, f"{root} allowed refs failed: {output}"
            assert "OK: every third-party action" in output, output


def assert_banned(run: str, refs: list[str]) -> None:
    for ref in refs:
        for root, relative in ROOTS.items():
            for style in range(3):
                result = run_step(run, [ref], root, relative, style)
                output = result.stdout + result.stderr
                assert result.returncode != 0, f"{root} accepted {ref!r}: {output}"
                assert "third-party action" in output and ref in output, (
                    f"{root} rejected {ref!r} without its diagnostic: {output}"
                )


def assert_quoted_comment_content(run: str, allowed: str) -> None:
    ref = allowed + " #inside"
    for root, relative in ROOTS.items():
        for style in (1, 2):
            result = run_step(run, [ref], root, relative, style)
            output = result.stdout + result.stderr
            assert result.returncode == 1, f"{root} stripped quoted comment content: {output}"
            assert ref in output and "third-party action" in output, output


def assert_text_controls(run: str, allowed: str, banned: str) -> None:
    positive = run_step(run, [allowed], "examples", Path("fixture.md"), 1)
    output = positive.stdout + positive.stderr
    assert positive.returncode == 0, f"non-YAML positive control failed: {output}"
    negative = run_step(run, [banned], "examples", Path("fixture.md"), 1)
    output = negative.stdout + negative.stderr
    assert negative.returncode != 0, f"non-YAML negative control passed: {output}"
    assert banned in output and "third-party action" in output, output


def assert_historical(run: str, cases: list[tuple[str, str]]) -> None:
    labels = [label for label, _ in cases]
    refs = [ref for _, ref in cases]
    for root, relative in ROOTS.items():
        result = run_step(run, refs, root, relative, 0, labels)
        output = result.stdout + result.stderr
        assert result.returncode != 0, f"{root} accepted all three historical refs: {output}"
        assert output.count("::error file=") == len(cases), (
            f"{root} did not diagnose all three historical refs: {output}"
        )
        for label, ref in cases:
            assert label in output or ref in output, (
                f"{root} lost historical case {label!r}: {output}"
            )


def main() -> int:
    run = ci_step()
    allowed = read_corpus("action-pins-allowed.txt")
    banned = read_corpus("action-pins-banned.txt")
    historical = read_history()
    assert allowed, "allowed action-pin corpus is empty"
    assert banned, "banned action-pin corpus is empty"
    assert len(historical) == 3, "the three historical upload steps must remain covered"
    assert_allowed(run, allowed)
    assert_banned(run, banned)
    assert_quoted_comment_content(run, allowed[0])
    assert_text_controls(run, allowed[0], banned[0])
    assert_historical(run, historical)
    print(f"OK: extracted {STEP_NAME!r}; tested {len(ROOTS)} roots, "
          f"{len(allowed)} allowed refs, {len(banned)} rejected refs, and "
          f"{len(historical)} historical failures")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
