"""Exercise immutable Guardian updates through the public setup command."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

BASELINE = Path(__file__).resolve().parents[2]
RUNNER = BASELINE / "scripts/guardian.py"


def command(argv, cwd, env):
    return subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True,
                          check=False)


def project(path, gate="true"):
    path.mkdir()
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    (path / "source.txt").write_text("fixture\n")
    (path / ".claude").mkdir()
    (path / ".claude/agent-guard.json").write_text(
        json.dumps({"gate_command": gate}) + "\n")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "-c", "user.name=Fixture", "-c",
                    "user.email=fixture@example.invalid", "-c", "core.hooksPath=/dev/null",
                    "commit", "-qm", "fixture"], cwd=path, check=True)
    return path.resolve()


class GuardianUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.env = {**os.environ, "HOME": str(self.home),
                    "MAXI_QUALITY_RUNTIME_CACHE": str(self.root / "cache")}
        self.source = project(self.root / "source")
        shutil.copytree(BASELINE / "scripts", self.source / "scripts")
        shutil.copytree(BASELINE / "skills/guardian", self.source / "skills/guardian")
        (self.source / "docs").mkdir()
        for name in ("GUARDIAN.md", "GUARDIAN-SETUP.md", "GUARDIAN-SKILL.md"):
            shutil.copy(BASELINE / "docs" / name, self.source / "docs" / name)
        subprocess.run(["git", "add", "."], cwd=self.source, check=True)
        subprocess.run(["git", "-c", "user.name=Fixture", "-c",
                        "user.email=fixture@example.invalid", "-c", "core.hooksPath=/dev/null",
                        "commit", "-qm", "release base"], cwd=self.source, check=True)
        self.release = self.make_release("v9.0.0", "first release")
        self.target = project(self.root / "target")
        result = self.setup("--guardian", "claude", *self.release, "--apply")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.release = self.make_release("v9.0.1", "updated release")

    def make_release(self, version, note):
        (self.source / "scripts/agent-guard/guard.py").write_text(
            (BASELINE / "scripts/agent-guard/guard.py").read_text() + f"\n# {note}\n")
        subprocess.run(["git", "add", "scripts/agent-guard/guard.py"],
                       cwd=self.source, check=True)
        subprocess.run(["git", "-c", "user.name=Fixture", "-c",
                        "user.email=fixture@example.invalid", "-c", "core.hooksPath=/dev/null",
                        "commit", "-qm", note], cwd=self.source, check=True)
        subprocess.run(["git", "tag", version], cwd=self.source, check=True)
        sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.source,
                                      text=True).strip()
        return ["--source", str(self.source), "--version", version, "--commit", sha]

    def setup(self, *args, env=None):
        return command([sys.executable, str(RUNNER), "setup", str(self.target),
                        *args, "--json"], self.target, env or self.env)

    def snapshot(self):
        return {str(path.relative_to(self.target)): path.read_bytes()
                for path in self.target.rglob("*") if path.is_file() and ".git" not in path.parts}

    def lock(self):
        return json.loads((self.target / ".claude/quality-runtime.json").read_text())

    def test_update_preview_and_success_are_candidate_pinned_and_idempotent(self):
        before = self.snapshot()
        preview = self.setup("--guardian", "claude", *self.release)
        report = json.loads(preview.stdout)
        self.assertEqual(preview.returncode, 0, report)
        self.assertEqual(report["current_version"]["version"], "v9.0.0")
        self.assertEqual(report["requested_version"]["version"], "v9.0.1")
        self.assertIn(".claude/settings.json", report["changes"])
        self.assertEqual(self.snapshot(), before)

        applied = self.setup("--guardian", "claude", *self.release, "--apply")
        result = json.loads(applied.stdout)
        self.assertEqual(applied.returncode, 0, result)
        self.assertEqual(result["outcome"], "applied")
        self.assertEqual(result["verification"]["outcome"], "succeeded")
        self.assertEqual(result["verification"]["candidate"]["version"], "v9.0.1")
        selected = self.snapshot()
        repeated = self.setup("--guardian", "claude", *self.release, "--apply")
        self.assertEqual(repeated.returncode, 0, repeated.stdout + repeated.stderr)
        self.assertEqual(json.loads(repeated.stdout)["outcome"], "unchanged")
        self.assertEqual(self.snapshot(), selected)

    def test_successful_gate_must_not_replace_candidate_runtime_pin(self):
        old_lock = self.target / ".git/old-lock.json"
        old_lock.write_bytes((self.target / ".claude/quality-runtime.json").read_bytes())
        gitignore = self.target / ".gitignore"
        gitignore.write_text(gitignore.read_text() + ".claude/quality-runtime.json\n")

        update = self.setup("--guardian", "claude", *self.release,
                            "--gate", "cp .git/old-lock.json .claude/quality-runtime.json",
                            "--apply")
        report = json.loads(update.stdout)

        self.assertNotEqual(update.returncode, 0, report)
        self.assertNotEqual(report["outcome"], "applied")
        self.assertEqual(self.lock()["version"], "v9.0.0")
        self.assertIn(".claude/quality-runtime.json", report["error"])

    def test_update_without_host_flag_refreshes_saved_host_state_and_lifecycle(self):
        codex_target = project(self.root / "codex-target")
        old_commit = subprocess.check_output(["git", "rev-parse", "v9.0.0"],
                                              cwd=self.source, text=True).strip()
        codex_setup = command([sys.executable, str(RUNNER), "setup", str(codex_target),
                               "--source", str(self.source), "--version", "v9.0.0",
                               "--commit", old_commit, "--guardian", "codex", "--apply", "--json"],
                              codex_target, self.env)
        self.assertEqual(codex_setup.returncode, 0, codex_setup.stdout + codex_setup.stderr)

        for target, host in ((self.target, "claude"), (codex_target, "codex")):
            updated = command([sys.executable, str(RUNNER), "setup", str(target),
                               "--source", str(self.source), *self.release, "--apply", "--json"],
                              target, self.env)
            report = json.loads(updated.stdout)
            self.assertEqual(updated.returncode, 0, report)
            state = json.loads((target / ".claude/guardian-state.json").read_text())
            self.assertEqual(state["selected_host"], host)
            self.assertEqual(state["release"]["version"], "v9.0.1")
            self.assertEqual(state["release"]["commit"], self.release[-1])

            status = command([sys.executable, str(RUNNER), "status", str(target),
                              "--json"], target, self.env)
            self.assertEqual(status.returncode, 0, status.stdout + status.stderr)
            status_report = json.loads(status.stdout)
            self.assertEqual(status_report["selection"]["host"], host)
            for action in ("pause", "resume"):
                lifecycle = command([sys.executable, str(RUNNER), action, str(target),
                                     "--apply", "--json"], target, self.env)
                self.assertEqual(lifecycle.returncode, 0,
                                 lifecycle.stdout + lifecycle.stderr)

    def test_failed_gate_restores_prior_owned_state_and_retains_failure_evidence(self):
        before = self.snapshot()
        old_lock = self.lock()
        failed = self.setup("--guardian", "claude", *self.release, "--gate", "exit 17",
                            "--apply")
        report = json.loads(failed.stdout)
        self.assertEqual(failed.returncode, 17)
        self.assertEqual(report["outcome"], "update_checks_failed")
        self.assertEqual(report["verification"]["outcome"], "failed")
        self.assertTrue(Path(report["verification"]["report_path"]).is_file())
        self.assertEqual(self.lock(), old_lock)
        self.assertEqual({key: value for key, value in self.snapshot().items()
                          if key != ".claude/agent-guard-receipt.json"},
                         {key: value for key, value in before.items()
                          if key != ".claude/agent-guard-receipt.json"})
        self.assertEqual((self.target / ".claude/agent-guard-receipt.json").read_bytes(),
                         before[".claude/agent-guard-receipt.json"])

    def test_unavailable_candidate_verification_restores_prior_state(self):
        before = self.snapshot()
        update = self.make_release("v9.0.2", "candidate unavailable")
        # Keep the runner executable while making its shell prerequisite unavailable.
        binaries = self.root / "limited-bin"
        binaries.mkdir()
        for name in ("git", "python3"):
            (binaries / name).symlink_to(shutil.which(name))
        limited_env = {**self.env, "PATH": str(binaries)}
        failed = self.setup("--guardian", "claude", *update, "--gate", "true", "--apply",
                            env=limited_env)
        report = json.loads(failed.stdout)
        self.assertEqual(failed.returncode, 3)
        self.assertEqual(report["outcome"], "update_checks_incomplete")
        self.assertEqual(report["verification"]["outcome"], "incomplete")
        self.assertEqual(self.lock()["version"], "v9.0.0")
        self.assertEqual(self.snapshot()[".claude/settings.json"], before[".claude/settings.json"])

    def test_terminated_verification_rolls_back_and_reports_interruption(self):
        before = self.snapshot()
        failed = self.setup("--guardian", "claude", *self.release, "--gate",
                            'kill -TERM "$GUARDIAN_UPDATE_PARENT_PID"; sleep 0.1; exit 0',
                            "--apply")
        report = json.loads(failed.stdout)
        self.assertEqual(report["outcome"], "update_interrupted")
        self.assertEqual(report["verification"]["outcome"], "interrupted")
        self.assertEqual(self.lock()["version"], "v9.0.0")
        self.assertEqual((self.target / ".claude/settings.json").read_bytes(),
                         before[".claude/settings.json"])

    def test_hard_interruption_is_visible_until_explicit_recovery(self):
        argv = [sys.executable, str(RUNNER), "setup", str(self.target), "--guardian", "claude",
                *self.release, "--gate",
                'kill -KILL "$GUARDIAN_UPDATE_PARENT_PID"; sleep 4; exit 0', "--apply", "--json"]
        process = subprocess.Popen(argv, cwd=self.target, env=self.env, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True)
        self.assertEqual(process.wait(timeout=5), -9)
        pending_path = self.target / ".git/guardian-update-pending.json"
        self.assertTrue(pending_path.is_file())

        preview = self.setup()
        preview_report = json.loads(preview.stdout)
        self.assertEqual(preview.returncode, 3)
        self.assertEqual(preview_report["outcome"], "update_pending")
        status = command([sys.executable, str(RUNNER), "status", str(self.target), "--json"],
                         self.target, self.env)
        status_report = json.loads(status.stdout)
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertEqual(status_report["verification"]["outcome"], "incomplete")
        self.assertEqual(status_report["installation"]["status"], "update_pending")
        before_pause = self.snapshot()
        pause = command([sys.executable, str(RUNNER), "pause", str(self.target),
                         "--host", "claude", "--apply", "--json"], self.target, self.env)
        self.assertEqual(pause.returncode, 3)
        self.assertIn("setup --apply to recover", json.loads(pause.stdout)["error"])
        self.assertEqual(self.snapshot(), before_pause)

        blocked = self.setup("--apply")
        blocked_report = json.loads(blocked.stdout)
        self.assertEqual(blocked.returncode, 3)
        self.assertIn("still running", blocked_report["error"])
        process.communicate(timeout=5)
        time.sleep(4)

        recovered = self.setup("--apply")
        recovery_report = json.loads(recovered.stdout)
        self.assertEqual(recovered.returncode, 0, recovery_report)
        self.assertEqual(recovery_report["outcome"], "update_recovered")
        self.assertEqual(self.lock()["version"], "v9.0.0")
        self.assertFalse(pending_path.exists())

    def test_recovery_refuses_and_preserves_user_changed_candidate_file(self):
        argv = [sys.executable, str(RUNNER), "setup", str(self.target), "--guardian", "claude",
                *self.release, "--gate",
                'kill -KILL "$GUARDIAN_UPDATE_PARENT_PID"; sleep 0.3; exit 0', "--apply", "--json"]
        process = subprocess.Popen(argv, cwd=self.target, env=self.env, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True)
        self.assertEqual(process.wait(timeout=5), -9)
        settings = self.target / ".claude/settings.json"
        settings.write_text(settings.read_text() + "\n")
        process.communicate(timeout=5)
        time.sleep(1)
        recovery = self.setup("--apply")
        report = json.loads(recovery.stdout)
        self.assertEqual(recovery.returncode, 3)
        self.assertIn("preserved them", report["error"])
        self.assertTrue(settings.read_text().endswith("\n\n"))
        self.assertTrue((self.target / ".git/guardian-update-pending.json").is_file())

    def test_failed_update_preserves_gate_edit_and_leaves_recovery_pending(self):
        settings = self.target / ".claude/settings.json"
        edit_then_fail = (
            "python3 -c 'import json,pathlib; p=pathlib.Path(\".claude/settings.json\"); "
            "v=json.loads(p.read_text()); v[\"user_note\"]=\"keep my change\"; "
            "p.write_text(json.dumps(v,indent=2)+\"\\n\")'; exit 17"
        )
        failed = self.setup("--guardian", "claude", *self.release, "--gate", edit_then_fail,
                            "--apply")
        report = json.loads(failed.stdout)

        self.assertEqual(settings.exists(), True)
        self.assertEqual(json.loads(settings.read_text())["user_note"], "keep my change")
        self.assertIn("pending", report["outcome"])
        self.assertTrue((self.target / ".git/guardian-update-pending.json").is_file())
        status = command([sys.executable, str(RUNNER), "status", str(self.target), "--json"],
                         self.target, self.env)
        status_report = json.loads(status.stdout)
        self.assertEqual(status_report["verification"]["pending_update"]["status"],
                         "recovery_conflict")
        self.assertIn(".claude/settings.json",
                      status_report["verification"]["pending_update"]["conflicts"])

    def test_interrupted_update_preserves_gate_edit_and_reports_pending_rollback(self):
        edit_then_interrupt = (
            "python3 -c 'import json,pathlib; p=pathlib.Path(\".claude/settings.json\"); "
            "v=json.loads(p.read_text()); v[\"user_note\"]=\"keep interrupted change\"; "
            "p.write_text(json.dumps(v,indent=2)+\"\\n\")'; "
            'kill -TERM "$GUARDIAN_UPDATE_PARENT_PID"; sleep 0.1; exit 0'
        )
        interrupted = self.setup("--guardian", "claude", *self.release, "--gate",
                                 edit_then_interrupt, "--apply")
        report = json.loads(interrupted.stdout)

        self.assertEqual(report["outcome"], "update_rollback_pending")
        self.assertEqual(json.loads((self.target / ".claude/settings.json").read_text())[
            "user_note"], "keep interrupted change")
        self.assertTrue((self.target / ".git/guardian-update-pending.json").is_file())

    def test_recovery_accepts_a_file_already_restored_before_interruption(self):
        argv = [sys.executable, str(RUNNER), "setup", str(self.target), "--guardian", "claude",
                *self.release, "--gate",
                'kill -KILL "$GUARDIAN_UPDATE_PARENT_PID"; sleep 4; exit 0', "--apply", "--json"]
        process = subprocess.Popen(argv, cwd=self.target, env=self.env, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True)
        self.assertEqual(process.wait(timeout=5), -9)
        pending_path = self.target / ".git/guardian-update-pending.json"
        pending = json.loads(pending_path.read_text())
        entry = pending["paths"][".claude/settings.json"]["before"]
        settings = self.target / ".claude/settings.json"
        settings.write_bytes(__import__("base64").b64decode(entry["value"]))
        os.chmod(settings, entry["mode"])
        # Model a crash after one path has been restored and both workers exited.
        pending["setup_pid"] = -1
        pending["checker_pid"] = -1
        pending_path.write_text(json.dumps(pending))
        process.communicate(timeout=5)

        recovered = self.setup("--apply")
        report = json.loads(recovered.stdout)
        self.assertEqual(recovered.returncode, 0, report)
        self.assertEqual(report["outcome"], "update_recovered")
        self.assertEqual(self.lock()["version"], "v9.0.0")
        self.assertEqual(settings.stat().st_mode & 0o777, entry["mode"])

    def test_update_preview_names_shared_other_host_and_apply_refuses(self):
        old_commit = subprocess.check_output(["git", "rev-parse", "v9.0.0"],
                                              cwd=self.source, text=True).strip()
        codex_project = project(self.root / "codex-project")
        codex = command([sys.executable, str(RUNNER), "setup", str(codex_project),
                         "--guardian", "codex", "--source", str(self.source),
                         "--version", "v9.0.0", "--commit", old_commit,
                         "--apply", "--json"], codex_project, self.env)
        self.assertEqual(codex.returncode, 0, codex.stdout + codex.stderr)
        codex_hooks = self.target / ".codex/hooks.json"
        codex_hooks.parent.mkdir()
        shutil.copy(codex_project / ".codex/hooks.json", codex_hooks)
        before = self.snapshot()

        preview = self.setup("--guardian", "claude", *self.release)
        report = json.loads(preview.stdout)
        self.assertEqual(preview.returncode, 0, report)
        self.assertEqual(report["other_integrations"], ["codex"])
        self.assertTrue(any("shares the project runtime pin" in conflict
                            for conflict in report["integration_conflicts"]))
        self.assertEqual(self.snapshot(), before)

        refused = self.setup("--guardian", "claude", *self.release, "--apply")
        refused_report = json.loads(refused.stdout)
        self.assertEqual(refused.returncode, 3)
        self.assertEqual(refused_report["outcome"], "refused")
        self.assertIn("shares the project runtime pin", refused_report["error"])
        self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
