#!/usr/bin/env python3
"""Consumer fixtures prove coupled guard/workflow pins fail together."""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
CHECK = ROOT / "scripts" / "check-quality-lock.py"
COMMIT = "a" * 40


class ReleaseLockTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="quality-lock-")
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        (self.root / ".claude").mkdir()
        (self.root / ".github/workflows").mkdir(parents=True)
        self.lock = dict(schema=1, source="maximalcode/maxi-quality", version="v1.2.0",
                         commit=COMMIT, guard_enabled=False)

    def write_lock(self):
        (self.root / ".claude/quality-runtime.json").write_text(json.dumps(self.lock))

    def workflow(self, filename="quality.yml", commit=COMMIT, version="v1.2.0"):
        (self.root / ".github/workflows" / filename).write_text(
            "name: quality\non: [push, pull_request]\njobs:\n  quality:\n"
            f"    uses: maximalcode/maxi-quality/.github/workflows/{filename}@{commit} # {version}\n"
        )

    def result(self):
        return subprocess.run([sys.executable, str(CHECK), str(self.root)],
                              text=True, capture_output=True)

    def test_legacy_consumer_has_no_new_requirement(self):
        self.workflow(commit="v1")
        self.assertEqual(self.result().returncode, 0)

    def test_workflow_only_and_guard_only_profiles(self):
        self.write_lock()
        self.workflow()
        self.assertEqual(self.result().returncode, 0)
        (self.root / ".github/workflows/quality.yml").unlink()
        self.lock["guard_enabled"] = True
        self.write_lock()
        self.assertEqual(self.result().returncode, 0)

    def test_report_cannot_lag_behind_gate(self):
        self.write_lock()
        self.workflow()
        self.workflow("quality-report.yaml", commit="b" * 40)
        result = self.result()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("quality-report.yaml:5", result.stderr)

    def test_mutable_ref_wrong_comment_and_partial_sha_fail(self):
        self.write_lock()
        for commit, version in [("v1", "v1.2.0"), (COMMIT, "v1.1.0"),
                                ("a" * 12, "v1.2.0")]:
            with self.subTest(commit=commit, version=version):
                self.workflow(commit=commit, version=version)
                self.assertNotEqual(self.result().returncode, 0)

    def test_invalid_lock_cannot_silently_disable_check(self):
        self.workflow()
        for key, value in [("schema", True), ("guard_enabled", "false"),
                           ("source", "example/untrusted"), ("extra", "command")]:
            with self.subTest(key=key):
                old = self.lock.copy()
                self.lock[key] = value
                self.write_lock()
                self.assertNotEqual(self.result().returncode, 0)
                self.lock = old

    def test_yaml_quoted_keys_and_folded_values_cannot_hide_moving_ref(self):
        self.write_lock()
        for use in ['"uses": maximalcode/maxi-quality/.github/workflows/quality.yml@v1',
                    'uses: >-\n      maximalcode/maxi-quality/.github/workflows/quality.yml@v1']:
            with self.subTest(use=use):
                (self.root / ".github/workflows/quality.yml").write_text(
                    "jobs:\n  quality:\n    " + use + "\n")
                self.assertNotEqual(self.result().returncode, 0)


if __name__ == "__main__":
    unittest.main()
