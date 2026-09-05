#!/usr/bin/env python3
"""Offline checks of the smoke command; these are NOT host observations."""

from __future__ import annotations

import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[2]
COMMAND = REPO / "scripts" / "agent-host-smoke.py"


class SmokeCommand(unittest.TestCase):
    def test_protocol_simulation_exercises_fixture_setup_and_real_recorder(self):
        # This executable simulates a host protocol in the OFFLINE test only.
        # It invokes configured hooks directly and is never live host evidence.
        with tempfile.TemporaryDirectory() as temp:
            host = Path(temp) / "claude"
            host.write_text("#!" + sys.executable + "\n" +
                            (REPO / "samples/agent-host-smoke/protocol_fixture.py").read_text())
            host.chmod(0o755)
            result = subprocess.run(
                [sys.executable, str(COMMAND), "--run-live", "--claude", str(host)],
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["fixtures"][0]["observations"], [
                {"phase": "no-receipt", "outcome": "no-receipt-blocked"},
                {"phase": "pass", "outcome": "fresh-stop-allowed"},
                {"phase": "content-changed", "outcome": "content-changed-blocked"},
                {"phase": "ordinary", "outcome": "ordinary-shell-allowed"},
                {"phase": "skip", "outcome": "skip-verification-denied"},
            ])
            self.assertEqual(report["negative_control"]["status"], "detected")

    def test_missing_host_is_unavailable_and_does_not_expose_its_path(self):
        result = subprocess.run(
            [sys.executable, str(COMMAND), "--run-live", "--claude",
             "/unavailable/private-host/claude"], capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "unavailable")
        self.assertEqual(report["reason"], "host-not-found")
        self.assertEqual(report["live_enforcement"], "unverified")
        self.assertNotIn("private-host", result.stdout)

    def test_expired_login_during_real_request_is_unavailable_after_healthy_diagnosis(self):
        with tempfile.TemporaryDirectory() as temp:
            host = Path(temp) / "claude"
            host.write_text("#!" + sys.executable + "\n" + '''
import json, sys
if "--version" in sys.argv:
    print("2.1.236 (Claude Code)")
elif "--help" in sys.argv:
    print("--include-hook-events")
elif "auth" in sys.argv:
    print(json.dumps({"loggedIn":True}))
else:
    print(json.dumps({"type":"result", "is_error":True,
        "result":"Failed to authenticate: OAuth session expired and could not be refreshed"}))
    sys.exit(1)
''')
            host.chmod(0o755)
            result = subprocess.run(
                [sys.executable, str(COMMAND), "--run-live", "--claude", str(host)],
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 2, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["reason"], "host-authentication-unusable")
            self.assertTrue(report["fixtures"][0]["diagnosis"]["healthy"])
            self.assertEqual(report["fixtures"][0]["observations"], [
                {"phase": "no-receipt", "outcome": "host-authentication-unusable"}])
            self.assertEqual(report["negative_control"]["status"], "not-run")

    def test_stop_assertion_requires_a_host_event_and_matching_guard_decision(self):
        observe = runpy.run_path(str(COMMAND))["observe"]
        claimed = [{"type": "assistant", "message": {"content": [
            {"type": "text", "text": "The Stop hook blocked: no-receipt"}]}}]
        ledger = [{"session": "fixture-session", "outcome": "no-receipt", "blocked": True}]
        self.assertEqual(observe("no-receipt", claimed, ledger), "hook-not-observed")
        event = {"type": "system", "subtype": "hook_response", "hook_event": "Stop",
                 "hook_id": "fixture-hook", "session_id": "fixture-session",
                 "exit_code": 0, "outcome": "success",
                 "stdout": json.dumps({"decision": "block", "reason": "The gate has not run."})}
        self.assertEqual(observe("no-receipt", [event], ledger), "no-receipt-blocked")
        self.assertEqual(observe("no-receipt", [event], []), "guard-decision-not-observed")
        self.assertEqual(observe("no-receipt", [event], [
            {"session": "other-session", "outcome": "no-receipt", "blocked": True}
        ]), "guard-decision-not-observed")
        # Removing hook wiring produces no host events; it must fail the SAME assertion.
        self.assertEqual(observe("no-receipt", [], []), "hook-not-observed")

    def test_fresh_receipt_requires_the_pass_decision_not_a_loop_override(self):
        observe = runpy.run_path(str(COMMAND))["observe"]
        hook = {"type": "system", "subtype": "hook_response", "hook_event": "Stop",
                "session_id": "fixture-session", "exit_code": 0,
                "outcome": "success", "stdout": ""}
        done = {"type": "result", "is_error": False}
        self.assertEqual(observe("pass", [hook, done], [
            {"session": "fixture-session", "outcome": "pass", "blocked": False}
        ]), "fresh-stop-allowed")
        self.assertEqual(observe("pass", [hook, done], [
            {"session": "fixture-session", "outcome": "loop-guard", "blocked": False}
        ]), "guard-decision-not-observed")
        self.assertEqual(observe("pass", [hook], [
            {"session": "fixture-session", "outcome": "pass", "blocked": False}
        ]), "host-turn-incomplete")

    def test_shell_refusal_requires_a_hook_denial_and_no_tripwire_execution(self):
        observe_shell = runpy.run_path(str(COMMAND))["observe_shell"]
        command = "/fixture/git commit --no-verify -m smoke"
        requested = {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Bash", "id": "fixture-tool",
             "input": {"command": command}}]}}
        hook = {"type": "system", "subtype": "hook_response", "hook_event": "PreToolUse",
                "session_id": "fixture-session", "exit_code": 0, "outcome": "success",
                "stdout": json.dumps({"hookSpecificOutput": {
                    "hookEventName": "PreToolUse", "permissionDecision": "deny",
                    "permissionDecisionReason": "This `git commit` passes --no-verify, which switches off the hook."}})}
        result = {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "fixture-tool", "is_error": True}]}}
        self.assertEqual(observe_shell("skip", [requested, hook, result], command, False),
                         "skip-verification-denied")
        self.assertEqual(observe_shell("skip", [requested, result], command, False),
                         "hook-not-observed")
        self.assertEqual(observe_shell("skip", [hook], command, False), "tool-not-requested")
        self.assertEqual(observe_shell("skip", [requested, hook, result], command, True),
                         "tripwire-executed")

    def test_non_invoking_host_fails_and_cleans_every_disposable_launch_shape(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            scratch = root / "scratch"
            scratch.mkdir()
            host = root / "claude"
            host.write_text("#!" + sys.executable + "\n" + '''
import json, sys
if "--version" in sys.argv:
    print("2.1.236 (Claude Code)")
elif "--help" in sys.argv:
    print("--include-hook-events --no-session-persistence --tools")
elif "auth" in sys.argv:
    print(json.dumps({"loggedIn": True}))
else:
    print(json.dumps({"type":"result", "is_error":False, "result":"fixture complete"}))
''')
            host.chmod(0o755)
            result = subprocess.run(
                [sys.executable, str(COMMAND), "--run-live", "--claude", str(host)],
                env={**os.environ, "TMPDIR": str(scratch)}, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 1, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "failed")
            self.assertEqual(report["live_enforcement"], "unverified")
            self.assertEqual({f["launch_shape"] for f in report["fixtures"]},
                             {"repository-root", "linked-worktree-root", "subdirectory"})
            self.assertEqual(report["negative_control"]["assertion"], "hook-not-observed")
            self.assertEqual(report["negative_control"]["status"], "detected")
            self.assertEqual(list(scratch.iterdir()), [])
            self.assertNotIn(str(root), result.stdout)


if __name__ == "__main__":
    unittest.main()
