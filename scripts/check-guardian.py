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

class SetupTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.env = {**os.environ, "HOME": str(self.home),
                    "MAXI_QUALITY_RUNTIME_CACHE": str(self.root / "cache")}

    def setup(self, root, *args):
        result = command([sys.executable, str(RUNNER), "setup", str(root), *args], root, env=self.env)
        return result, json.loads(result.stdout)

    def snapshot(self, root):
        return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*")
                if p.is_file() and ".git" not in p.relative_to(root).parts}

    def release(self):
        source = project(self.root / "release")
        shutil.copytree(BASELINE / "scripts/agent-guard", source / "scripts/agent-guard")
        shutil.copy(BASELINE / "scripts/quality-runtime.py", source / "scripts/quality-runtime.py")
        command(["git", "add", "."], source, check=True)
        command(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                 "-c", "core.hooksPath=/dev/null", "commit", "-qm", "release fixture"], source, check=True)
        command(["git", "tag", "v9.0.0"], source, check=True)
        sha = command(["git", "rev-parse", "HEAD"], source, check=True).stdout.strip()
        return source, ["--source", str(source), "--version", "v9.0.0", "--commit", sha]

    def test_existing_gate_preview_and_reapply(self):
        gate = "printf one && printf two"
        root = project(self.root / "project", gate)
        before = self.snapshot(root)
        proc, report = self.setup(root)
        self.assertEqual(proc.returncode, 0, report)
        self.assertEqual(report["selected_gate"], gate)
        self.assertEqual(report["changes"], {})
        self.assertEqual(self.snapshot(root), before)
        for _ in range(2):
            proc, report = self.setup(root, "--apply")
            self.assertEqual(proc.returncode, 0, report)
            self.assertEqual(report["outcome"], "unchanged")
            self.assertEqual(self.snapshot(root), before)
        self.assertEqual(report["tests"], "not_inferred")

    def test_fresh_rust_local_checks(self):
        root = project(self.root / "rust", None)
        fixture = BASELINE / "samples/guardian/rust-local"
        shutil.copytree(fixture, root, dirs_exist_ok=True)
        for name in ("Cargo.toml", "Cargo.lock"):
            (root / (name + ".fixture")).rename(root / name)
        before = self.snapshot(root)
        proc, report = self.setup(root)
        self.assertEqual(proc.returncode, 3)
        self.assertIn("Cargo.toml", report["quality_configuration"])
        self.assertIn("cargo test --offline", report["suggestions"])
        self.assertEqual(self.snapshot(root), before)
        gate = "cargo test --offline"
        proc, report = self.setup(root, "--gate", gate)
        self.assertEqual(proc.returncode, 0, report)
        self.assertEqual(self.snapshot(root), before)
        proc, report = self.setup(root, "--gate", gate, "--apply")
        self.assertEqual(proc.returncode, 0, report)
        self.assertFalse((root / ".codex").exists())
        self.assertFalse((root / ".claude/settings.json").exists())
        self.assertFalse((root / ".github").exists())
        proc, evidence = run(root)
        self.assertEqual(proc.returncode, 0, evidence)
        self.assertIn("1 passed", Path(evidence["stdout"]).read_text())

    def test_versioned_codex_setup_preview_update_and_failure(self):
        source, release = self.release()
        root = project(self.root / "project")
        (root / ".codex").mkdir()
        unrelated = {"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "echo hello"}]}]}}
        (root / ".codex/hooks.json").write_text(json.dumps(unrelated))
        before = self.snapshot(root)
        proc, report = self.setup(root, "--guardian", "codex", *release)
        self.assertEqual(proc.returncode, 0, report)
        self.assertEqual(self.snapshot(root), before)
        self.assertFalse((self.root / "cache").exists())
        self.assertFalse((self.home / ".local").exists())
        proc, report = self.setup(root, "--guardian", "codex", *release, "--apply")
        self.assertEqual(proc.returncode, 0, report)
        self.assertEqual(report["verification"]["outcome"], "succeeded")
        self.assertEqual(report["host_trust"], "unverified")
        installed = json.loads((root / ".codex/hooks.json").read_text())
        self.assertEqual(installed["hooks"]["SessionStart"], unrelated["hooks"]["SessionStart"])
        self.assertFalse((root / ".claude/settings.json").exists())
        before = self.snapshot(root)
        proc, report = self.setup(root)
        self.assertEqual(proc.returncode, 0, report)
        self.assertEqual(report["current_version"]["version"], "v9.0.0")
        self.assertEqual(report["changes"], {})
        for _ in range(2):
            proc, report = self.setup(root, "--apply")
            self.assertEqual(proc.returncode, 0, report)
            self.assertEqual(self.snapshot(root), before)
        bad_release = [*release]
        bad_release[3] = "v9.9.9"
        proc, report = self.setup(root, *bad_release, "--apply")
        self.assertEqual(proc.returncode, 3)
        self.assertEqual(self.snapshot(root), before)
        # A distinct immutable payload activates, then honestly reports a failed gate.
        (source / "scripts/agent-guard/guard.py").write_text(
            (source / "scripts/agent-guard/guard.py").read_text() + "\n# second fixture release\n")
        command(["git", "add", "."], source, check=True)
        command(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                 "-c", "core.hooksPath=/dev/null", "commit", "-qm", "second release"], source, check=True)
        command(["git", "tag", "v9.0.1"], source, check=True)
        sha = command(["git", "rev-parse", "HEAD"], source, check=True).stdout.strip()
        update = ["--source", str(source), "--version", "v9.0.1", "--commit", sha, "--gate", "exit 17"]
        proc, report = self.setup(root, *update)
        self.assertEqual(proc.returncode, 0, report)
        self.assertEqual(report["current_version"]["version"], "v9.0.0")
        self.assertEqual(report["requested_version"]["version"], "v9.0.1")
        proc, report = self.setup(root, *update, "--apply")
        self.assertEqual(proc.returncode, 17, report)
        self.assertEqual(report["outcome"], "applied_checks_failed")
        self.assertEqual(report["verification"]["execution"]["exit_code"], 17)
        self.assertEqual(json.loads((root / ".claude/quality-runtime.json").read_text())["commit"], sha)

    def test_refusals_do_not_write(self):
        for name, content in ((".claude/agent-guard.json", "[]"),
                              (".codex/hooks.json", '{"hooks": []}'),
                              (".claude/quality-runtime.json", "{}"),
                              ("Cargo.toml", "[broken")):
            with self.subTest(name=name):
                root = project(self.root / (name.replace("/", "-").replace(".", "_")))
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
                before = self.snapshot(root)
                proc, report = self.setup(root, "--gate", "true", "--apply")
                self.assertEqual(proc.returncode, 3, report)
                self.assertEqual(self.snapshot(root), before)

    def test_rejected_payload_and_workflow_pins_preserve_selection(self):
        source, release = self.release()
        root = project(self.root / "project")
        proc, report = self.setup(root, *release, "--apply")
        self.assertEqual(proc.returncode, 0, report)
        before = self.snapshot(root)
        # A tagged payload with invalid Python is rejected before activation.
        (source / "scripts/agent-guard/guard.py").write_text("invalid Python !")
        command(["git", "add", "."], source, check=True)
        command(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                 "-c", "core.hooksPath=/dev/null", "commit", "-qm", "invalid payload"], source, check=True)
        command(["git", "tag", "v9.0.1"], source, check=True)
        sha = command(["git", "rev-parse", "HEAD"], source, check=True).stdout.strip()
        proc, report = self.setup(root, "--source", str(source), "--version", "v9.0.1",
                                  "--commit", sha, "--apply")
        self.assertEqual(proc.returncode, 3, report)
        self.assertEqual(self.snapshot(root), before)
        workflows = root / ".github/workflows"
        workflows.mkdir(parents=True)
        (workflows / "quality.yml").write_text(
            "jobs:\n  quality:\n    uses: maximalcode/maxi-quality/.github/workflows/quality.yml@v1\n")
        before = self.snapshot(root)
        proc, report = self.setup(root, "--apply")
        self.assertEqual(proc.returncode, 3, report)
        self.assertIn("workflow", report["error"].lower())
        self.assertEqual(self.snapshot(root), before)

    def test_symlink_refused_before_writing(self):
        root = project(self.root / "project")
        outside = self.root / "outside"
        outside.write_text("untouched")
        (root / "AGENTS.md").symlink_to(outside)
        proc, report = self.setup(root, "--gate", "true", "--apply")
        self.assertEqual(proc.returncode, 3, report)
        self.assertEqual(outside.read_text(), "untouched")

    def test_legacy_profile_is_not_migrated(self):
        root = project(self.root / "project")
        # Existing copied configuration remains on its current delivery path.
        directory = root / ".claude/agent-guard"
        shutil.copytree(BASELINE / "scripts/agent-guard", directory)
        settings = json.loads((BASELINE / "configs/agent/settings.json").read_text())
        settings["hooks"]["PreToolUse"] = [group for group in settings["hooks"]["PreToolUse"]
                                              if group.get("matcher") != "Edit|Write|MultiEdit"]
        (root / ".claude/settings.json").write_text(json.dumps(settings))
        before = self.snapshot(root)
        proc, report = self.setup(root, "--apply")
        self.assertEqual(proc.returncode, 0, report)
        self.assertEqual(report["installation_profile"], "legacy-copied")
        self.assertEqual(self.snapshot(root), before)


if __name__ == "__main__":
    unittest.main()
