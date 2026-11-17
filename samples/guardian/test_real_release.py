"""End-to-end setup against the immutable Guardian release used by consumers."""

import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest

from test_setup_hosts import BASELINE, RUNNER, command, project


VERSION = "v1.3.0"
COMMIT = "8940116445bbeed3637983e1cd756629eafba7d5"


class RealReleaseSetupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = BASELINE
        expected_tag = command(
            ["git", "rev-parse", "--verify", f"refs/tags/{VERSION}^{{commit}}"], source)
        if expected_tag.returncode:
            raise AssertionError(f"required release tag {VERSION} is unavailable: {expected_tag.stderr}")
        if expected_tag.stdout.strip() != COMMIT:
            raise AssertionError(
                f"{VERSION} resolves to {expected_tag.stdout.strip()}, expected {COMMIT}")
        available = command(["git", "cat-file", "-e", f"{COMMIT}^{{commit}}"], source)
        if available.returncode:
            raise AssertionError(f"required payload commit {COMMIT} is unavailable: {available.stderr}")
        checkout_head = command(["git", "rev-parse", "HEAD"], source)
        dirty = bool(command(["git", "status", "--porcelain"], source).stdout.strip())
        print(f"payload: {VERSION} {COMMIT}")
        print(f"tested setup checkout: HEAD {checkout_head.stdout.strip()} dirty={str(dirty).lower()}")

    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="guardian-real-release-")
        self.addCleanup(temp.cleanup)
        self.temp = temp
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.cache = self.root / "cache"
        self.env = {**os.environ, "HOME": str(self.home),
                    "MAXI_QUALITY_RUNTIME_CACHE": str(self.cache)}
        self.source = BASELINE

    def target(self, name):
        target = project(self.root / name, guardian_gate=False)
        self.assertFalse((target / ".claude/agent-guard.json").exists())
        self.assertFalse((target / ".claude/quality-runtime.json").exists())
        self.assertFalse((target / ".claude/agent-guard-receipt.json").exists())
        self.assertFalse((target / ".claude/skills/guardian").exists())
        self.assertFalse((target / ".agents/skills/guardian").exists())
        return target

    def snapshot(self, target):
        saved = {}
        for path in target.rglob("*"):
            relative = path.relative_to(target)
            if ".git" in relative.parts:
                continue
            mode = stat.S_IMODE(path.lstat().st_mode)
            if path.is_symlink():
                saved[str(relative)] = ("symlink", os.readlink(path), mode)
            elif path.is_dir():
                saved[str(relative)] = ("directory", mode)
            elif path.is_file():
                saved[str(relative)] = ("file", path.read_bytes(), mode)
        return saved

    def assert_initial_inventory(self, target):
        inventory = self.snapshot(target)
        self.assertEqual(set(inventory), {"source.txt"})
        self.assertEqual(inventory["source.txt"][:2], ("file", b"fixture\n"))

    def setup(self, target, *args):
        return command([sys.executable, str(RUNNER), "setup", str(target),
                        "--source", str(self.source), "--version", VERSION,
                        "--commit", COMMIT, *args], target, self.env)

    def read_report(self, result):
        self.assertTrue(result.stdout, result.stderr)
        try:
            return json.loads(result.stdout)
        except ValueError as exc:
            self.fail(f"Guardian CLI did not return JSON: {exc}: {result.stdout!r}")

    def run_guardian(self, target):
        return command([sys.executable, str(RUNNER), "run", str(target), "--base", "HEAD", "--json"],
                       target, self.env)

    def status(self, target):
        result = command([sys.executable, str(RUNNER), "status", str(target), "--json"],
                         target, self.env)
        return result, self.read_report(result)

    def exercise_real_release_setup(self, host):
        target = self.target(host)
        self.assert_initial_inventory(target)
        before_preview = self.snapshot(target)
        gate = "printf 'guardian-real-release-gate\\n' >> .git/guardian-gate-runs"
        marker = target / ".git/guardian-gate-runs"

        preview_result = self.setup(target, "--guardian", host, "--gate", gate)
        preview = self.read_report(preview_result)
        self.assertEqual(preview_result.returncode, 0, preview)
        self.assertEqual(preview["outcome"], "preview")
        self.assertEqual(preview["host"], host)
        self.assertIn("preview", preview["next_step"].lower())
        self.assertIn(".claude/agent-guard.json", preview["changes"])
        self.assertIn(".claude/quality-runtime.json", preview["changes"])
        skill = ".claude/skills/guardian" if host == "claude" else ".agents/skills/guardian"
        self.assertIn(skill, preview["changes"])
        self.assertFalse(marker.exists(), "preview must not execute the selected gate")
        self.assertEqual(self.snapshot(target), before_preview,
                         "preview must leave the complete project inventory unchanged")
        self.assertFalse(self.cache.exists(), "preview must not populate the runtime cache")

        applied_result = self.setup(target, "--guardian", host, "--gate", gate, "--apply")
        applied = self.read_report(applied_result)
        self.assertEqual(applied_result.returncode, 0, applied)
        self.assertEqual(applied["outcome"], "applied")
        self.assertEqual(applied["verification"]["outcome"], "succeeded")
        self.assertEqual(applied["verification"]["execution"]["outcome"], "succeeded")
        self.assertEqual(applied["host"], host)
        self.assertEqual(applied["host_trust"], "unverified")
        self.assertEqual(marker.read_text(), "guardian-real-release-gate\n")

        config_path = target / ".claude/agent-guard.json"
        config = json.loads(config_path.read_text())
        self.assertEqual(config["gate_command"], gate)
        self.assertNotIn("automatic_completion", config)
        if host == "claude":
            self.assertTrue((target / ".claude/settings.json").is_file())
            self.assertFalse((target / ".codex/hooks.json").exists())
        else:
            self.assertTrue((target / ".codex/hooks.json").is_file())
            self.assertFalse((target / ".claude/settings.json").exists())

        cache_recorder = self.cache / COMMIT / "record-gate.py"
        release_recorder = command(
            ["git", "show", f"{COMMIT}:scripts/agent-guard/record-gate.py"], self.source)
        self.assertEqual(release_recorder.returncode, 0, release_recorder.stderr)
        self.assertEqual(cache_recorder.read_bytes(), release_recorder.stdout.encode())

        run_result = self.run_guardian(target)
        run_report = self.read_report(run_result)
        self.assertEqual(run_result.returncode, 0, run_report)
        self.assertEqual(run_report["outcome"], "succeeded")
        self.assertEqual(run_report["execution"]["outcome"], "succeeded")
        self.assertEqual(run_report["command"], gate)
        receipt_path = target / ".claude/agent-guard-receipt.json"
        self.assertEqual(run_report["receipt"], str(receipt_path))
        receipt = json.loads(receipt_path.read_text())
        self.assertEqual(receipt["gate_command"], gate)
        self.assertEqual(marker.read_text(),
                         "guardian-real-release-gate\n" * 2,
                         "the public run command must execute through the recorder")

        before_status = self.snapshot(target)
        marker_before_status = marker.read_bytes()
        status_result, status_report = self.status(target)
        self.assertEqual(status_result.returncode, 0, status_report)
        self.assertEqual(status_report["verification"]["outcome"], "succeeded")
        self.assertEqual(status_report["verification"]["freshness"], "current")
        self.assertEqual(status_report["verification"]["report_path"], run_report["report_path"])
        self.assertEqual(status_report["installation"]["status"], "ok")
        self.assertEqual(status_report["installation"]["configured_gate"], gate)
        self.assertEqual(status_report["installation"]["release"]["version"], VERSION)
        self.assertEqual(status_report["installation"]["release"]["commit"], COMMIT)
        self.assertEqual(status_report["selection"]["host"], host)
        self.assertEqual(status_report["host"]["trust"], "unverified")
        self.assertEqual(status_report["host"]["observed_enforcement"], "unverified")
        self.assertEqual(self.snapshot(target), before_status,
                         "status must leave project files and the recorder receipt unchanged")
        self.assertEqual(marker.read_bytes(), marker_before_status,
                         "status must report saved evidence without running the gate")

    def test_real_release_setup_preview_apply_run_and_read_only_status_claude(self):
        self.exercise_real_release_setup("claude")

    def test_real_release_setup_preview_apply_run_and_read_only_status_codex(self):
        self.exercise_real_release_setup("codex")

    def test_public_setup_rejects_missing_and_mismatched_payload_commits(self):
        cases = (
            ("missing", "f" * 40, "does not contain commit"),
            ("mismatched", "HEAD", "release tag v1.3.0 resolves to"),
        )
        for name, bad_commit, expected_error in cases:
            with self.subTest(payload=name):
                target = self.target("negative-" + name)
                if bad_commit == "HEAD":
                    bad_commit = command(["git", "rev-parse", "HEAD"], self.source).stdout.strip()
                    self.assertNotEqual(bad_commit, COMMIT,
                                        "negative mismatch requires a distinct available commit")
                result = command([sys.executable, str(RUNNER), "setup", str(target),
                                  "--guardian", "claude", "--gate", "true",
                                  "--source", str(self.source), "--version", VERSION,
                                  "--commit", bad_commit, "--apply"], target, self.env)
                report = self.read_report(result)
                self.assertEqual(result.returncode, 3, report)
                self.assertEqual(report["outcome"], "refused")
                self.assertIn(expected_error, report["error"])
                self.assertFalse((target / ".claude/agent-guard.json").exists())
                self.assertFalse((target / ".claude/quality-runtime.json").exists())
                self.assertFalse(self.cache.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
