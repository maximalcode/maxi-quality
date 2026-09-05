#!/usr/bin/env python3
"""Black box checks for the bounded, versioned guard runtime.

The cases build throwaway Git projects and a throwaway cache.  No consumer
tree or machine level installation is inspected or changed.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RUNTIME = REPO / "scripts" / "quality-runtime.py"
MIGRATE = REPO / "scripts" / "quality-runtime-migrate.py"


def call(*args: str, cwd: Path | None = None, input: str = "",
         env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        (sys.executable, *args), cwd=cwd or REPO, input=input,
        capture_output=True, text=True, check=False, env=env,
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


def launcher_roundtrips(root: Path, commit: str, cache: Path) -> None:
    """Migration, diagnosis and the host shell agree on supported launchers."""
    target = root / "launcher project with spaces"
    project(target)
    home = root / "fixture-home"
    bin_dir = home / ".local" / "bin"
    bin_dir.mkdir(parents=True)
    launchers = (
        (str(bin_dir / "custom-runtime.py"), bin_dir / "custom-runtime.py"),
        (str(bin_dir / "custom executable"), bin_dir / "custom executable"),
        ("quality-runtime.py", target / "quality-runtime.py"),
        ("qr.py", target / "qr.py"),
        ("qr", bin_dir / "qr"),
        ("quality-runtime", bin_dir / "quality-runtime"),
    )
    env = {**os.environ, "HOME": str(home), "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
           "CLAUDE_PROJECT_DIR": str(target), "MAXI_QUALITY_RUNTIME_CACHE": str(cache)}
    failures = []
    for spelling, destination in launchers:
        shutil.copyfile(RUNTIME, destination)
        destination.chmod(0o755)
        migrated = call(str(MIGRATE), "--target", str(target), "--version", "v1.2.0",
                        "--commit", commit, "--launcher", spelling)
        assert migrated.returncode == 0, migrated.stderr
        (target / ".claude" / "agent-guard.json").write_text('{"gate_command":"false"}')
        diagnosed = call(str(RUNTIME), "diagnose", "--root", str(target), "--json", env=env)
        if diagnosed.returncode != 0:
            failures.append(spelling + ": " + diagnosed.stdout)
        settings = json.loads((target / ".claude" / "settings.json").read_text())
        command = next(entry["command"] for group in settings["hooks"]["PreToolUse"]
                       if group.get("matcher") == "Bash" for entry in group["hooks"])
        invoked = subprocess.run(command, shell=True, cwd=target, env=env,
                                 input='{"tool_name":"Bash","tool_input":{"command":"git commit --no-verify"}}',
                                 capture_output=True, text=True)
        assert invoked.returncode == 0, (spelling, invoked.stderr)
        assert json.loads(invoked.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert "unavailable" not in invoked.stdout, (spelling, invoked.stdout)
    assert not failures, "Generated launcher roundtrips failed: " + "\n".join(failures)


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
        # A shared launcher serves guard releases whose launcher sources
        # differ, including an otherwise harmless comment-only change.
        with (source / "scripts" / "quality-runtime.py").open("a") as stream:
            stream.write("\n# A different launcher source in this release.\n")
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
        launcher_roundtrips(root, head, cache)

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

        # Existing format-1 caches survive a launcher upgrade. Status,
        # dispatch and repeated prepare use the same immutable directory.
        manifest_path = cache / previous / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["format"] = 1
        manifest.pop("launcher_sha256", None)
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        old_cache = {p: p.read_bytes() for p in (cache / previous).iterdir() if p.is_file()}
        compatible = call(str(RUNTIME), "status", "--root", str(target_b),
                          "--cache-root", str(cache))
        assert compatible.returncode == 0, compatible.stderr
        dispatched = call(str(RUNTIME), "no-verify-guard", "--root", str(target_b),
                          "--cache-root", str(cache),
                          input='{"tool_name":"Bash","tool_input":{"command":"git commit --no-verify"}}')
        assert '"permissionDecision": "deny"' in dispatched.stdout
        assert "unavailable" not in dispatched.stdout
        prepared_again = call(str(RUNTIME), "prepare", "--source", str(source),
                              "--version", "v1.1.0", "--commit", previous,
                              "--cache-root", str(cache), "--allow-untagged-development")
        assert prepared_again.returncode == 0, prepared_again.stderr
        assert old_cache == {p: p.read_bytes() for p in (cache / previous).iterdir() if p.is_file()}

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

        # Project-level hook disabling invalidates an otherwise complete
        # installation.  The host setting is part of the owned wiring
        # contract, so a static pass must not claim this guard is healthy.
        disabled_hooks = json.loads((target_b / ".claude" / "settings.json").read_text())
        disabled_hooks["disableAllHooks"] = True
        (target_b / ".claude" / "settings.json").write_text(
            json.dumps(disabled_hooks), encoding="utf-8")
        hooks_disabled = call(str(RUNTIME), "diagnose", "--root", str(target_b),
                              "--cache-root", str(cache), "--json")
        assert hooks_disabled.returncode != 0
        assert any(c["id"] == "hooks-enabled" and c["status"] == "fail"
                   for c in json.loads(hooks_disabled.stdout)["checks"])
        disabled_hooks["disableAllHooks"] = False
        (target_b / ".claude" / "settings.json").write_text(
            json.dumps(disabled_hooks), encoding="utf-8")
        restored = call(str(MIGRATE), "--target", str(target_b), "--version", "v1.1.0",
                        "--commit", previous, "--launcher", str(RUNTIME))
        assert restored.returncode == 0, restored.stderr

        # Hook execution metadata is part of the contract.  Stop decisions
        # cannot be enforced by an asynchronous hook.
        async_stop = json.loads((target_b / ".claude" / "settings.json").read_text())
        for group in async_stop["hooks"]["Stop"]:
            for entry in group["hooks"]:
                if entry.get("command"):
                    entry["async"] = True
        (target_b / ".claude" / "settings.json").write_text(
            json.dumps(async_stop), encoding="utf-8")
        async_report = call(str(RUNTIME), "diagnose", "--root", str(target_b),
                            "--cache-root", str(cache), "--json")
        assert async_report.returncode != 0
        assert any(c["id"] == "hook-execution-mode" and c["status"] == "fail"
                   for c in json.loads(async_report.stdout)["checks"])
        restored = call(str(MIGRATE), "--target", str(target_b), "--version", "v1.1.0",
                        "--commit", previous, "--launcher", str(RUNTIME))
        assert restored.returncode == 0, restored.stderr

        # A comment can hide every required invocation while leaving all of
        # the expected words in the JSON.  Diagnosis must parse the executable
        # branch rather than search for launcher and guard substrings.
        commented = json.loads((target_b / ".claude" / "settings.json").read_text())
        for groups in commented["hooks"].values():
            for group in groups:
                for entry in group.get("hooks", []):
                    if isinstance(entry, dict) and "quality-runtime" in entry.get("command", ""):
                        entry["command"] = "true # " + entry["command"]
        (target_b / ".claude" / "settings.json").write_text(
            json.dumps(commented), encoding="utf-8")
        commented_report = call(str(RUNTIME), "diagnose", "--root", str(target_b),
                                "--cache-root", str(cache), "--json")
        assert commented_report.returncode != 0
        commented_checks = json.loads(commented_report.stdout)["checks"]
        assert any(check["status"] == "fail" and check["id"].startswith("hook-")
                   for check in commented_checks)
        restored = call(str(MIGRATE), "--target", str(target_b), "--version", "v1.1.0",
                        "--commit", previous, "--launcher", str(RUNTIME))
        assert restored.returncode == 0, restored.stderr

        # An echo wrapper only prints the required command and never invokes
        # it.  This is a changed owned hook even when its text is otherwise
        # plausible.
        echoed = json.loads((target_b / ".claude" / "settings.json").read_text())
        echoed["hooks"]["Stop"][0]["hooks"][0]["command"] = (
            "echo python3 " + str(RUNTIME) +
            ' stop-gate --root "${CLAUDE_PROJECT_DIR}"'
        )
        (target_b / ".claude" / "settings.json").write_text(
            json.dumps(echoed), encoding="utf-8")
        echoed_report = call(str(RUNTIME), "diagnose", "--root", str(target_b),
                             "--cache-root", str(cache), "--json")
        assert echoed_report.returncode != 0
        assert any(c["id"] == "hook-stop-gate" and c["status"] == "fail"
                   for c in json.loads(echoed_report.stdout)["checks"])
        restored = call(str(MIGRATE), "--target", str(target_b), "--version", "v1.1.0",
                        "--commit", previous, "--launcher", str(RUNTIME))
        assert restored.returncode == 0, restored.stderr

        # A complete-looking invocation is not owned when shell control flow
        # makes its branch unreachable, or when the expected words only occur
        # as an argument to another command.  Each mutation uses an existing
        # launcher so this exercises parsing independently from availability.
        control_flow_cases = (
            "python3 " + str(RUNTIME)
            + " stop-gate --root '${CLAUDE_PROJECT_DIR}'"
            + ' # --root "${CLAUDE_PROJECT_DIR}"',
            "if false; then python3 " + str(RUNTIME)
            + ' stop-gate --root "${CLAUDE_PROJECT_DIR}"; fi',
            "exit 0; if [ -f /missing/path ]; then python3 " + str(RUNTIME)
            + ' stop-gate --root "${CLAUDE_PROJECT_DIR}"; fi',
            "echo then python3 " + str(RUNTIME)
            + ' stop-gate --root "${CLAUDE_PROJECT_DIR}"',
        )
        for command in control_flow_cases:
            control_flow = json.loads((target_b / ".claude" / "settings.json").read_text())
            control_flow["hooks"]["Stop"][0]["hooks"][0]["command"] = command
            (target_b / ".claude" / "settings.json").write_text(
                json.dumps(control_flow), encoding="utf-8")
            control_report = call(str(RUNTIME), "diagnose", "--root", str(target_b),
                                  "--cache-root", str(cache), "--json")
            assert control_report.returncode != 0
            assert any(c["id"] == "hook-stop-gate" and c["status"] == "fail"
                       for c in json.loads(control_report.stdout)["checks"])
            restored = call(str(MIGRATE), "--target", str(target_b), "--version", "v1.1.0",
                            "--commit", previous, "--launcher", str(RUNTIME))
            assert restored.returncode == 0, restored.stderr

        # An unrelated executable must not qualify as the runtime merely
        # because the generated command shape points at it.  The check is
        # static and therefore does not execute /usr/bin/true.
        wrong_launcher = json.loads((target_b / ".claude" / "settings.json").read_text())
        wrong_launcher["hooks"]["Stop"][0]["hooks"][0]["command"] = (
            'if [ -f /usr/bin/true ]; then /usr/bin/true stop-gate --root '
            '"${CLAUDE_PROJECT_DIR}"; fi'
        )
        (target_b / ".claude" / "settings.json").write_text(
            json.dumps(wrong_launcher), encoding="utf-8")
        wrong_launcher_report = call(str(RUNTIME), "diagnose", "--root", str(target_b),
                                     "--cache-root", str(cache), "--json")
        assert wrong_launcher_report.returncode != 0
        assert any(c["id"] == "launcher" and c["status"] == "fail"
                   for c in json.loads(wrong_launcher_report.stdout)["checks"])
        restored = call(str(MIGRATE), "--target", str(target_b), "--version", "v1.1.0",
                        "--commit", previous, "--launcher", str(RUNTIME))
        assert restored.returncode == 0, restored.stderr

        # Every owned hook needs a usable launcher.  A missing Bash launcher
        # must fail even when the Stop launcher is still present.
        missing_bash = json.loads((target_b / ".claude" / "settings.json").read_text())
        for group in missing_bash["hooks"]["PreToolUse"]:
            if group.get("matcher") == "Bash":
                group["hooks"][0]["command"] = (
                    "if [ -f /definitely-missing/quality-runtime.py ]; then python3 "
                    "/definitely-missing/quality-runtime.py no-verify-guard --root "
                    '"${CLAUDE_PROJECT_DIR}"; fi'
                )
        (target_b / ".claude" / "settings.json").write_text(
            json.dumps(missing_bash), encoding="utf-8")
        missing_bash_report = call(str(RUNTIME), "diagnose", "--root", str(target_b),
                                   "--cache-root", str(cache), "--json")
        assert missing_bash_report.returncode != 0
        assert any(c["id"] == "launcher" and c["status"] == "fail"
                   and "definitely-missing" in c["detail"]
                   for c in json.loads(missing_bash_report.stdout)["checks"])
        restored = call(str(MIGRATE), "--target", str(target_b), "--version", "v1.1.0",
                        "--commit", previous, "--launcher", str(RUNTIME))
        assert restored.returncode == 0, restored.stderr

        # A custom executable installed into an explicit bin directory is a
        # supported launcher spelling and must diagnose through that entrypoint.
        custom_bin = root / "custom-bin"
        installed = call(str(RUNTIME), "install", "--source", str(source),
                         "--commit", previous, "--install-root", str(custom_bin))
        assert installed.returncode == 0, installed.stderr
        custom_launcher = custom_bin / "quality-runtime"
        migrated_custom = call(str(MIGRATE), "--target", str(target_b),
                               "--version", "v1.1.0", "--commit", previous,
                               "--launcher", str(custom_launcher))
        assert migrated_custom.returncode == 0, migrated_custom.stderr
        custom_report = call(str(custom_launcher), "diagnose", "--root", str(target_b),
                             "--cache-root", str(cache), "--json")
        assert custom_report.returncode == 0, custom_report.stderr + custom_report.stdout
        assert json.loads(custom_report.stdout)["healthy"] is True

        # Shell-significant newlines and single quotes must not be erased by
        # diagnosis.  Both mutations leave plausible launcher words behind,
        # but the shell either runs two commands or passes a literal root.
        settings_path_b = target_b / ".claude" / "settings.json"
        original_settings_b = settings_path_b.read_bytes()
        for malformed_command in (
            "python3 " + str(custom_launcher)
            + '\nstop-gate --root "${CLAUDE_PROJECT_DIR}"',
            "python3 " + str(custom_launcher)
            + " stop-gate --root '${CLAUDE_PROJECT_DIR}'",
            "python3 " + str(custom_launcher)
            + " stop-gate --root '${CLAUDE_PROJECT_DIR}'"
            + ' # --root "${CLAUDE_PROJECT_DIR}"',
        ):
            malformed = json.loads(original_settings_b)
            for group in malformed["hooks"]["Stop"]:
                for entry in group.get("hooks", []):
                    if isinstance(entry, dict) and entry.get("command"):
                        entry["command"] = malformed_command
            (target_b / ".claude" / "settings.json").write_text(
                json.dumps(malformed), encoding="utf-8")
            malformed_report = call(str(custom_launcher), "diagnose", "--root", str(target_b),
                                    "--cache-root", str(cache), "--json")
            assert malformed_report.returncode != 0
            assert any(c["id"] == "hook-stop-gate" and c["status"] == "fail"
                       for c in json.loads(malformed_report.stdout)["checks"])
            settings_path_b.write_bytes(original_settings_b)

        for direct in (
            shlex.quote(str(custom_launcher)) + ' stop-gate --root "${CLAUDE_PROJECT_DIR}"',
            "python3 " + shlex.quote(str(custom_launcher)) + ' stop-gate --root "${CLAUDE_PROJECT_DIR}"',
        ):
            direct_settings = json.loads(original_settings_b)
            direct_settings["hooks"]["Stop"][0]["hooks"][0]["command"] = direct
            settings_path_b.write_text(json.dumps(direct_settings))
            direct_report = call(str(custom_launcher), "diagnose", "--root", str(target_b),
                                 "--cache-root", str(cache), "--json")
            assert direct_report.returncode == 0, direct_report.stdout
        settings_path_b.write_bytes(original_settings_b)

        # A syntactically plausible copy that does not dispatch when invoked
        # is not a trusted launcher.  Diagnosis must inspect identity without
        # executing this candidate.
        hollow_bin = root / "hollow-bin"
        hollow_bin.mkdir()
        hollow_launcher = hollow_bin / "quality-runtime"
        hollow_source = custom_launcher.read_text(encoding="utf-8")
        hollow_source = hollow_source.split("if __name__ == \"__main__\":", 1)[0]
        executed_marker = root / "candidate-was-executed"
        hollow_source += "\nPath(" + repr(str(executed_marker)) + ").write_text('executed')\n"
        hollow_launcher.write_text(hollow_source, encoding="utf-8")
        hollow_launcher.chmod(0o755)
        hollow_migrated = call(str(MIGRATE), "--target", str(target_b),
                               "--version", "v1.1.0", "--commit", previous,
                               "--launcher", str(hollow_launcher))
        assert hollow_migrated.returncode == 0, hollow_migrated.stderr
        hollow_report = call(str(custom_launcher), "diagnose", "--root", str(target_b),
                             "--cache-root", str(cache), "--json")
        assert hollow_report.returncode != 0
        assert not executed_marker.exists(), "diagnosis executed the candidate launcher"
        assert any(c["id"] == "launcher" and c["status"] == "fail"
                   for c in json.loads(hollow_report.stdout)["checks"])
        restored = call(str(MIGRATE), "--target", str(target_b),
                        "--version", "v1.1.0", "--commit", previous,
                        "--launcher", str(custom_launcher))
        assert restored.returncode == 0, restored.stderr

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

        # A workflow-only profile may still carry unrelated policy. Invalid
        # JSON is a configuration failure even when the guard is disabled.
        disabled_settings = target_disabled / ".claude" / "settings.json"
        unrelated = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo own"}]}]},
                     "permissions": {"deny": ["Edit(/unrelated/**)"]}}
        disabled_settings.write_text(json.dumps(unrelated))
        unrelated_bytes = disabled_settings.read_bytes()
        unrelated_report = call(str(RUNTIME), "diagnose", "--root", str(target_disabled), "--json")
        assert unrelated_report.returncode == 0, unrelated_report.stdout
        assert disabled_settings.read_bytes() == unrelated_bytes
        disabled_settings.write_text("{")
        invalid_disabled = call(str(RUNTIME), "diagnose", "--root", str(target_disabled), "--json")
        assert invalid_disabled.returncode != 0
        assert any(c["id"] == "settings-json" and c["status"] == "fail"
                   for c in json.loads(invalid_disabled.stdout)["checks"])
        disabled_settings.write_bytes(unrelated_bytes)

        # Disabling a previously enabled lock does not remove its hooks.
        # Diagnosis must report the inconsistent profile without repairing it.
        for launcher in (str(RUNTIME), "legacy"):
            if launcher == "legacy":
                residue = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command":
                    'python3 "${CLAUDE_PROJECT_DIR}/.claude/agent-guard/stop-gate.py"'}]}]}}
                (target_disabled / ".claude" / "settings.json").write_text(json.dumps(residue))
            else:
                enabled = call(str(MIGRATE), "--target", str(target_disabled),
                               "--version", "v1.2.0", "--commit", head, "--launcher", launcher)
                assert enabled.returncode == 0, enabled.stderr
                disabled = call(str(MIGRATE), "--target", str(target_disabled),
                                "--version", "v1.2.0", "--commit", head, "--guard-disabled")
                assert disabled.returncode == 0, disabled.stderr
            before_disabled = {p: p.read_bytes() for p in (target_disabled / ".claude").rglob("*") if p.is_file()}
            residual_report = call(str(RUNTIME), "diagnose", "--root", str(target_disabled),
                                   "--cache-root", str(cache), "--json")
            assert residual_report.returncode != 0, residual_report.stdout
            residual_json = json.loads(residual_report.stdout)
            assert residual_json["healthy"] is False
            assert residual_json["installation_profile"] == "disabled"
            assert any(c["id"] == "disabled-hook-wiring" and c["status"] == "fail"
                       for c in residual_json["checks"])
            assert before_disabled == {p: p.read_bytes() for p in (target_disabled / ".claude").rglob("*") if p.is_file()}

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
        (legacy / ".claude" / "agent-guard" / "shim.py").write_text("shared fixture")
        shared_report = call(str(RUNTIME), "diagnose", "--root", str(legacy), "--json")
        assert shared_report.returncode == 0
        shared_json = json.loads(shared_report.stdout)
        assert shared_json["status"] == "legacy-shared"
        assert shared_json["healthy"] is False
        assert "quality-runtime-migrate.py" in shared_json["migration"]
    print("runtime-release: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
