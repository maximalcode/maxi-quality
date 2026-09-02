#!/usr/bin/env python3
"""Black box checks for the bounded, versioned guard runtime.

The cases build throwaway Git projects and a throwaway cache.  No consumer
tree or machine level installation is inspected or changed.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RUNTIME = REPO / "scripts" / "quality-runtime.py"
MIGRATE = REPO / "scripts" / "quality-runtime-migrate.py"


def call(*args: str, cwd: Path | None = None, input: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        (sys.executable, *args), cwd=cwd or REPO, input=input,
        capture_output=True, text=True, check=False,
    )


def git(path: Path, *args: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
           "GIT_COMMITTER_NAME": "fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid"}
    return subprocess.run(("git", *args), cwd=path, env=env, capture_output=True, text=True, check=True).stdout.strip()


def project(path: Path) -> None:
    path.mkdir()
    git(path, "init", "--quiet", "--initial-branch=main")
    (path / "README.md").write_text("fixture\n", encoding="utf-8")
    git(path, "add", "-A")
    git(path, "commit", "--quiet", "-m", "base")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="runtime-release-") as temp:
        root = Path(temp)
        target_a = root / "project-a"
        target_b = root / "project-b"
        project(target_a)
        project(target_b)
        (target_b / "samples" / "expected").mkdir(parents=True)
        cache = root / "cache"
        source = root / "release-source"
        (source / "scripts" / "agent-guard").mkdir(parents=True)
        for name in ("guard.py", "stop-gate.py", "sample-guard.py", "no-verify-guard.py", "record-gate.py"):
            shutil.copyfile(REPO / "scripts" / "agent-guard" / name,
                            source / "scripts" / "agent-guard" / name)
        shutil.copyfile(REPO / "scripts" / "quality-runtime.py",
                        source / "scripts" / "quality-runtime.py")
        git(source, "init", "--quiet", "--initial-branch=main")
        git(source, "add", "-A")
        git(source, "commit", "--quiet", "-m", "release")
        head = git(source, "rev-parse", "HEAD")
        git(source, "tag", "v1.2.0")
        (source / "release-note").write_text("second pin\n", encoding="utf-8")
        git(source, "add", "-A")
        git(source, "commit", "--quiet", "-m", "follow-up")
        previous = git(source, "rev-parse", "HEAD")

        # Two immutable pins share one cache without a mutable latest pointer.
        for version, commit in (("v1.2.0", head), ("v1.1.0", previous)):
            prepared = call(str(RUNTIME), "prepare", "--source", str(source), "--version", version,
                            "--commit", commit, "--cache-root", str(cache),
                            "--allow-untagged-development")
            assert prepared.returncode == 0, prepared.stderr
        assert (cache / head / "manifest.json").is_file()
        assert (cache / previous / "manifest.json").is_file()

        # Migration preserves an existing hook and removes the copied guard
        # body.  A second migration produces byte-for-byte identical files.
        settings = target_a / ".claude" / "settings.json"
        settings.parent.mkdir()
        settings.write_text(json.dumps({"custom": {"kept": True}, "hooks": {
            "Stop": [{"hooks": [{"type": "command", "command": "echo own"}]}],
            "PreToolUse": [],
        }}), encoding="utf-8")
        old = target_a / ".claude" / "agent-guard"
        old.mkdir()
        (old / "stop-gate.py").write_text("copied", encoding="utf-8")
        (target_a / "CLAUDE.md").write_text(
            "project prose\n\n<!-- BEGIN maxi-quality agent-guard -->\n"
            "Run the gate:\n\npython3 .claude/agent-guard/record-gate.py --gate\n"
            "<!-- END maxi-quality agent-guard -->\n",
            encoding="utf-8",
        )
        migrated = call(str(MIGRATE), "--target", str(target_a), "--version", "v1.2.0",
                        "--commit", head, "--launcher", str(RUNTIME))
        assert migrated.returncode == 0, migrated.stderr
        first_lock = (target_a / ".claude" / "quality-runtime.json").read_bytes()
        first_settings = settings.read_bytes()
        first_ignore = (target_a / ".gitignore").read_bytes()
        repeated = call(str(MIGRATE), "--target", str(target_a), "--version", "v1.2.0",
                        "--commit", head, "--launcher", str(RUNTIME))
        assert repeated.returncode == 0, repeated.stderr
        assert first_lock == (target_a / ".claude" / "quality-runtime.json").read_bytes()
        assert first_settings == settings.read_bytes()
        assert first_ignore == (target_a / ".gitignore").read_bytes()
        assert ".claude/agent-guard-ledger.jsonl" in first_ignore.decode()
        assert not list((target_a / ".claude" / "agent-guard").glob("*.py")) if (target_a / ".claude" / "agent-guard").exists() else True
        assert json.loads(settings.read_text(encoding="utf-8"))["custom"]["kept"] is True
        instruction = (target_a / "CLAUDE.md").read_text(encoding="utf-8")
        assert "project prose" in instruction
        assert ".claude/agent-guard/record-gate.py" not in instruction
        assert "quality-runtime.py record-gate" in instruction

        # A passing and failing gate, then a stale receipt, are visible through
        # the real Stop hook.  The gate itself runs in the fixture only.
        (target_a / ".claude" / "agent-guard.json").write_text('{"gate_command":"false"}\n', encoding="utf-8")
        failed = call(str(RUNTIME), "record-gate", "--root", str(target_a), "--cache-root", str(cache), "--gate")
        assert failed.returncode != 0
        blocked = call(str(RUNTIME), "stop-gate", "--root", str(target_a), "--cache-root", str(cache), input="{}")
        assert '"decision": "block"' in blocked.stdout
        (target_a / ".claude" / "agent-guard.json").write_text('{"gate_command":"true"}\n', encoding="utf-8")
        passed = call(str(RUNTIME), "record-gate", "--root", str(target_a), "--cache-root", str(cache), "--gate")
        assert passed.returncode == 0, passed.stderr
        assert git(target_a, "check-ignore", ".claude/agent-guard-ledger.jsonl") == ".claude/agent-guard-ledger.jsonl"
        clean = call(str(RUNTIME), "stop-gate", "--root", str(target_a), "--cache-root", str(cache), input="{}")
        assert clean.stdout.strip() == ""
        (target_a / "README.md").write_text("changed\n", encoding="utf-8")
        stale = call(str(RUNTIME), "stop-gate", "--root", str(target_a), "--cache-root", str(cache), input="{}")
        assert '"decision": "block"' in stale.stdout
        stale_reason = json.loads(stale.stdout)["reason"]
        assert "quality-runtime.py" in stale_reason and "record-gate --root" in stale_reason
        assert "python3 python3" not in stale_reason
        repair = next(line.strip() for line in stale_reason.splitlines()
                      if "record-gate --root" in line)
        repaired = subprocess.run(repair, cwd=target_a, shell=True,
                                  capture_output=True, text=True)
        assert repaired.returncode == 0, repaired.stderr

        # Missing cache and corrupted cache remain repairable and do not turn
        # ordinary samples/edit hooks into a universal refusal.
        missing = call(str(RUNTIME), "stop-gate", "--root", str(target_a), "--cache-root", str(root / "none"), input="{}")
        assert '"decision": "block"' in missing.stdout and "prepare" in missing.stdout
        cached_stop = cache / head / "stop-gate.py"
        original = cached_stop.read_bytes()
        cached_stop.write_bytes(b"tampered\n")
        corrupt = call(str(RUNTIME), "stop-gate", "--root", str(target_a), "--cache-root", str(cache), input="{}")
        assert '"decision": "block"' in corrupt.stdout
        cached_stop.write_bytes(original)

        # B can roll back to the other immutable pin and both remain usable.
        rolled = call(str(MIGRATE), "--target", str(target_b), "--version", "v1.1.0",
                      "--commit", previous, "--launcher", str(RUNTIME))
        assert rolled.returncode == 0, rolled.stderr
        settings_b = json.loads((target_b / ".claude" / "settings.json").read_text())
        assert len(settings_b["hooks"]["PreToolUse"]) == 2
        assert json.loads((target_b / ".claude" / "quality-runtime.json").read_text())["commit"] == previous
        status = call(str(RUNTIME), "status", "--root", str(target_b), "--cache-root", str(cache))
        assert status.returncode == 0, status.stderr
    print("runtime-release: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
