#!/usr/bin/env python3
"""Anonymous acceptance tests for scripts/release-refs.py.

The corpus is a small git repository because a release wrapper is a relationship
between two commits, not a property a single YAML file can prove.  Every test
uses synthetic action names and commit data.
"""

from __future__ import annotations

import importlib.util
import pathlib
import subprocess
import sys
import tempfile


ROOT = pathlib.Path(__file__).resolve().parents[2]
CHECKER = ROOT / "scripts/release-refs.py"
PAYLOAD = "a" * 40
OTHER = "b" * 40


def checker_module():
    spec = importlib.util.spec_from_file_location("release_refs_fixture", CHECKER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def run(*args: str, cwd: pathlib.Path, ok: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, cwd=cwd, text=True, capture_output=True)
    if result.returncode != (0 if ok else 1):
        raise AssertionError(
            f"{' '.join(args)} returned {result.returncode}, expected "
            f"{0 if ok else 1}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def write(path: pathlib.Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def reusable(ref: str) -> str:
    return f"""name: sample
on:
  workflow_call:
jobs:
  run:
    steps:
      - uses: maximalcode/maxi-quality/actions/alpha@{ref} # stable label
      - uses: \"maximalcode/maxi-quality/actions/beta@{ref}\"
      - uses: actions/checkout@v4
"""


def make_tree(root: pathlib.Path, ref: str = "v1") -> None:
    write(root / ".github/workflows/quality.yml", reusable(ref))
    write(root / ".github/workflows/quality-report.yaml", reusable(ref))
    # This is intentionally outside the reusable surface: the checker must not
    # rewrite a local test workflow or conflate a consumer's @v1 choice with an
    # internal delivery pin.
    write(root / ".github/workflows/local.yml", reusable(ref).replace("workflow_call:", "push:"))
    # The shell body deliberately contains a complete reusable-workflow
    # fixture. It is data in a local CI workflow, never a release entry point.
    write(root / ".github/workflows/ci.yml", f"""name: CI
on: [push]
jobs:
  fixture:
    runs-on: ubuntu-latest
    steps:
      - run: |
          cat > /tmp/fixture.yml <<'YAML'
          on:
            workflow_call:
          jobs:
            nested:
              uses: maximalcode/maxi-quality/.github/workflows/quality.yml@{ref}
          YAML
""")
    write(root / "notes.txt", "maximalcode/maxi-quality/actions/alpha@v1\n")


def git(root: pathlib.Path, *args: str) -> str:
    return run("git", *args, cwd=root).stdout.strip()


def checker(root: pathlib.Path, *args: str, ok: bool = True) -> subprocess.CompletedProcess[str]:
    return run(sys.executable, str(CHECKER), "--root", str(root), *args, cwd=root, ok=ok)


def main() -> int:
    release_refs = checker_module()
    assert release_refs.is_reusable_workflow("on: # reusable entry point\n  workflow_call:\n")
    assert release_refs.is_reusable_workflow("on: {workflow_call: {}}\n")
    with tempfile.TemporaryDirectory(prefix="release-refs-") as temporary:
        root = pathlib.Path(temporary)
        make_tree(root)

        # List sees every supported spelling in BOTH public reusable workflows,
        # and none from the local workflow/comment-like text.
        listed = checker(root, "list").stdout.splitlines()
        assert len(listed) == 4, listed
        assert all("local.yml" not in line and "ci.yml" not in line and "notes.txt" not in line for line in listed)
        checker(root, "check", ok=False)

        # YAML allows flow triggers, quoted keys, and folded scalar values. The
        # tool need not rewrite every spelling, but it must fail closed rather
        # than certify a first-party ref that its line-preserving grammar did
        # not see.
        write(root / ".github/workflows/folded.yml", """on: [workflow_call]
jobs:
  sample:
    steps:
      - \"uses\": maximalcode/maxi-quality/actions/alpha@v1
      - uses: >-
          maximalcode/maxi-quality/actions/beta@v1
""")
        unsupported = checker(root, "check", ok=False)
        assert "unsupported first-party uses syntax" in unsupported.stderr
        (root / ".github/workflows/folded.yml").unlink()

        before_local = (root / ".github/workflows/local.yml").read_bytes()
        before_ci = (root / ".github/workflows/ci.yml").read_bytes()
        before_notes = (root / "notes.txt").read_bytes()
        checker(root, "rewrite", "--payload", PAYLOAD)
        assert (root / ".github/workflows/local.yml").read_bytes() == before_local
        assert (root / ".github/workflows/ci.yml").read_bytes() == before_ci
        assert (root / "notes.txt").read_bytes() == before_notes
        checker(root, "check")

        # The wrapper proof needs an actual preceding commit. Its payload
        # contains a recursive first-party action reference so this also proves
        # the walk does not stop at quality.yml. A nested payload reference is
        # immutable but need not equal its containing commit (a git commit
        # cannot know its own SHA before it exists).
        git(root, "init", "-q")
        git(root, "config", "user.name", "fixture")
        git(root, "config", "user.email", "fixture@example.invalid")
        write(root / "actions/alpha/action.yml", f"runs:\n  using: composite\n  steps:\n    - uses: maximalcode/maxi-quality/actions/beta@{PAYLOAD}\n")
        write(root / "actions/beta/action.yml", "runs:\n  using: composite\n  steps: []\n")
        write(root / "scripts/run.sh", "#!/usr/bin/env bash\ntrue\n")
        write(root / "semgrep/rule.yml", "rules: []\n")
        git(root, "add", ".")
        git(root, "commit", "-qm", "base payload")
        base_payload = git(root, "rev-parse", "HEAD")
        alpha = root / "actions/alpha/action.yml"
        alpha.write_text(alpha.read_text().replace(PAYLOAD, base_payload))
        git(root, "add", "actions/alpha/action.yml")
        git(root, "commit", "-qm", "payload")
        actual_payload = git(root, "rev-parse", "HEAD")
        checker(root, "rewrite", "--payload", actual_payload)
        checker(root, "check", "--payload", actual_payload)
        # A single stale immutable pin is a failure when a wrapper declares
        # one payload; full SHAs alone are not sufficient.
        report = root / ".github/workflows/quality-report.yaml"
        report.write_text(report.read_text().replace(actual_payload, OTHER, 1))
        mismatch = checker(root, "check", "--payload", actual_payload, ok=False)
        assert "does not target payload" in mismatch.stderr
        checker(root, "rewrite", "--payload", actual_payload)
        checker(root, "record", "--payload", actual_payload)
        git(root, "add", ".github/workflows", "release-payload.sha")
        git(root, "commit", "-qm", "wrapper")
        checker(root, "verify-wrapper")

        # Configuration is delivery payload too: scripts/policy.py reads it at
        # consumer runtime, so a wrapper cannot change it under an old record.
        wrapper = git(root, "rev-parse", "HEAD")
        git(root, "checkout", "-qb", "bad-config", wrapper)
        write(root / "configs/runtime.txt", "changed\n")
        git(root, "add", "configs/runtime.txt")
        git(root, "commit", "-qm", "changed config")
        bad_config = checker(root, "verify-wrapper", ok=False)
        assert "executable payload" in bad_config.stderr
        git(root, "checkout", "--detach", "-q", wrapper)

        # GitHub validates a synthetic PR merge, then promotion produces a
        # second merge on main. P is not the direct parent in either case, so
        # the verifier must use ancestry and compare the release revision's
        # tree through git plumbing.
        git(root, "checkout", "-qb", "develop", actual_payload)
        git(root, "merge", "--no-ff", "-qm", "merge wrapper", wrapper)
        checker(root, "verify-wrapper", "--revision", "HEAD")
        git(root, "branch", "-f", "main", actual_payload)
        git(root, "checkout", "-q", "main")
        git(root, "merge", "--no-ff", "-qm", "promote wrapper", "develop")
        checker(root, "verify-wrapper", "--revision", "HEAD")

        # A later release revision that changes a shipped script cannot certify
        # the old payload, even though all its workflow refs are full SHAs.
        write(root / "scripts/run.sh", "#!/usr/bin/env bash\necho changed\n")
        git(root, "add", "scripts/run.sh")
        git(root, "commit", "-qm", "changed payload")
        bad = checker(root, "verify-wrapper", ok=False)
        assert "executable payload" in bad.stderr

    print("OK: release-reference fixture covers discovery, rewrite, payload matching, and closure")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
