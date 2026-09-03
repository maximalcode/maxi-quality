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
        (target_b / ".claude" / "agent-guard.json").write_text(
            '{"gate_command":"true"}\n', encoding="utf-8")
        settings_b = json.loads((target_b / ".claude" / "settings.json").read_text())
        assert len(settings_b["hooks"]["PreToolUse"]) == 2
        assert json.loads((target_b / ".claude" / "quality-runtime.json").read_text())["commit"] == previous
        status = call(str(RUNTIME), "status", "--root", str(target_b), "--cache-root", str(cache))
        assert status.returncode == 0, status.stderr

        # The installation doctor is read-only and observes the actual
        # Adopter wiring.  Its JSON shape is stable and says that a static
        # pass does not prove a live agent session executed anything.
        diagnosis = call(str(RUNTIME), "diagnose", "--root", str(target_b),
                         "--cache-root", str(cache), "--json")
        assert diagnosis.returncode == 0, diagnosis.stderr + diagnosis.stdout
        report = json.loads(diagnosis.stdout)
        assert report["healthy"] is True
        assert report["status"] == "ok"
        assert report["installation_profile"] == "versioned-with-samples"
        assert report["release"]["version"] == "v1.1.0"
        assert report["release"]["commit"] == previous
        assert report["configured_gate"] == "true"
        assert report["live_enforcement"] == "unverified"
        assert report["host_settings"] == "unverified"
        assert all(check["status"] == "pass" for check in report["checks"])

        # Repeated diagnosis is observational: no lock, settings, or cache
        # bytes change.
        before_settings = (target_b / ".claude" / "settings.json").read_bytes()
        before_lock = (target_b / ".claude" / "quality-runtime.json").read_bytes()
        before_manifest = (cache / previous / "manifest.json").read_bytes()
        again = call(str(RUNTIME), "diagnose", "--root", str(target_b),
                     "--cache-root", str(cache), "--json")
        assert again.returncode == 0
        assert before_settings == (target_b / ".claude" / "settings.json").read_bytes()
        assert before_lock == (target_b / ".claude" / "quality-runtime.json").read_bytes()
        assert before_manifest == (cache / previous / "manifest.json").read_bytes()

        unavailable_cache = call(str(RUNTIME), "diagnose", "--root", str(target_b),
                                 "--cache-root", str(root / "missing-cache"), "--json")
        assert unavailable_cache.returncode != 0
        assert any(c["id"] == "runtime-cache" and c["status"] == "fail"
                   for c in json.loads(unavailable_cache.stdout)["checks"])

        readable = call(str(RUNTIME), "diagnose", "--root", str(target_b),
                        "--cache-root", str(cache))
        assert readable.returncode == 0
        assert "versioned-with-samples" in readable.stdout
        assert "live enforcement: unverified" in readable.stdout

        # A profile without samples/expected is a supported workflow-only
        # shape, so its intentionally absent sample protection is skipped.
        no_samples = call(str(RUNTIME), "diagnose", "--root", str(target_a),
                          "--cache-root", str(cache), "--json")
        assert no_samples.returncode == 0, no_samples.stderr
        no_samples_report = json.loads(no_samples.stdout)
        assert no_samples_report["installation_profile"] == "versioned-without-samples"
        assert no_samples_report["healthy"] is True
        sample_check = next(c for c in no_samples_report["checks"] if c["id"] == "sample-protection")
        assert sample_check["status"] == "skip"

        # Narrowing the owned matcher is a wiring failure, even though the
        # hook command and the cached runtime remain valid.
        changed = json.loads((target_b / ".claude" / "settings.json").read_text())
        for group in changed["hooks"]["PreToolUse"]:
            if group.get("matcher") == "Edit|Write|MultiEdit":
                group["matcher"] = "Edit|Write"
        (target_b / ".claude" / "settings.json").write_text(
            json.dumps(changed), encoding="utf-8")
        broken = call(str(RUNTIME), "diagnose", "--root", str(target_b),
                      "--cache-root", str(cache), "--json")
        assert broken.returncode != 0
        broken_report = json.loads(broken.stdout)
        assert broken_report["healthy"] is False
        assert any(c["id"] == "hook-sample-guard" and c["status"] == "fail"
                   for c in broken_report["checks"])

        # Each required seam fails by its own reason and the fixture can be
        # restored without any diagnosis side effects.
        # Re-migrate to restore the owned entries while retaining the target's
        # gate and then exercise a missing deny rule and missing gate.
        restored = call(str(MIGRATE), "--target", str(target_b), "--version", "v1.1.0",
                        "--commit", previous, "--launcher", str(RUNTIME))
        assert restored.returncode == 0, restored.stderr

        malformed = json.loads((target_b / ".claude" / "settings.json").read_text())
        for group in malformed["hooks"]["PreToolUse"]:
            if group.get("matcher") == "Bash":
                group["hooks"][0]["command"] = "echo replaced"
        (target_b / ".claude" / "settings.json").write_text(json.dumps(malformed), encoding="utf-8")
        replaced_hook = call(str(RUNTIME), "diagnose", "--root", str(target_b),
                             "--cache-root", str(cache), "--json")
        assert replaced_hook.returncode != 0
        assert any(c["id"] == "hook-no-verify" and c["status"] == "fail"
                   for c in json.loads(replaced_hook.stdout)["checks"])
        restored = call(str(MIGRATE), "--target", str(target_b), "--version", "v1.1.0",
                        "--commit", previous, "--launcher", str(RUNTIME))
        assert restored.returncode == 0, restored.stderr

        launcher_missing = json.loads((target_b / ".claude" / "settings.json").read_text())
        for group in launcher_missing["hooks"]["Stop"]:
            group["hooks"][0]["command"] = (
                "if [ -f /missing/quality-runtime.py ]; then python3 "
                "/missing/quality-runtime.py stop-gate --root \"${CLAUDE_PROJECT_DIR}\"; fi"
            )
        (target_b / ".claude" / "settings.json").write_text(json.dumps(launcher_missing), encoding="utf-8")
        missing_launcher = call(str(RUNTIME), "diagnose", "--root", str(target_b),
                                "--cache-root", str(cache), "--json")
        assert missing_launcher.returncode != 0
        assert any(c["id"] == "launcher" and c["status"] == "fail"
                   for c in json.loads(missing_launcher.stdout)["checks"])
        restored = call(str(MIGRATE), "--target", str(target_b), "--version", "v1.1.0",
                        "--commit", previous, "--launcher", str(RUNTIME))
        assert restored.returncode == 0, restored.stderr
        current = json.loads((target_b / ".claude" / "settings.json").read_text())
        current["permissions"]["deny"].remove("Edit(/samples/expected/**)")
        (target_b / ".claude" / "settings.json").write_text(json.dumps(current), encoding="utf-8")
        missing_deny = call(str(RUNTIME), "diagnose", "--root", str(target_b),
                            "--cache-root", str(cache), "--json")
        assert missing_deny.returncode != 0
        assert any(c["status"] == "fail" and "samples/expected" in c["detail"]
                   for c in json.loads(missing_deny.stdout)["checks"])
        restored = call(str(MIGRATE), "--target", str(target_b), "--version", "v1.1.0",
                        "--commit", previous, "--launcher", str(RUNTIME))
        assert restored.returncode == 0, restored.stderr
        (target_b / ".claude" / "agent-guard.json").unlink()
        no_gate = call(str(RUNTIME), "diagnose", "--root", str(target_b),
                       "--cache-root", str(cache), "--json")
        assert no_gate.returncode != 0
        assert any(c["id"] == "configured-gate" and c["status"] == "fail"
                   for c in json.loads(no_gate.stdout)["checks"])
        (target_b / ".claude" / "agent-guard.json").write_text(
            '{"gate_command":"true"}\n', encoding="utf-8")

        # An explicitly disabled profile is reported as not enabled, never as
        # enforced.  Migration itself is the only writer in this fixture.
        target_disabled = root / "project-disabled"
        project(target_disabled)
        disabled = call(str(MIGRATE), "--target", str(target_disabled),
                        "--version", "v1.2.0", "--commit", head,
                        "--launcher", str(RUNTIME), "--guard-disabled")
        assert disabled.returncode == 0, disabled.stderr
        disabled_report = call(str(RUNTIME), "diagnose", "--root", str(target_disabled),
                               "--cache-root", str(cache), "--json")
        assert disabled_report.returncode == 0
        disabled_json = json.loads(disabled_report.stdout)
        assert disabled_json["status"] == "not-enabled"
        assert disabled_json["live_enforcement"] == "unverified"

        # Legacy copied and shared installs are migration candidates, not
        # versioned healthy installs.  The classification is based on the
        # actual files and command wiring, and includes the supported seam.
        legacy = root / "legacy"
        project(legacy)
        (legacy / ".claude").mkdir()
        (legacy / ".claude" / "settings.json").write_text(json.dumps({
            "hooks": {"Stop": [{"hooks": [{"type": "command",
                "command": 'python3 "${CLAUDE_PROJECT_DIR}/.claude/agent-guard/stop-gate.py"'}]}]}
        }), encoding="utf-8")
        (legacy / ".claude" / "agent-guard").mkdir()
        (legacy / ".claude" / "agent-guard" / "stop-gate.py").write_text("copied", encoding="utf-8")
        legacy_report = call(str(RUNTIME), "diagnose", "--root", str(legacy), "--json")
        assert legacy_report.returncode == 0
        legacy_json = json.loads(legacy_report.stdout)
        assert legacy_json["status"] == "legacy-copied"
        assert "quality-runtime-migrate.py" in legacy_json["migration"]
    print("runtime-release: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
