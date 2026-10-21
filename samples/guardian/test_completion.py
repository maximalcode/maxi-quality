"""Observe automatic completion through native Stop payloads and public commands."""

import json
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest

from test_setup_hosts import BASELINE, RUNNER, project

STOP = BASELINE / "scripts/agent-guard/stop-gate.py"
RECORDER = BASELINE / "scripts/agent-guard/record-gate.py"


class CompletionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = project(Path(self.temp.name) / "project")
        (self.root / "source.txt").write_text("changed\n")
        (self.root / "check.py").write_text(
            "from pathlib import Path\nimport sys, time\n"
            "p=Path('.git/starts'); p.write_text(p.read_text()+'x' if p.exists() else 'x')\n"
            "print('fixture diagnostic', flush=True)\n"
            "time.sleep(float(sys.argv[1]))\n"
            "raise SystemExit(int(sys.argv[2]))\n")
        self.configure()

    def configure(self, delay=0, code=0, *, automatic=True, seconds=2, gate=None):
        command = gate or f"{sys.executable} check.py {delay} {code}"
        config = {"gate_command": command}
        if automatic:
            config["automatic_completion"] = {
                "command": command, "check_only": True, "timeout_seconds": seconds}
        (self.root / ".claude/agent-guard.json").write_text(json.dumps(config))

    def cli(self, *args):
        return subprocess.run([sys.executable, str(RUNNER), *args], cwd=self.root,
                              capture_output=True, text=True, timeout=15)

    def stop(self, host="claude", **event):
        payload = {"cwd": str(self.root), "hook_event_name": "Stop",
                   "stop_hook_active": False, "session_id": "fixture", **event}
        if host == "codex":
            payload.update(transcript_path="", last_assistant_message="Finished fixture work")
        return subprocess.run([sys.executable, str(STOP)], cwd=self.root,
                              input=json.dumps(payload), text=True, capture_output=True, timeout=12)

    def starts(self):
        path = self.root / ".git/starts"
        return len(path.read_text()) if path.exists() else 0

    def status(self):
        proc = self.cli("status", str(self.root), "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)["automatic_completion"]

    def sources(self):
        return {name: (self.root / name).read_bytes() for name in
                ("source.txt", "check.py", ".claude/agent-guard.json")}

    def test_unborn_head_records_reuses_and_invalidates_on_first_commit(self):
        subprocess.run(["git", "symbolic-ref", "HEAD", "refs/heads/unborn"],
                       cwd=self.root, check=True)
        recorded = subprocess.run([sys.executable, str(RECORDER), "--gate"],
                                  cwd=self.root, capture_output=True, text=True)
        self.assertEqual(recorded.returncode, 0, recorded.stderr)
        self.assertEqual(self.stop().stdout, "")
        self.assertEqual(self.starts(), 1)
        self.assertEqual(self.status()["verification"], "succeeded")
        subprocess.run(["git", "add", "."], cwd=self.root, check=True)
        subprocess.run(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                        "-c", "core.hooksPath=/dev/null", "commit", "-qm", "first commit"],
                       cwd=self.root, check=True)
        self.assertEqual(self.status()["verification"], "unverified")
        self.assertEqual(self.stop().stdout, "")
        self.assertEqual(self.starts(), 2)

    def test_clean_opted_in_tree_checks_missing_and_stale_evidence(self):
        subprocess.run(["git", "add", "."], cwd=self.root, check=True)
        subprocess.run(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                        "-c", "core.hooksPath=/dev/null", "commit", "-qm", "approved check"],
                       cwd=self.root, check=True)
        self.assertEqual(self.stop().stdout, "")
        self.assertEqual(self.starts(), 1)
        self.stop()
        self.assertEqual(self.starts(), 1)
        # Empty commit changes the checked base without making the worktree dirty.
        subprocess.run(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                        "-c", "core.hooksPath=/dev/null", "commit", "--allow-empty", "-qm", "new base"],
                       cwd=self.root, check=True)
        self.assertEqual(self.status()["verification"], "unverified")
        self.assertEqual(self.stop().stdout, "")
        self.assertEqual(self.starts(), 2)

    def test_disabled_and_paused_never_start(self):
        self.configure(automatic=False)
        self.assertIn('"block"', self.stop().stdout)
        self.assertEqual(self.starts(), 0)
        self.configure()
        (self.root / ".claude/guardian-state.json").write_text(json.dumps({
            "schema": 1, "selected_host": "claude", "release": {}, "owned": {},
            "lifecycle": "paused"}))
        self.stop()
        self.assertEqual(self.starts(), 0)
        self.assertFalse(self.status()["enabled"])

    def test_success_reused_and_status_is_read_only(self):
        for host in ("claude", "codex"):
            with self.subTest(host=host):
                (self.root / "source.txt").write_text(host)
                before = self.sources()
                count = self.starts()
                self.assertEqual(self.stop(host).stdout, "")
                self.assertEqual(self.starts(), count + 1)
                self.assertEqual(self.status()["verification"], "succeeded")
                self.assertEqual(self.stop(host).stdout, "")
                self.assertEqual(self.starts(), count + 1)
                self.assertEqual(self.sources(), before)

    def test_failure_no_retry_change_and_regular_resume(self):
        self.configure(code=1)
        before = self.sources()
        self.assertIn("UNVERIFIED", self.stop().stdout)
        self.stop("codex")
        self.assertEqual(self.starts(), 1)
        self.assertEqual(self.status()["attempt"]["exit_code"], 1)
        self.assertEqual(self.sources(), before)
        (self.root / "source.txt").write_text("relevant change")
        self.stop()
        self.assertEqual(self.starts(), 2)
        regular = self.cli("run", str(self.root), "--base", "HEAD", "--json")
        self.assertEqual(regular.returncode, 1, regular.stderr)
        self.assertEqual(self.starts(), 3)
        self.stop()
        self.assertEqual(self.starts(), 3)
        self.configure(code=0)
        self.assertEqual(self.cli("run", str(self.root), "--base", "HEAD").returncode, 0)
        self.assertEqual(self.stop().stdout, "")
        self.assertEqual(self.starts(), 4)

    def test_failed_regular_check_is_not_automatically_repeated(self):
        self.configure(code=1)
        self.assertEqual(self.cli("run", str(self.root), "--base", "HEAD").returncode, 1)
        self.stop()
        self.assertEqual(self.starts(), 1)

    def test_concurrent_stop_does_not_duplicate_a_check(self):
        self.configure(delay=.5)
        payload = json.dumps({"cwd": str(self.root), "hook_event_name": "Stop"})
        first = subprocess.Popen([sys.executable, str(STOP)], cwd=self.root,
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True)
        first.stdin.write(payload)
        first.stdin.close()
        deadline = time.monotonic() + 5
        while self.starts() == 0 and time.monotonic() < deadline:
            time.sleep(.02)
        self.stop("codex")
        first.wait(timeout=5)
        self.assertEqual(first.stdout.read(), "")
        first.stdout.close()
        first.stderr.close()
        self.assertEqual(self.starts(), 1)

    def test_wrong_order_partial_and_stale_evidence(self):
        subprocess.run([sys.executable, str(RECORDER), "--", "true"], cwd=self.root,
                       capture_output=True, check=True)
        self.assertEqual(self.status()["verification"], "unverified")
        self.stop()
        self.assertEqual(self.starts(), 1)
        (self.root / "source.txt").write_text("after check")
        self.assertEqual(self.status()["verification"], "unverified")
        self.stop()
        self.assertEqual(self.starts(), 2)

    def test_changed_command_requires_new_approval(self):
        config_path = self.root / ".claude/agent-guard.json"
        config = json.loads(config_path.read_text())
        config["gate_command"] = "true"
        config_path.write_text(json.dumps(config))
        self.assertIn("reapprove", self.stop().stdout)
        self.assertEqual(self.starts(), 0)
        self.assertEqual(self.cli("handoff", str(self.root), "--reason", "Choose the gate").returncode, 0)
        self.assertEqual(self.stop().stdout, "")
        self.assertIn("UNVERIFIED", self.stop().stderr)

    def test_source_change_during_run_does_not_pass(self):
        # A lying check-only declaration is not a sandbox; detect its stale evidence.
        self.configure(gate=f"{sys.executable} check.py 0 0 && echo altered > source.txt")
        self.assertIn("UNVERIFIED", self.stop().stdout)
        self.assertEqual(self.status()["verification"], "unverified")

    def test_timeout_kills_children_without_retry(self):
        child = self.root / "child.py"
        child.write_text("from pathlib import Path\nimport time\ntime.sleep(2)\nPath('.git/orphan').touch()\n")
        self.configure(gate=f"{sys.executable} child.py & {sys.executable} check.py 10 0",
                       seconds=1)
        started = time.monotonic()
        proc = self.stop()
        self.assertLess(time.monotonic() - started, 5)
        self.assertIn("timeout", proc.stdout)
        self.stop()
        self.assertEqual(self.starts(), 1)
        self.assertEqual(self.status()["verification"], "unverified")
        time.sleep(2)
        self.assertFalse((self.root / ".git/orphan").exists())

    def test_interruption_is_recorded_and_not_repeated(self):
        self.configure(delay=10)
        proc = subprocess.Popen([sys.executable, str(STOP)], cwd=self.root,
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True)
        proc.stdin.write(json.dumps({"cwd": str(self.root), "hook_event_name": "Stop"}))
        proc.stdin.close()
        deadline = time.monotonic() + 5
        while self.starts() == 0 and time.monotonic() < deadline:
            time.sleep(.02)
        self.assertEqual(self.starts(), 1)
        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=5)
        self.assertIn("interrupted", proc.stdout.read())
        proc.stdout.close()
        proc.stderr.close()
        self.stop()
        self.assertEqual(self.starts(), 1)

    def test_missing_tool_and_unreadable_attempt_are_visible(self):
        self.configure(gate="guardian-nonexistent-fixture-tool")
        self.assertIn("UNVERIFIED", self.stop().stdout)
        status = self.status()
        self.assertEqual(status["attempt"]["exit_code"], 127)
        self.assertIn("not found", (self.root / ".git/guardian-completion/stderr.log").read_text())
        (self.root / ".git/guardian-completion/state.json").write_text("broken")
        self.assertIn("unavailable/unverified", self.stop().stdout)

    def test_long_gate_regular_path_and_handoff(self):
        self.configure(automatic=False)
        proc = self.cli("handoff", str(self.root), "--reason",
                        "Gate still open; two corrections failed; choose expected behavior.")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        before = self.sources()
        stopped = self.stop("codex")
        self.assertEqual(stopped.stdout, "")
        self.assertIn("UNVERIFIED", stopped.stderr)
        self.assertEqual(self.status()["verification"], "unverified")
        self.assertEqual(self.starts(), 0)
        self.assertEqual(self.sources(), before)
        self.assertEqual(self.cli("run", str(self.root), "--base", "HEAD").returncode, 0)
        self.assertEqual(self.status()["verification"], "succeeded")

    def test_setup_preview_activation_disable_and_repair_rejection(self):
        self.configure(automatic=False)
        before = self.sources()
        preview = self.cli("setup", str(self.root), "--automatic-check", "2")
        self.assertEqual(preview.returncode, 0, preview.stdout)
        self.assertEqual(self.sources(), before)
        applied = self.cli("setup", str(self.root), "--automatic-check", "2", "--apply")
        self.assertEqual(applied.returncode, 0, applied.stdout)
        self.assertTrue(self.status()["enabled"])
        disabled = self.cli("setup", str(self.root), "--no-automatic-check", "--apply")
        self.assertEqual(disabled.returncode, 0, disabled.stdout)
        self.assertFalse(self.status()["enabled"])
        for gate in ("ruff check --fix .", "prettier --write .", "cargo fmt"):
            rejected = self.cli("setup", str(self.root), "--gate", gate,
                                "--automatic-check", "2", "--apply")
            self.assertNotEqual(rejected.returncode, 0, rejected.stdout)
        rejected = self.cli("setup", str(self.root), "--automatic-check", "60", "--apply")
        self.assertNotEqual(rejected.returncode, 0, rejected.stdout)


class CodexCompletionTests(CompletionTests):
    """Run the same behavior matrix independently with Codex's native payload."""

    def stop(self, host="codex", **event):
        return super().stop(host, **event)


if __name__ == "__main__":
    unittest.main()
