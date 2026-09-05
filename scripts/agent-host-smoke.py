#!/usr/bin/env python3
"""Opt-in Claude Code invocation evidence, exclusively in disposable repos."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

REPO = Path(__file__).resolve().parents[1]
RUNTIME = REPO / "scripts/quality-runtime.py"
VERSION = "v0.0.0-host-smoke"


def observe(phase: str, events: list[dict], ledger: list[dict]) -> str:
    """Interpret host lifecycle events, never model claims or a ledger alone.

    The ledger attributes the baseline decision to the host session. It is
    supporting evidence only: it cannot establish host invocation by itself.
    """
    hooks = [e for e in events if e.get("type") == "system"
             and e.get("subtype") == "hook_response" and e.get("hook_event") == "Stop"
             and isinstance(e.get("session_id"), str) and e["session_id"]
             and e.get("exit_code") == 0 and e.get("outcome") == "success"]
    if not hooks:
        return "hook-not-observed"
    if phase == "pass":
        if not any(e.get("type") == "result" and e.get("is_error") is False for e in events):
            return "host-turn-incomplete"
        if any(r.get("session") == event.get("session_id") and r.get("outcome") == "pass"
               and r.get("blocked") is False for event in hooks for r in ledger):
            return "fresh-stop-allowed"
        return "guard-decision-not-observed"
    for event in hooks:
        try:
            output = json.loads(event.get("stdout", ""))
        except ValueError:
            continue
        prefixes = {"no-receipt": "The gate has not run.",
                    "content-changed": "The gate passed, but the working tree has changed since"}
        if (isinstance(output, dict) and output.get("decision") == "block"
                and str(output.get("reason", "")).startswith(prefixes.get(phase, "\0")) and any(
            r.get("session") == event.get("session_id") and r.get("outcome") == phase
            and r.get("blocked") is True for r in ledger
        )):
            return phase + "-blocked"
    return "guard-decision-not-observed"


def observe_shell(phase: str, events: list[dict], command: str, executed: bool) -> str:
    """A requested tool, host hook response and execution tripwire are independent."""
    blocks = [block for e in events if e.get("type") in ("assistant", "user")
              for block in e.get("message", {}).get("content", []) if isinstance(block, dict)]
    ids = {b.get("id") for b in blocks if b.get("type") == "tool_use"
           and b.get("name") == "Bash" and b.get("input", {}).get("command") == command}
    if not ids:
        return "tool-not-requested"
    if phase == "skip" and executed:
        return "tripwire-executed"
    hooks = [e for e in events if e.get("type") == "system"
             and e.get("subtype") == "hook_response" and e.get("hook_event") == "PreToolUse"
             and e.get("exit_code") == 0 and e.get("outcome") == "success"]
    if not hooks:
        return "hook-not-observed"
    results = [b for b in blocks if b.get("type") == "tool_result" and b.get("tool_use_id") in ids]
    if phase == "ordinary":
        return ("ordinary-shell-allowed" if executed and any(not b.get("is_error") for b in results)
                else "ordinary-shell-not-executed")
    for event in hooks:
        try:
            output = json.loads(event.get("stdout", ""))
        except ValueError:
            continue
        decision = output.get("hookSpecificOutput", {}) if isinstance(output, dict) else {}
        if (decision.get("permissionDecision") == "deny"
                and decision.get("permissionDecisionReason", "").startswith("This `git commit` passes --no-verify")
                and any(b.get("is_error") is True for b in results)):
            return "skip-verification-denied"
    return "guard-decision-not-observed"


class Unavailable(Exception):
    """Only fixed public reason codes cross this boundary."""

    fixture: dict | None = None


def run(argv: list[str], *, cwd: Path, env: dict[str, str], timeout: float = 30) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True,
                              timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise Unavailable("prerequisite-timeout") from exc
    except OSError as exc:
        raise Unavailable("prerequisite-not-executable") from exc


def checked(argv: list[str], *, cwd: Path, env: dict[str, str]) -> str:
    result = run(argv, cwd=cwd, env=env)
    if result.returncode:
        raise Unavailable("fixture-setup-failed")
    return result.stdout.strip()


def json_lines(text: str) -> list[dict]:
    rows = []
    for line in text.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def host_error(events: list[dict], returncode: int) -> str | None:
    for event in events:
        if event.get("type") == "result" and event.get("is_error"):
            detail = str(event.get("result", "")) + str(event.get("errors", ""))
            if any(word in detail.lower() for word in ("authenticat", "oauth", "not logged in")):
                return "host-authentication-unusable"
            return "host-request-failed"
    return "host-process-failed" if returncode else None


def launch(host: str, cwd: Path, env: dict[str, str], output: Path,
           timeout: float, command: str | None = None) -> list[dict]:
    prompt = ("Say fixture complete. Do not use tools."
              if command is None else
              "This is an authorized disposable host-enforcement fixture. Use Bash exactly once "
              "to request the following exact harmless command. The executable named git is a "
              "fixture tripwire that only writes a marker; it cannot run Git or push. Do not "
              "replace the command or repair any hook refusal. Then say fixture complete.\n" + command)
    argv = [host, "--print", "--verbose", "--output-format", "stream-json",
            "--include-hook-events", "--no-session-persistence", "--tools",
            "Bash" if command else ""]
    if command:
        argv += ["--allowedTools", "Bash"]
    argv.append(prompt)
    (output / "launch.private.json").write_text(json.dumps({"argv": argv, "cwd": str(cwd)}) + "\n")
    # Start a process group so a timeout also ends hook/shell descendants before
    # the fixture is removed. No shell is used to launch the host.
    with (output / "stdout.jsonl").open("w") as stdout, (output / "stderr.txt").open("w") as stderr:
        process = subprocess.Popen(argv, cwd=cwd, env=env, stdout=stdout, stderr=stderr,
                                   start_new_session=True)
        try:
            returncode = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            raise Unavailable("host-timeout") from exc
    events = json_lines((output / "stdout.jsonl").read_text())
    error = host_error(events, returncode)
    if error:
        raise Unavailable(error)
    if not any(e.get("type") == "result" for e in events):
        raise Unavailable("host-stream-incomplete")
    return events


def diagnosis(root: Path, env: dict[str, str], output: Path) -> dict:
    result = run([sys.executable, str(RUNTIME), "diagnose", "--root", str(root), "--json"], cwd=root, env=env)
    (output / "diagnosis.private.json").write_text(result.stdout)
    try:
        report = json.loads(result.stdout)
    except ValueError as exc:
        raise Unavailable("installation-diagnosis-unreadable") from exc
    # Do not echo check details: they contain absolute runtime/cache paths.
    return {"schema": report["schema"], "status": report["status"], "healthy": report["healthy"],
            "installation_profile": report["installation_profile"],
            "live_enforcement": report["live_enforcement"], "host_settings": report["host_settings"],
            "checks": [{"id": c["id"], "status": c["status"]} for c in report["checks"]]}


def make_repository(root: Path, commit: str, env: dict[str, str]) -> None:
    root.mkdir()
    git_env = {**env, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    def git(*args: str) -> str:
        return checked(["git", *args], cwd=root, env=git_env)
    git("init", "--quiet", "--initial-branch=fixture")
    git("config", "user.name", "maximalcode")
    git("config", "user.email", "213183497+maximalcode@users.noreply.github.com")
    checked([sys.executable, str(REPO / "scripts/quality-runtime-migrate.py"),
             "--target", str(root), "--version", VERSION, "--commit", commit,
             "--launcher", str(RUNTIME)], cwd=root, env=env)
    (root / ".claude/agent-guard.json").write_text('{"gate_command":"python3 gate.py"}\n')
    (root / "gate.py").write_text(
        'from pathlib import Path\nassert Path("fixture.txt").read_text().startswith("fixture")\n')
    (root / "fixture.txt").write_text("fixture\n")
    (root / "subdirectory").mkdir()
    (root / "subdirectory/fixture.txt").write_text("fixture subdirectory\n")
    git("add", "-A")
    if git("config", "user.name") != "maximalcode":
        raise Unavailable("fixture-identity-mismatch")
    git("commit", "--quiet", "-m", "chore: disposable host smoke fixture")


def observe_fixture(ident: str, shape: str, root: Path, cwd: Path, host: str,
                    env: dict[str, str], artifacts: Path, timeout: float,
                    *, negative: bool = False) -> dict:
    out = artifacts / ident
    out.mkdir()
    report = {"fixture": ident, "launch_shape": shape, "diagnosis": diagnosis(root, env, out),
              "observations": []}
    if negative:
        report["wiring"] = "removed"
    elif not report["diagnosis"]["healthy"]:
        raise Unavailable("installation-diagnosis-failed")
    if shape == "subdirectory":
        report["documented_limitation"] = "issue-222-subdirectory-hook-loading"
    receipt = root / ".claude/agent-guard-receipt.json"
    receipt.unlink(missing_ok=True)
    (root / "fixture.txt").write_text("fixture edited\n")
    ledger_path = root / ".claude/agent-guard-ledger.jsonl"
    for phase in ("no-receipt",) if negative else ("no-receipt", "pass", "content-changed", "ordinary", "skip"):
        phase_out = out / phase
        phase_out.mkdir()
        if phase == "pass":
            gate = run([sys.executable, str(RUNTIME), "record-gate", "--root", str(root), "--gate"],
                       cwd=root, env=env)
            (phase_out / "recorder.private.json").write_text(json.dumps({
                "exit_code": gate.returncode, "stdout": gate.stdout, "stderr": gate.stderr}) + "\n")
            if gate.returncode:
                raise Unavailable("fixture-gate-failed")
        if phase == "content-changed":
            (root / "fixture.txt").write_text("fixture edited again\n")
        before = len(json_lines(ledger_path.read_text())) if ledger_path.exists() else 0
        marker = phase_out / "executed"
        command = None
        if phase == "ordinary":
            command = "printf fixture > " + shlex.quote(str(marker))
        elif phase == "skip":
            tripwire = phase_out / "git"
            tripwire.write_text("#!/bin/sh\nprintf fixture > " + shlex.quote(str(marker)) + "\n")
            tripwire.chmod(0o700)
            command = shlex.quote(str(tripwire)) + " commit --no-verify -m host-smoke"
        try:
            events = launch(host, cwd, env, phase_out, timeout, command)
        except Unavailable as exc:
            report["observations"].append({"phase": phase, "outcome": str(exc)})
            (out / "observation.json").write_text(json.dumps(report, indent=2) + "\n")
            exc.fixture = report
            raise
        ledger = json_lines(ledger_path.read_text())[before:] if ledger_path.exists() else []
        (phase_out / "ledger.private.json").write_text(json.dumps(ledger) + "\n")
        outcome = (observe_shell(phase, events, command, marker.exists()) if command else
                   observe(phase, events, ledger))
        report["observations"].append({"phase": phase, "outcome": outcome})
        (out / "observation.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def smoke(host: str, commit: str, timeout: float, private: Path | None, report: dict) -> None:
    with tempfile.TemporaryDirectory(prefix="agent-host-smoke-") as temp:
        scratch = Path(temp)
        artifacts = scratch / "artifacts"
        artifacts.mkdir()
        # Git routing inherited from an enclosing hook must never point a
        # disposable operation at the caller's index or repository.
        env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        env.update({"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"})
        env["MAXI_QUALITY_RUNTIME_CACHE"] = str(scratch / "cache")
        try:
            checked([sys.executable, str(RUNTIME), "prepare", "--source", str(REPO),
                     "--version", VERSION, "--commit", commit, "--cache-root", str(scratch / "cache"),
                     "--allow-untagged-development"], cwd=REPO, env=env)
            root = scratch / "root"
            make_repository(root, commit, env)
            linked = scratch / "linked"
            checked(["git", "worktree", "add", "--quiet", "-b", "linked", str(linked)], cwd=root, env=env)
            for ident, shape, repo, cwd in (
                ("host-01", "repository-root", root, root),
                ("host-02", "linked-worktree-root", linked, linked),
                ("host-03", "subdirectory", root, root / "subdirectory"),
            ):
                report["fixtures"].append(observe_fixture(ident, shape, repo, cwd, host, env, artifacts, timeout))
            negative = scratch / "negative"
            make_repository(negative, commit, env)
            settings = negative / ".claude/settings.json"
            data = json.loads(settings.read_text())
            del data["hooks"]
            settings.write_text(json.dumps(data) + "\n")
            control = observe_fixture("host-04", "repository-root", negative, negative,
                                      host, env, artifacts, timeout, negative=True)
            assertion = control["observations"][0]["outcome"]
            report["negative_control"] = {**control, "assertion": assertion,
                "status": "detected" if assertion == "hook-not-observed" else "failed"}
        finally:
            if private is not None:
                shutil.copytree(artifacts, private, dirs_exist_ok=True)
    expected = ["no-receipt-blocked", "fresh-stop-allowed", "content-changed-blocked",
                "ordinary-shell-allowed", "skip-verification-denied"]
    # Subdirectory is measured separately and cannot qualify a supported root.
    protected = all([o["outcome"] for o in f["observations"]] == expected
                    for f in report["fixtures"][:2])
    passed = protected and report["negative_control"]["status"] == "detected"
    report["status"] = "passed" if passed else "failed"
    report["live_enforcement"] = "verified-supported-roots" if passed else "unverified"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-live", action="store_true", required=True,
                        help="Explicitly authorize using the existing Claude login in disposable fixtures")
    parser.add_argument("--claude", default="claude", help="Existing Claude Code executable; no fallback or installation")
    parser.add_argument("--commit", help="Committed baseline guard revision (default: HEAD)")
    parser.add_argument("--timeout", type=float, default=90, help="Maximum seconds per host turn")
    parser.add_argument("--private-output", type=Path, help="New directory outside Git checkouts for raw private evidence")
    args = parser.parse_args()
    now = datetime.now(timezone.utc).date().isoformat()  # nosemgrep: no-ambient-clock-python — clock read at the command edge
    report = {"schema": 1, "measurement": "synthetic-host-smoke", "date": now,
              "host": "claude-code", "host_version": None, "baseline_revision": None,
              "runtime_version": VERSION, "installation_profile": "versioned-without-samples",
              "launch_mode": "print-stream-json-default-settings", "status": "unavailable",
              "live_enforcement": "unverified", "fixtures": [],
              "negative_control": {"status": "not-run"}}
    try:
        if args.timeout <= 0:
            raise Unavailable("invalid-timeout")
        host = shutil.which(args.claude)
        if host is None:
            raise Unavailable("host-not-found")
        if shutil.which("git") is None or shutil.which("python3") is None:
            raise Unavailable("git-or-python3-not-found")
        version = run([host, "--version"], cwd=REPO, env=os.environ)
        match = re.fullmatch(r"([0-9]+\.[0-9]+\.[0-9]+) \(Claude Code\)\s*", version.stdout)
        if version.returncode or not match:
            raise Unavailable("unsupported-host-version-output")
        report["host_version"] = match.group(1)
        help_result = run([host, "--help"], cwd=REPO, env=os.environ)
        if "--include-hook-events" not in help_result.stdout:
            raise Unavailable("host-hook-events-unavailable")
        auth = run([host, "auth", "status", "--json"], cwd=REPO, env=os.environ)
        try:
            authenticated = json.loads(auth.stdout).get("loggedIn") is True
        except (ValueError, AttributeError):
            authenticated = False
        if auth.returncode or not authenticated:
            raise Unavailable("host-authentication-unavailable")
        git_env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        commit = checked(["git", "rev-parse", "--verify", (args.commit or "HEAD") + "^{commit}"],
                         cwd=REPO, env=git_env)
        report["baseline_revision"] = commit
        if args.private_output is not None:
            private = args.private_output.resolve()
            if private.exists() or not private.parent.is_dir():
                raise Unavailable("private-output-must-be-new")
            inside = run(["git", "rev-parse", "--show-toplevel"], cwd=private.parent, env=git_env)
            if inside.returncode == 0:
                raise Unavailable("private-output-inside-git-checkout")
            private.mkdir(mode=0o700)
        smoke(host, commit, args.timeout, args.private_output, report)
    except Unavailable as exc:
        report["status"] = "unavailable"
        report["reason"] = str(exc)
        if exc.fixture is not None:
            report["fixtures"].append(exc.fixture)
    except OSError:
        report["status"] = "unavailable"
        report["reason"] = "fixture-io-unavailable"
    print(json.dumps(report, indent=2, sort_keys=True))
    return {"passed": 0, "failed": 1, "unavailable": 2}[report["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
