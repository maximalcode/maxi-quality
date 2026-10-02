#!/usr/bin/env python3
"""Exercise Guardian through real subprocesses and invented Git projects."""

import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

BASELINE = Path(__file__).resolve().parent.parent
RUNNER = BASELINE / "scripts/guardian.py"
STOP = BASELINE / "scripts/agent-guard/stop-gate.py"
CASES = BASELINE / "samples/guardian/cases.json"


def command(argv, cwd, **kwargs):
    return subprocess.run(argv, cwd=cwd, capture_output=True, text=True, **kwargs)


def project(path, gate="printf 'ok\\n'"):
    path.mkdir()
    command(["git", "init", "-q", str(path)], path, check=True)
    (path / "source.txt").write_text("original\n")
    if gate is not None:
        (path / ".claude").mkdir()
        (path / ".claude/agent-guard.json").write_text(json.dumps({"gate_command": gate}))
    command(["git", "add", "."], path, check=True)
    command(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
             "-c", "core.hooksPath=/dev/null", "commit", "-qm", "fixture"], path, check=True)
    return path.resolve()


def run(root, cwd=None, base="HEAD", **kwargs):
    proc = command([sys.executable, str(RUNNER), "run", str(root), "--base", base,
                    "--task", "fixture task", "--json"], cwd or root, **kwargs)
    return proc, json.loads(proc.stdout)


class GuardianTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def test_outcomes(self):
        cases = json.loads(CASES.read_text())
        self.assertGreater(len(cases), 0)
        for case in cases:
            with self.subTest(case=case["name"]):
                root = project(self.root / case["name"], case["gate"])
                proc, report = run(root, base=case.get("base", "HEAD"))
                self.assertEqual(proc.returncode, case["exit"], proc.stderr)
                self.assertEqual(report["schema_version"], 1)
                self.assertEqual(set(report), {
                    "schema_version", "created_at", "project_root", "working_directory",
                    "comparison", "command", "argv", "checked_state", "execution",
                    "outcome", "freshness", "analysis_scope", "finding_attribution",
                    "requirements", "receipt", "stdout", "stderr", "report_path", "error",
                })
                self.assertEqual(report["outcome"], case["outcome"])
                self.assertEqual(report["command"], case["gate"])
                self.assertEqual(report["project_root"], str(root))
                self.assertEqual(report["working_directory"], str(root))
                self.assertEqual(report["analysis_scope"], "unknown")
                self.assertEqual(report["finding_attribution"], "unknown")
                self.assertEqual(report["requirements"]["assessment"], "not_assessed")
                self.assertFalse((root / "second-ran").exists())
                self.assertFalse((root / ".claude/settings.json").exists())
                self.assertFalse((root / ".github").exists())
                self.assertEqual(json.loads(Path(report["report_path"]).read_text()), report)
                if case["outcome"] == "failed":
                    self.assertEqual(report["execution"]["exit_code"], case["exit"])
                    self.assertTrue(Path(report["stderr"]).read_text())
                if case["name"] != "editing-gate":
                    self.assertEqual((root / "source.txt").read_text(), "original\n")
                if case["gate"] is not None:
                    self.assertEqual(json.loads((root / ".claude/agent-guard.json").read_text()),
                                     {"gate_command": case["gate"]})

    def test_staleness_and_stop_compatibility(self):
        root = project(self.root / "project")
        (root / "source.txt").write_text("before gate\n")
        _, report = run(root)
        receipt = (root / ".claude/agent-guard-receipt.json").read_bytes()
        def check():
            return command([sys.executable, str(RUNNER), "check", report["report_path"], "--json"], root)
        def stop():
            result = command([sys.executable, str(STOP)], root,
                             input=json.dumps({"cwd": str(root)}))
            return result.stdout
        self.assertEqual(check().returncode, 0)
        self.assertNotIn('"decision": "block"', stop())
        (root / "source.txt").write_text("after gate\n")
        self.assertEqual(check().returncode, 3)
        self.assertEqual(json.loads(check().stdout)["freshness"], "stale")
        self.assertIn('"decision": "block"', stop())
        self.assertEqual((root / ".claude/agent-guard-receipt.json").read_bytes(), receipt)

    def test_other_checkout_and_inherited_git_environment(self):
        caller = project(self.root / "caller", "exit 12")
        target = project(self.root / "target", "pwd")
        env = {**os.environ, "GIT_DIR": str(caller / ".git"),
               "GIT_WORK_TREE": str(caller), "GIT_INDEX_FILE": str(caller / ".git/index")}
        proc, report = run(target, cwd=caller, env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(Path(report["stdout"]).read_text().strip(), str(target))
        self.assertFalse((caller / ".claude/agent-guard-receipt.json").exists())
        self.assertTrue((target / ".claude/agent-guard-receipt.json").exists())

    def test_committed_change_is_stale_even_with_clean_worktree(self):
        root = project(self.root / "project")
        _, report = run(root)
        (root / "source.txt").write_text("new committed content\n")
        command(["git", "add", "source.txt"], root, check=True)
        command(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                 "-c", "core.hooksPath=/dev/null", "commit", "-qm", "change"], root, check=True)
        proc = command([sys.executable, str(RUNNER), "check", report["report_path"], "--json"], root)
        self.assertEqual(proc.returncode, 3)
        self.assertEqual(json.loads(proc.stdout)["freshness"], "stale")

    def test_human_report_without_requirements_claim(self):
        root = project(self.root / "project")
        proc = command([sys.executable, str(RUNNER), "run", str(root), "--base", "HEAD"], root)
        self.assertEqual(proc.returncode, 0)
        for value in (str(root), "printf", "Analysis scope: unknown", "Requirements: not assessed",
                      "Checked state:", "Execution:"):
            self.assertIn(value, proc.stdout)

    def test_shell_cannot_start_does_not_reuse_old_receipt(self):
        root = project(self.root / "project")
        _, previous = run(root)
        receipt = Path(previous["receipt"]).read_bytes()
        binaries = self.root / "bin"
        binaries.mkdir()
        (binaries / "git").symlink_to(shutil.which("git"))
        proc, report = run(root, env={**os.environ, "PATH": str(binaries)})
        self.assertEqual(proc.returncode, 3)
        self.assertEqual(report["outcome"], "incomplete")
        self.assertEqual(report["execution"], {"outcome": "not_run", "exit_code": None})
        self.assertIsNone(report["receipt"])
        self.assertIn("bash", report["error"])
        self.assertEqual(Path(previous["receipt"]).read_bytes(), receipt)

    def test_linked_worktree_keeps_evidence_separate(self):
        root = project(self.root / "project")
        target = self.root / "linked"
        command(["git", "worktree", "add", "-qb", "fixture", str(target)], root, check=True)
        proc, report = run(target, cwd=root)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertFalse((root / ".claude/agent-guard-receipt.json").exists())
        self.assertTrue(Path(report["report_path"]).is_file())
        self.assertIn("worktrees", Path(report["report_path"]).parts)
        self.assertEqual(report["project_root"], str(target.resolve()))

    def test_receipt_write_failure_retains_executed_failure(self):
        root = project(self.root / "project", "exit 21")
        (root / ".claude/agent-guard-receipt.json").mkdir()
        proc, report = run(root)
        self.assertEqual(proc.returncode, 21)
        self.assertEqual(report["outcome"], "incomplete")
        self.assertEqual(report["execution"], {"outcome": "failed", "exit_code": 21})
        self.assertIsNone(report["receipt"])

    def test_invalid_root(self):
        proc, report = run(self.root)
        self.assertEqual(proc.returncode, 3)
        self.assertEqual(report["outcome"], "incomplete")


if __name__ == "__main__":
    unittest.main()
