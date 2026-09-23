#!/usr/bin/env python3
"""Codex native-hook protocol and adoption fixtures; no live-host claim."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PATCH = REPO / "scripts/agent-guard/codex-patch-guard.py"


def call(script: Path, *args: str, cwd: Path, payload: object = None,
         env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run((sys.executable, str(script), *args), cwd=cwd,
                          input=json.dumps(payload), text=True, capture_output=True, env=env)


def git(root: Path, *args: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
           "GIT_COMMITTER_NAME": "fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid"}
    return subprocess.run(("git", "-C", str(root), *args), env=env,
                          text=True, capture_output=True, check=True).stdout.strip()


def event(root: Path, patch: str) -> dict:
    return {"cwd": str(root), "hook_event_name": "PreToolUse", "session_id": "fixture",
            "turn_id": "turn-1", "tool_use_id": "tool-1", "tool_name": "apply_patch",
            "tool_input": {"command": patch}}


def patch_verdict(root: Path, patch: str, denied: bool, reason: str = "") -> None:
    result = call(PATCH, cwd=root, payload=event(root, patch))
    assert result.returncode == 0, result.stderr
    verdict = json.loads(result.stdout) if result.stdout.strip() else {}
    output = verdict.get("hookSpecificOutput", {})
    assert (output.get("permissionDecision") == "deny") == denied, result.stdout
    if denied:
        assert reason in output["permissionDecisionReason"], result.stdout


def native_installation(root: Path) -> None:
    source = root / "release-source"
    guards = source / "scripts/agent-guard"
    guards.mkdir(parents=True)
    for name in ("guard.py", "sample-guard.py", "stop-gate.py", "no-verify-guard.py", "record-gate.py"):
        shutil.copyfile(REPO / "scripts/agent-guard" / name, guards / name)
    git(source, "init", "--quiet")
    git(source, "add", "-A")
    git(source, "commit", "--quiet", "-m", "old release")
    old = git(source, "rev-parse", "HEAD")
    shutil.copyfile(PATCH, guards / PATCH.name)
    git(source, "add", "-A")
    git(source, "commit", "--quiet", "-m", "native Codex release")
    current = git(source, "rev-parse", "HEAD")
    runtime = REPO / "scripts/quality-runtime.py"
    migration = REPO / "scripts/quality-runtime-migrate.py"
    cache = root / "cache"
    env = {**os.environ, "MAXI_QUALITY_RUNTIME_CACHE": str(cache)}
    for version, commit in (("v1.0.0", old), ("v1.1.0", current)):
        prepared = call(runtime, "prepare", "--source", str(source), "--version", version,
                        "--commit", commit, "--allow-untagged-development", cwd=root, env=env)
        assert prepared.returncode == 0, prepared.stderr
    target = root / "project with spaces"
    target.mkdir()
    git(target, "init", "--quiet")
    (target / ".claude").mkdir()
    claude_settings = target / ".claude/settings.json"
    claude_settings.write_text('{"custom":"keep Claude untouched"}\n')
    (target / "AGENTS.md").write_text("Existing project instructions.\n")
    before_claude = claude_settings.read_bytes()
    args = ("--target", str(target), "--version", "v1.1.0", "--commit", current,
            "--launcher", str(runtime), "--host", "codex")
    adopted = call(migration, *args, cwd=root, env=env)
    assert adopted.returncode == 0, adopted.stderr
    assert claude_settings.read_bytes() == before_claude
    hooks_path = target / ".codex/hooks.json"
    first = hooks_path.read_bytes()
    assert "permissions" not in json.loads(first)
    repeated = call(migration, *args, cwd=root, env=env)
    assert repeated.returncode == 0, repeated.stderr
    assert hooks_path.read_bytes() == first
    (target / ".claude/agent-guard.json").write_text('{"gate_command":"true"}')
    diagnosed = call(runtime, "diagnose", "--root", str(target), "--host", "codex", "--json", cwd=root, env=env)
    assert diagnosed.returncode == 0, diagnosed.stdout + diagnosed.stderr
    report = json.loads(diagnosed.stdout)
    assert report["host"] == "codex" and report["healthy"] is True
    assert report["live_enforcement"] == "unverified"
    assert report["host_settings"] == "unverified"
    assert (target / "AGENTS.md").read_text().startswith("Existing project instructions.")
    assert "record-gate" in (target / "AGENTS.md").read_text()
    implicit_root = call(runtime, "diagnose", "--host", "codex", "--json", cwd=target,
                         env={**env, "CLAUDE_PROJECT_DIR": str(root / "wrong")})
    assert implicit_root.returncode == 0, implicit_root.stdout + implicit_root.stderr
    # Exercise the emitted commands through the same shell interface the host
    # uses, started below the Git root. No Claude env is needed or trusted.
    subdir = target / "nested"
    subdir.mkdir()
    env["CLAUDE_PROJECT_DIR"] = str(root / "wrong-project")
    hooks = json.loads(first)["hooks"]
    def invoke(event_name: str, matcher: str | None, payload: dict) -> dict:
        command = next(entry["command"] for group in hooks[event_name]
                       if group.get("matcher") == matcher for entry in group["hooks"])
        result = subprocess.run(command, shell=True, cwd=subdir, env=env,
                                input=json.dumps(payload), text=True, capture_output=True)
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout) if result.stdout.strip() else {}
    payload = {"cwd": str(subdir), "session_id": "native", "turn_id": "roundtrip",
               "tool_name": "Bash", "tool_input": {"command": "git commit --no-verify"}}
    assert invoke("PreToolUse", "Bash", payload)["hookSpecificOutput"]["permissionDecision"] == "deny"
    payload["tool_input"]["command"] = "git status --short"
    assert invoke("PreToolUse", "Bash", payload) == {}
    denied = invoke("PreToolUse", "apply_patch", event(subdir,
                    "*** Begin Patch\n*** Add File: ../.claude/agent-guard-receipt.json\n+{}\n*** End Patch"))
    assert denied["hookSpecificOutput"]["permissionDecision"] == "deny"
    allowed = invoke("PreToolUse", "apply_patch", event(subdir,
                     "*** Begin Patch\n*** Add File: new.txt\n+ordinary work\n*** End Patch"))
    assert allowed == {}
    git(target, "add", "-A")
    git(target, "commit", "--quiet", "-m", "configured project")
    (target / "work.txt").write_text("new work\n")
    stop = {"cwd": str(subdir), "hook_event_name": "Stop", "session_id": "native", "turn_id": "stop"}
    assert invoke("Stop", None, stop)["decision"] == "block"
    recorded = call(runtime, "record-gate", "--root", str(target), "--gate", cwd=subdir, env=env)
    assert recorded.returncode == 0, recorded.stderr
    assert invoke("Stop", None, stop) == {}
    (target / "work.txt").write_text("later work\n")
    assert invoke("Stop", None, stop)["decision"] == "block"
    # Old pins remain exact format-1 releases and can still run Claude's guard;
    # requesting the absent native adapter is a denial, not an unchecked patch.
    assert json.loads((cache / old / "manifest.json").read_text())["format"] == 1
    assert json.loads((cache / current / "manifest.json").read_text())["format"] == 2
    before = {p: p.read_bytes() for p in (cache / old).iterdir() if p.is_file()}
    old_args = ("--target", str(target), "--version", "v1.0.0", "--commit", old,
                "--launcher", str(runtime), "--host", "codex")
    assert call(migration, *old_args, cwd=root, env=env).returncode == 0
    absent = call(runtime, "codex-patch-guard", "--root", str(target), cwd=root, env=env,
                  payload=event(target, "*** Begin Patch\n*** Add File: ordinary.txt\n+safe\n*** End Patch"))
    assert json.loads(absent.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"
    legacy = call(runtime, "no-verify-guard", "--root", str(target), cwd=root, env=env,
                  payload={"tool_name": "Bash", "tool_input": {"command": "git commit --no-verify"}})
    assert json.loads(legacy.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert before == {p: p.read_bytes() for p in (cache / old).iterdir() if p.is_file()}
    # An extra file cannot upgrade a format-1 manifest into native support.
    stray = cache / old / PATCH.name
    shutil.copyfile(PATCH, stray)
    old_diagnosis = call(runtime, "diagnose", "--root", str(target), "--host", "codex", "--json", cwd=root, env=env)
    assert old_diagnosis.returncode == 1, old_diagnosis.stdout
    assert any(c["id"] == "codex-runtime" and c["status"] == "fail" for c in json.loads(old_diagnosis.stdout)["checks"])
    stray.unlink()
    assert call(migration, *args, cwd=root, env=env).returncode == 0
    config = target / ".codex/config.toml"
    config.write_text("[features]\nhooks = false\n")
    disabled = call(runtime, "diagnose", "--root", str(target), "--host", "codex", "--json", cwd=root, env=env)
    assert disabled.returncode == 1, disabled.stdout + disabled.stderr
    assert any(c["id"] == "hooks-enabled" and c["status"] == "fail" for c in json.loads(disabled.stdout)["checks"])
    # Installing Claude after Codex also preserves the native Codex config.
    native_before = hooks_path.read_bytes()
    claude = call(migration, "--target", str(target), "--version", "v1.1.0", "--commit", current,
                  "--launcher", str(runtime), "--host", "claude", cwd=root, env=env)
    assert claude.returncode == 0, claude.stderr
    assert hooks_path.read_bytes() == native_before
    assert json.loads(claude_settings.read_text())["permissions"]["deny"] == ["Edit(/.claude/agent-guard-receipt.json)"]
    # A mismatched matcher must not pass diagnosis merely because the command
    # text exists elsewhere in the same file.
    config.unlink()
    broken = json.loads(first)
    broken["hooks"]["PreToolUse"][0]["matcher"] = "Read"
    hooks_path.write_text(json.dumps(broken))
    invalid = call(runtime, "diagnose", "--root", str(target), "--host", "codex", "--json", cwd=root, env=env)
    assert invalid.returncode == 1
    assert any(c["id"] == "hook-codex-patch" and c["status"] == "fail" for c in json.loads(invalid.stdout)["checks"])


def patch_edges(root: Path) -> None:
    bad = [
        ("*** Delete File: samples/bad.txt", "removes 2 line"),
        ("*** Add File: samples/bad.txt\n+one", "removes 1 line"),
        ("*** Update File: samples/bad.txt\n*** Move to: moved.txt\n@@\n keep\n planted finding", "removes 2 line"),
        ("*** Update File: ordinary.txt\n*** Move to: .claude/agent-guard-receipt.json\n@@\n-old\n+new", "receipt"),
        ("*** Delete File: samples/expected/nested/manifest.json", "manifests"),
        ("*** Add File: ordinary.txt\n+safe\n*** Update File: samples/bad.txt\n@@\n keep\n-planted finding", "removes 1 line"),
        ("*** Update File: samples/bad.txt\n@@\n keep\n-planted finding\n*** End of File", "removes 1 line"),
    ]
    for body, reason in bad:
        patch_verdict(root, "*** Begin Patch\n" + body + "\n*** End Patch", True, reason)
    good = [
        "*** Add File: normal file.txt\n+ordinary content",
        "*** Delete File: one.txt",
        "*** Update File: samples/bad.txt\n@@\n-planted finding\n+same-size replacement",
        "*** Update File: one.txt\n*** Move to: renamed.txt\n@@\n-short\n+renamed",
    ]
    for body in good:
        patch_verdict(root, "*** Begin Patch\n" + body + "\n*** End Patch", False)
    for malformed in ("", "--- a/file\n+++ b/file", "*** Begin Patch\n*** Unknown File: samples/bad.txt\n*** End Patch"):
        patch_verdict(root, malformed, True, "could not check")
    for malformed in (None, [], {"tool_name": "apply_patch", "tool_input": []}):
        result = call(PATCH, cwd=root, payload=malformed)
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"
    nested = root / "nested"
    nested.mkdir()
    patch_verdict(nested, "*** Begin Patch\n*** Delete File: ../samples/bad.txt\n*** End Patch", True, "removes 2 line")
    (root / "receipt-link").symlink_to(root / ".claude/agent-guard-receipt.json")
    patch_verdict(root, "*** Begin Patch\n*** Add File: receipt-link\n+{}\n*** End Patch", True, "receipt")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="codex-guard-") as tmp:
        root = Path(tmp)
        git(root, "init", "--quiet")
        # Codex's apply_patch must protect the recorder's output even though
        # this host has no Claude permissions.deny interpreter.
        patch_verdict(root, "*** Begin Patch\n*** Add File: .claude/agent-guard-receipt.json\n+{}\n*** End Patch", True, "receipt")
        (root / "samples/expected").mkdir(parents=True)
        (root / "samples/expected/cases.json").write_text(json.dumps({"findings": [
            {"rule": "fixture", "file": "samples/bad.txt", "line": 2}]}))
        (root / "samples/bad.txt").write_text("keep\nplanted finding\n")
        patch_verdict(root, "*** Begin Patch\n*** Update File: samples/bad.txt\n@@\n keep\n-planted finding\n*** End Patch", True, "removes 1 line")
        patch_verdict(root, "*** Begin Patch\n*** Update File: samples/bad.txt\n@@\n keep\n planted finding\n+another finding\n*** End Patch", False)
        # Moving an uncited file onto a cited fixture is also an overwrite.
        (root / "one.txt").write_text("short\n")
        patch_verdict(root, "*** Begin Patch\n*** Update File: one.txt\n*** Move to: samples/bad.txt\n@@\n-short\n+replacement\n*** End Patch", True, "removes 1 line")
        patch_edges(root)
        native_installation(root)
    print("OK: Codex native hook fixtures")


if __name__ == "__main__":
    main()
