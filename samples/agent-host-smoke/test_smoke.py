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
    def test_codex_native_protocol_runs_every_phase_and_removed_wiring_control(self):
        with tempfile.TemporaryDirectory() as temp:
            host = Path(temp) / "codex"
            host.write_text("#!" + sys.executable + "\n" +
                            (REPO / "samples/agent-host-smoke/codex_protocol_fixture.py").read_text())
            host.chmod(0o700)
            private = Path(temp) / "evidence"
            result = subprocess.run(
                [sys.executable, str(COMMAND), "--run-live", "--host", "codex",
                 "--codex", str(host), "--claude", "/never/call/claude",
                 "--private-output", str(private), "--timeout", "5"],
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["host"], "codex")
            self.assertEqual(report["negative_control"]["status"], "detected")
            for fixture in report["fixtures"]:
                self.assertTrue(fixture["diagnosis"]["healthy"])
                self.assertEqual([o["outcome"] for o in fixture["observations"]], [
                    "no-receipt-blocked", "fresh-stop-allowed", "content-changed-blocked",
                    "ordinary-shell-allowed", "skip-verification-denied"])
            for artifact in (private, *private.rglob("*")):
                self.assertEqual(artifact.stat().st_mode & 0o077, 0)
            # Native events/ledger are retained privately; IDs and paths never
            # leak into the public outcome report.
            self.assertTrue(list(private.rglob("stdout.jsonl")))
            self.assertNotIn("offline-codex-thread", result.stdout)
            self.assertNotIn(str(Path(temp)), result.stdout)

    def test_codex_subdirectory_discovery_failure_stays_separate_from_supported_roots(self):
        with tempfile.TemporaryDirectory() as temp:
            host = Path(temp) / "codex"
            host.write_text("#!" + sys.executable + "\n" +
                            (REPO / "samples/agent-host-smoke/codex_protocol_fixture.py").read_text())
            host.chmod(0o700)
            result = subprocess.run(
                [sys.executable, str(COMMAND), "--run-live", "--host", "codex",
                 "--codex", str(host), "--timeout", "5"], capture_output=True, text=True,
                env={**os.environ, "SMOKE_CODEX_PROTOCOL": "subdirectory-absent"},
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["live_enforcement"], "verified-supported-roots")
            subdirectory = report["fixtures"][2]
            self.assertEqual(subdirectory["discovery"]["outcome"], "host-project-hooks-not-discovered")
            self.assertEqual(subdirectory["observations"], [])
            self.assertEqual(subdirectory["status"], "unavailable")

    def test_codex_missing_untrusted_disabled_or_unauthenticated_preflight_never_starts_a_turn(self):
        for mode, code in (("untrusted", "host-hook-trust-required"),
                           ("modified", "host-hook-trust-required"),
                           ("disabled", "host-hooks-disabled"),
                           ("absent", "host-project-hooks-not-discovered"),
                           ("no-auth", "host-authentication-unavailable"),
                           ("no-experimental-api", "host-experimental-events-unavailable"),
                           ("missing-hash", "host-hook-discovery-unavailable")):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temp:
                host = Path(temp) / "codex"
                host.write_text("#!" + sys.executable + "\n" +
                                (REPO / "samples/agent-host-smoke/codex_protocol_fixture.py").read_text())
                host.chmod(0o700)
                private = Path(temp) / "evidence"
                result = subprocess.run(
                    [sys.executable, str(COMMAND), "--run-live", "--host", "codex",
                     "--codex", str(host), "--timeout", "2", "--private-output", str(private)],
                    capture_output=True, text=True, env={**os.environ, "SMOKE_CODEX_PROTOCOL": mode},
                )
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                report = json.loads(result.stdout)
                self.assertEqual(report["reason"], code)
                self.assertEqual(report["live_enforcement"], "unverified")
                self.assertEqual(len(report["fixtures"]), 3)
                self.assertEqual(report["negative_control"]["status"], "not-run")
                for log in private.rglob("requests.private.jsonl"):
                    requests = [json.loads(line) for line in log.read_text().splitlines()]
                    self.assertNotIn("thread/start", [r.get("method") for r in requests])
                    self.assertNotIn("turn/start", [r.get("method") for r in requests])

    def test_codex_stop_requires_native_identity_source_and_guard_decision(self):
        from copy import deepcopy
        observe = runpy.run_path(str(REPO / "scripts/agent_host_codex.py"))["observe"]
        source = Path("/fixture/.codex/hooks.json")
        hook = {"method": "hook/completed", "params": {"threadId": "fixture-thread", "turnId": "fixture-turn",
                "run": {"id": "fixture-hook", "eventName": "stop", "source": "project",
                        "sourcePath": str(source), "handlerType": "command", "executionMode": "sync",
                        "status": "blocked", "entries": [{"kind": "feedback", "text": "The gate has not run."}]}}}
        ledger = [{"session": "fixture-thread", "outcome": "no-receipt", "blocked": True}]
        def check(events, rows=ledger):
            return observe("no-receipt", events, rows, "fixture-thread", "fixture-turn", source)
        self.assertEqual(check([hook]), "no-receipt-blocked")
        self.assertEqual(check([]), "hook-not-observed")
        self.assertEqual(check([hook], []), "guard-decision-not-observed")
        self.assertEqual(check([hook], [{**ledger[0], "session": "other-thread"}]), "guard-decision-not-observed")
        for field, value in (("threadId", "other-thread"), ("turnId", "other-turn")):
            other = deepcopy(hook)
            other["params"][field] = value
            self.assertEqual(check([other]), "hook-not-observed")
        for field, value in (("source", "user"), ("sourcePath", "/other/hooks.json"),
                             ("id", ""), ("status", "failed"), ("entries", [])):
            with self.subTest(field=field):
                other = deepcopy(hook)
                other["params"]["run"][field] = value
                self.assertNotEqual(check([other]), "no-receipt-blocked")

    def test_codex_ordinary_shell_accepts_the_observed_native_launch_wrapper(self):
        observe = runpy.run_path(str(REPO / "scripts/agent_host_codex.py"))["observe"]
        source = Path("/fixture/.codex/hooks.json")
        command = "printf fixture > /fixture/root/.host-smoke-probes/host-01/ordinary/executed"
        scope = {"threadId": "fixture-thread", "turnId": "fixture-turn"}
        hook = {"method": "hook/completed", "params": {**scope, "run": {
            "id": "fixture-hook", "eventName": "preToolUse", "source": "project", "sourcePath": str(source),
            "handlerType": "command", "executionMode": "sync", "status": "completed", "entries": []}}}
        # Codex 0.153.3 reports the launch wrapper on BOTH lifecycle items,
        # after its synchronous PreToolUse event. Paths and IDs are synthetic.
        for reported in (command, "/bin/zsh -lc '" + command + "'"):
            with self.subTest(reported=reported):
                item = {"type": "commandExecution", "id": "fixture-command", "command": reported}
                events = [hook, {"method": "item/started", "params": {**scope, "item": item}},
                          {"method": "item/completed", "params": {**scope, "item": {
                              **item, "status": "completed", "exitCode": 0}}}]
                self.assertEqual(observe("ordinary", events, [], "fixture-thread", "fixture-turn",
                                         source, command, True), "ordinary-shell-allowed")

    def test_codex_denied_command_items_without_raw_provenance_stay_unavailable(self):
        observe = runpy.run_path(str(REPO / "scripts/agent_host_codex.py"))["observe"]
        scope = {"threadId": "fixture-thread", "turnId": "fixture-turn"}
        command = "/fixture/git commit --no-verify -m smoke"
        item = {"type": "commandExecution", "id": "fixture-command", "command": command}
        events = [{"method": "item/started", "params": {**scope, "item": item}},
                  {"method": "item/completed", "params": {**scope, "item": {**item, "status": "declined"}}}]
        # The old synthetic approval-denial shape is not the measured hook
        # denial protocol. It cannot silently replace missing raw provenance.
        self.assertEqual(observe("skip", events, [], "fixture-thread", "fixture-turn",
                                 Path("/fixture/.codex/hooks.json"), command),
                         "host-tool-request-provenance-unavailable")

    def test_codex_native_wrapper_rejects_misleading_commands_and_mismatched_results(self):
        from copy import deepcopy
        observe = runpy.run_path(str(REPO / "scripts/agent_host_codex.py"))["observe"]
        source = Path("/fixture/.codex/hooks.json")
        command = "printf fixture > /fixture/executed"
        wrapper = "/bin/zsh -lc '" + command + "'"
        scope = {"threadId": "fixture-thread", "turnId": "fixture-turn"}
        item = {"type": "commandExecution", "id": "fixture-command", "command": wrapper}
        events = [
            {"method": "hook/completed", "params": {**scope, "run": {
                "id": "fixture-hook", "eventName": "preToolUse", "source": "project", "sourcePath": str(source),
                "handlerType": "command", "executionMode": "sync", "status": "completed", "entries": []}}},
            {"method": "item/started", "params": {**scope, "item": item}},
            {"method": "item/completed", "params": {**scope, "item": {
                **item, "status": "completed", "exitCode": 0}}},
        ]
        def check(rows):
            return observe("ordinary", rows, [], "fixture-thread", "fixture-turn", source, command, True)
        for misleading in (
            wrapper + " extra", wrapper + "; printf extra", wrapper + " && printf extra",
            wrapper[:-1] + "; printf extra'", "env " + wrapper, "echo " + wrapper,
            wrapper.replace("/bin/zsh", "/fixture/zsh"), wrapper.replace(" -lc ", " -lic "),
            wrapper.replace("fixture >", "other >"), wrapper + " # comment", wrapper[:-1],
            "/bin/zsh -lc '$(" + command + ")'",
        ):
            with self.subTest(misleading=misleading):
                changed = deepcopy(events)
                for event in changed[1:]:
                    event["params"]["item"]["command"] = misleading
                self.assertEqual(check(changed), "tool-not-requested")
        for field, value in (("id", "other-command"), ("type", "fileChange"),
                             ("command", command), ("command", wrapper + " extra"), ("exitCode", 1)):
            with self.subTest(field=field, value=value):
                changed = deepcopy(events)
                changed[-1]["params"]["item"][field] = value
                self.assertEqual(check(changed), "ordinary-shell-not-executed")
        extra = {"method": "item/started", "params": {**scope, "item": {
            "id": "other-tool", "type": "fileChange"}}}
        self.assertEqual(check([*events, extra]), "ambiguous-tool-requests")

    def test_codex_denied_raw_request_needs_exact_provenance_without_command_items(self):
        from copy import deepcopy
        observe = runpy.run_path(str(REPO / "scripts/agent_host_codex.py"))["observe"]
        source = Path("/fixture/.codex/hooks.json")
        command = "/fixture/git commit --no-verify -m smoke"
        scope = {"threadId": "fixture-thread", "turnId": "fixture-turn"}
        request = {"method": "rawResponseItem/completed", "params": {**scope, "item": {
            "type": "custom_tool_call", "name": "exec", "id": "fixture-item", "call_id": "fixture-call",
            "input": "text(await tools.exec_command({cmd:" + json.dumps(command) + "}));\n"}}}
        hook = {"method": "hook/completed", "params": {**scope, "run": {
            "id": "fixture-hook", "eventName": "preToolUse", "source": "project", "sourcePath": str(source),
            "handlerType": "command", "executionMode": "sync", "status": "blocked",
            "entries": [{"kind": "feedback", "text": "This `git commit` passes --no-verify, which switches off the hook."}]}}}
        start = {"method": "hook/started", "params": {**scope, "run": {**hook["params"]["run"], "status": "running"}}}
        def check(rows, executed=False):
            return observe("skip", rows, [], "fixture-thread", "fixture-turn", source, command, executed)
        self.assertEqual(check([request, start, hook]), "skip-verification-denied")
        self.assertEqual(check([request, start, hook], True), "tripwire-executed")
        for field, value in (("call_id", ""), ("call_id", None), ("name", "other_tool"),
                             ("type", "message"), ("id", ""), ("namespace", "other"),
                             ("input", "text(await tools.exec_command({cmd:" + json.dumps(command + "; echo other") + "}));"),
                             ("input", "// " + command)):
            with self.subTest(field=field, value=value):
                wrong = deepcopy(request)
                wrong["params"]["item"][field] = value
                self.assertNotEqual(check([wrong, start, hook]), "skip-verification-denied")
        for event_index in (0, 1, 2):
            for field in ("threadId", "turnId"):
                with self.subTest(event=event_index, field=field):
                    wrong = deepcopy([request, start, hook])
                    wrong[event_index]["params"][field] = "other"
                    self.assertNotEqual(check(wrong), "skip-verification-denied")
        self.assertNotEqual(check([hook, start, request]), "skip-verification-denied")
        self.assertNotEqual(check([request]), "skip-verification-denied")
        self.assertNotEqual(check([hook]), "skip-verification-denied")
        program = request["params"]["item"]["input"].rstrip("\n")
        for misleading in (program + " // extra", "// " + program, program + program,
                           "text(" + json.dumps(program) + ");", program.replace("tools.exec_command", "other.exec_command"),
                           program.replace("}));", ',max_output_tokens:1}));'),
                           program.replace("await ", "")):
            wrong = deepcopy(request)
            wrong["params"]["item"]["input"] = misleading
            self.assertNotEqual(check([wrong, start, hook]), "skip-verification-denied")
        for field, value in (("id", "other-hook"), ("source", "user"), ("sourcePath", "/other/hooks.json"),
                             ("handlerType", "prompt"), ("executionMode", "async"), ("status", "completed")):
            wrong = deepcopy(start)
            wrong["params"]["run"][field] = value
            self.assertNotEqual(check([request, wrong, hook]), "skip-verification-denied")
        output = {"method": "rawResponseItem/completed", "params": {**scope, "item": {
            "type": "custom_tool_call_output", "call_id": "other-call", "output": "denied"}}}
        self.assertNotEqual(check([request, start, hook, output]), "skip-verification-denied")
        other_request = deepcopy(request)
        other_request["params"]["item"]["id"] = "other-item"
        other_request["params"]["item"]["call_id"] = "other-call"
        for extra in (request, {"method": "item/started", "params": {**scope, "item": {
                "type": "fileChange", "id": "other-call"}}},
                {"method": "rawResponseItem/completed", "params": {**scope, "item": {
                    "type": "custom_tool_call", "name": "apply_patch", "call_id": "other-call", "input": "other"}}}):
            with self.subTest(extra=extra):
                self.assertNotEqual(check([request, extra, start, hook]), "skip-verification-denied")
        self.assertNotEqual(check([request, other_request, start, hook]), "skip-verification-denied")

    def test_codex_missing_experimental_raw_requests_is_unavailable(self):
        with tempfile.TemporaryDirectory() as temp:
            host = Path(temp) / "codex"
            host.write_text("#!" + sys.executable + "\n" +
                            (REPO / "samples/agent-host-smoke/codex_protocol_fixture.py").read_text())
            host.chmod(0o700)
            result = subprocess.run(
                [sys.executable, str(COMMAND), "--run-live", "--host", "codex",
                 "--codex", str(host), "--timeout", "5"], capture_output=True, text=True,
                env={**os.environ, "SMOKE_CODEX_PROTOCOL": "no-raw-events"})
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["reason"], "host-tool-request-provenance-unavailable")
            self.assertEqual(report["live_enforcement"], "unverified")
            self.assertEqual(report["negative_control"]["status"], "not-run")

    def test_codex_tripwire_racing_interrupt_cannot_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            host = Path(temp) / "codex"
            host.write_text("#!" + sys.executable + "\n" +
                            (REPO / "samples/agent-host-smoke/codex_protocol_fixture.py").read_text())
            host.chmod(0o700)
            result = subprocess.run(
                [sys.executable, str(COMMAND), "--run-live", "--host", "codex",
                 "--codex", str(host), "--timeout", "5"], capture_output=True, text=True,
                env={**os.environ, "SMOKE_CODEX_PROTOCOL": "late-tripwire"})
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            report = json.loads(result.stdout)
            for fixture in report["fixtures"]:
                self.assertEqual(fixture["observations"][-1]["outcome"], "tripwire-executed")

    def test_private_scratch_cannot_be_created_inside_a_git_checkout(self):
        with tempfile.TemporaryDirectory() as temp:
            parent = Path(temp) / "checkout"
            parent.mkdir()
            subprocess.run(["git", "init", "--quiet", str(parent)], check=True)
            host = Path(temp) / "codex"
            host.write_text("#!" + sys.executable + "\n" +
                            (REPO / "samples/agent-host-smoke/codex_protocol_fixture.py").read_text())
            host.chmod(0o700)
            result = subprocess.run(
                [sys.executable, str(COMMAND), "--run-live", "--host", "codex", "--codex", str(host)],
                env={**os.environ, "TMPDIR": str(parent), "SMOKE_CODEX_PROTOCOL": "untrusted"},
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertEqual(json.loads(result.stdout)["reason"], "private-scratch-inside-git-checkout")
            self.assertEqual([path.name for path in parent.iterdir()], [".git"])

    def test_codex_selection_never_requires_claude(self):
        result = subprocess.run(
            [sys.executable, str(COMMAND), "--run-live", "--host", "codex",
             "--codex", "/unavailable/private-host/codex"], capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["host"], "codex")
        self.assertEqual(report["reason"], "host-not-found")
        self.assertNotIn("private-host", result.stdout)

    def test_protocol_simulation_exercises_fixture_setup_and_real_recorder(self):
        # This executable simulates a host protocol in the OFFLINE test only.
        # It invokes configured hooks directly and is never live host evidence.
        with tempfile.TemporaryDirectory() as temp:
            host = Path(temp) / "claude"
            host.write_text("#!" + sys.executable + "\n" +
                            (REPO / "samples/agent-host-smoke/protocol_fixture.py").read_text())
            host.chmod(0o755)
            private = Path(temp) / "private-evidence"
            result = subprocess.run(
                [sys.executable, str(COMMAND), "--run-live", "--claude", str(host),
                 "--private-output", str(private)],
                capture_output=True, text=True, umask=0o022,
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
            self.assertTrue(list(private.rglob("stdout.jsonl")))
            for artifact in (private, *private.rglob("*")):
                with self.subTest(artifact=artifact.relative_to(private)):
                    self.assertEqual(artifact.stat().st_mode & 0o077, 0,
                                     "Private evidence must have no group or other access")

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

    def test_shell_denial_for_another_request_cannot_prove_tripwire_protection(self):
        observe_shell = runpy.run_path(str(COMMAND))["observe_shell"]
        command = "/fixture/git commit --no-verify -m smoke"

        def request(ident, text):
            return {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Bash", "id": ident,
                 "input": {"command": text}}]}}

        def result(ident):
            return {"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": ident, "is_error": True,
                 "content": "Permission denied"}]}}

        hook = {"type": "system", "subtype": "hook_response", "hook_event": "PreToolUse",
                "session_id": "fixture-session", "exit_code": 0, "outcome": "success",
                "stdout": json.dumps({"hookSpecificOutput": {
                    "hookEventName": "PreToolUse", "permissionDecision": "deny",
                    "permissionDecisionReason": "This `git commit` passes --no-verify, which switches off the hook."}})}
        expected = [request("expected-tool", command), result("expected-tool")]
        other = [request("other-tool", "git commit --no-verify -m other"), hook, result("other-tool")]
        for events in (other + expected, expected + other):
            with self.subTest(events=events):
                self.assertEqual(observe_shell("skip", events, command, False),
                                 "ambiguous-tool-requests")
        self.assertEqual(observe_shell("skip", [expected[0], hook, expected[1]], command, False),
                         "skip-verification-denied")

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
