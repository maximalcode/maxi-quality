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
PREREQUISITES = BASELINE / "samples/guardian/prerequisites"


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
                    "next_step",
                })
                self.assertEqual(report["outcome"], case["outcome"])
                if case["outcome"] == "succeeded":
                    self.assertIsNone(report["next_step"])
                else:
                    self.assertIsInstance(report["next_step"], str)
                    self.assertTrue(report["next_step"].strip())
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


class PrerequisiteTests(unittest.TestCase):
    """Exercise owner recovery with invented commands and real subprocesses."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.env = {**os.environ, "PATH": os.environ.get("PATH", "")}

    def fixture_project(self, name, gate, executable=None):
        root = project(self.root / name, gate)
        if executable is not None:
            source = PREREQUISITES / executable
            destination = root / "bin" / source.name
            destination.parent.mkdir()
            shutil.copy2(source, destination)
            destination.chmod(destination.stat().st_mode | 0o111)
        return root

    @staticmethod
    def command_v(executable, root, env):
        # This is an independent fact check, rather than a helper that asks
        # Guardian or parses its output.
        return command(["bash", "-c", "command -v \"$1\"", "bash", executable],
                       root, env=env).stdout.strip() or None

    @staticmethod
    def full_snapshot(root):
        """Capture files, modes and symlink targets, including .git state."""
        snapshot = {}
        for path in root.rglob("*"):
            relative = str(path.relative_to(root))
            if path.is_symlink():
                snapshot[relative] = ("symlink", os.readlink(path))
            elif path.is_file():
                snapshot[relative] = ("file", path.stat().st_mode & 0o777,
                                      path.read_bytes())
        return snapshot

    def setup_preview(self, root):
        proc = command([sys.executable, str(RUNNER), "setup", str(root), "--json"],
                       root, env=self.env)
        return proc, json.loads(proc.stdout)

    def assert_recovery_step(self, report):
        self.assertIsInstance(report["next_step"], str)
        step = report["next_step"].lower()
        self.assertTrue(step.strip())
        self.assertIn("unknown", step)
        self.assertTrue("output" in step or "error" in step or "report" in step)
        self.assertIn("guardian-setup.md#recover-an-unavailable-prerequisite", step)

    def assert_setup_step(self, report):
        self.assertIsInstance(report["next_step"], str)
        step = report["next_step"].lower()
        self.assertIn("preview", step)
        self.assertIn("whole", step)
        self.assertIn("guardian-setup.md#recover-an-unavailable-prerequisite", step)

    def test_installed_outside_path_requires_explicit_process_path_recovery(self):
        tail = self.root / "tail-marker"
        gate = "guardian-installed-check && printf 'tail ran\\n' > \"$GUARDIAN_TAIL_FILE\""
        root = self.fixture_project("installed-outside-path", gate, "guardian-installed-check")
        base_env = {**self.env, "GUARDIAN_TAIL_FILE": str(tail)}

        before = self.full_snapshot(root)
        proc, preview = self.setup_preview(root)
        self.assertEqual(proc.returncode, 0, preview)
        self.assertEqual(preview["selected_gate"], gate)
        self.assertEqual(preview["changes"], {})
        self.assert_setup_step(preview)
        self.assertEqual(self.full_snapshot(root), before)
        self.assertFalse((root / ".claude/agent-guard-receipt.json").exists())

        installed = root / "bin/guardian-installed-check"
        self.assertTrue(installed.is_file())
        self.assertTrue(os.access(installed, os.X_OK))
        self.assertIsNone(self.command_v(installed.name, root, base_env))
        proc, failed = run(root, env=base_env)
        self.assertEqual(proc.returncode, 127, failed)
        self.assertEqual(failed["command"], gate)
        self.assertEqual(failed["execution"], {"outcome": "failed", "exit_code": 127})
        self.assertEqual(failed["outcome"], "failed")
        self.assertFalse(tail.exists(), "the compound gate must short-circuit before its tail")
        self.assert_recovery_step(failed)
        old_receipt = (root / ".claude/agent-guard-receipt.json").read_bytes()
        old_receipt_data = json.loads(old_receipt)
        self.assertEqual(old_receipt_data["verdict"], "fail")
        self.assertEqual(old_receipt_data["exit_code"], 127)
        old_report = Path(failed["report_path"]).read_bytes()
        old_stdout = Path(failed["stdout"]).read_bytes()
        old_stderr = Path(failed["stderr"]).read_bytes()

        before = self.full_snapshot(root)
        self.assertEqual(self.setup_preview(root)[0].returncode, 0)
        self.assertIsNone(self.command_v(installed.name, root, base_env))
        self.assertEqual(self.full_snapshot(root), before)
        self.assertEqual((root / ".claude/agent-guard-receipt.json").read_bytes(), old_receipt)

        corrected_env = {**base_env, "PATH": str(installed.parent) + os.pathsep + base_env["PATH"]}
        self.assertTrue(self.command_v(installed.name, root, corrected_env))
        proc, succeeded = run(root, env=corrected_env)
        self.assertEqual(proc.returncode, 0, succeeded)
        self.assertEqual(succeeded["command"], gate)
        self.assertEqual(succeeded["execution"], {"outcome": "succeeded", "exit_code": 0})
        self.assertEqual(succeeded["outcome"], "succeeded")
        self.assertEqual(succeeded["freshness"], "current")
        self.assertIsNone(succeeded["next_step"])
        self.assertEqual(tail.read_text(), "tail ran\n")
        receipt = json.loads((root / ".claude/agent-guard-receipt.json").read_text())
        self.assertEqual(receipt["verdict"], "pass")
        self.assertEqual(receipt["gate_command"], gate)
        self.assertNotEqual((root / ".claude/agent-guard-receipt.json").read_bytes(), old_receipt)
        checked_new = command([sys.executable, str(RUNNER), "check", succeeded["report_path"], "--json"], root)
        self.assertEqual(checked_new.returncode, 0)
        self.assertEqual(json.loads(checked_new.stdout)["freshness"], "current")

        # The recovery changed only this subprocess's PATH. Failed evidence
        # remains immutable, and checking it cannot turn it into a pass.
        self.assertEqual(Path(failed["report_path"]).read_bytes(), old_report)
        self.assertEqual(Path(failed["stdout"]).read_bytes(), old_stdout)
        self.assertEqual(Path(failed["stderr"]).read_bytes(), old_stderr)
        checked = command([sys.executable, str(RUNNER), "check", failed["report_path"], "--json"], root)
        self.assertEqual(checked.returncode, 3)
        self.assertEqual(json.loads(checked.stdout)["outcome"], "failed")

    def test_missing_executable_and_opaque_failure_keep_cause_unknown(self):
        missing = "./bin/guardian-missing-command-285"
        root = self.fixture_project("absent-executable", missing)
        proc, preview = self.setup_preview(root)
        self.assertEqual(proc.returncode, 0, preview)
        self.assert_setup_step(preview)
        self.assertIsNone(self.command_v(missing, root, self.env))
        self.assertFalse((root / missing).exists())
        proc, report = run(root, env=self.env)
        self.assertEqual(proc.returncode, 127, report)
        self.assertEqual(report["outcome"], "failed")
        self.assert_recovery_step(report)
        self.assertNotIn("guardian-missing-command-285", report["next_step"])
        human = command([sys.executable, str(RUNNER), "run", str(root), "--base", "HEAD"],
                        root, env=self.env)
        self.assertEqual(human.returncode, 127)
        for value in ("Next step:", "Cause unknown", "GUARDIAN-SETUP.md#recover-an-unavailable-prerequisite"):
            self.assertIn(value, human.stdout)

        root = self.fixture_project("opaque-gate", "guardian-opaque-gate", "guardian-opaque-gate")
        self.assertIsNone(self.command_v("guardian-opaque-gate", root, self.env))
        opaque_env = {**self.env, "PATH": str(root / "bin") + os.pathsep + self.env["PATH"]}
        self.assertTrue(self.command_v("guardian-opaque-gate", root, opaque_env))
        proc, opaque = run(root, env=opaque_env)
        self.assertEqual(proc.returncode, 42, opaque)
        self.assertEqual(opaque["outcome"], "failed")
        self.assert_recovery_step(opaque)
        self.assertIn("opaque gate failure", Path(opaque["stderr"]).read_text())

    def test_available_exit_127_and_misleading_stderr_are_not_missing_prerequisites(self):
        cases = (("guardian-available-exit-127", 127, "deliberate exit 127"),
                 ("guardian-misleading-failure", 19, "dependency missing"))
        for executable, exit_code, stderr in cases:
            with self.subTest(executable=executable):
                root = self.fixture_project(executable, executable, executable)
                env = {**self.env, "PATH": str(root / "bin") + os.pathsep + self.env["PATH"]}
                self.assertTrue(self.command_v(executable, root, env))
                proc, report = run(root, env=env)
                self.assertEqual(proc.returncode, exit_code, report)
                self.assertEqual(report["outcome"], "failed")
                self.assertIn(stderr, Path(report["stderr"]).read_text())
                self.assert_recovery_step(report)


class SkillTests(unittest.TestCase):
    def test_installed_skill_uses_local_interfaces_and_revalidates_repair(self):
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            installed = temp / "skills/guardian"
            installed.parent.mkdir()
            installed.symlink_to(BASELINE / "skills/guardian", target_is_directory=True)
            skill = installed / "SKILL.md"
            self.assertTrue(skill.is_file())
            runner = skill.resolve().parents[2] / "scripts/guardian.py"
            self.assertEqual(runner, RUNNER)
            fixture = json.loads((BASELINE / "samples/guardian/skill-review.json").read_text())
            gate = fixture["gate"]
            root = project(temp / "project", gate)
            (root / "SPEC.md").write_text(fixture["task"])
            original = {name: (root / name).read_bytes() for name in
                        ("source.txt", "SPEC.md", ".claude/agent-guard.json")}

            def invoke(*args):
                proc = command([sys.executable, str(runner), *args, "--json"], root)
                return proc, json.loads(proc.stdout)

            _, preview = invoke("setup", str(root))
            self.assertEqual(preview["selected_gate"], gate)
            self.assertEqual(preview["changes"], {})
            direct, measured = run(root)
            proc, reviewed = invoke("run", str(root), "--base", "HEAD", "--task", "SPEC.md")
            self.assertEqual(proc.returncode, direct.returncode)
            for key in ("command", "argv", "execution", "outcome", "freshness", "checked_state"):
                self.assertEqual(reviewed[key], measured[key])
            self.assertEqual(reviewed["next_step"], measured["next_step"])
            self.assertEqual(reviewed["execution"], {"outcome": "failed", "exit_code": 1})
            self.assertEqual(reviewed["requirements"], {"reference": "SPEC.md", "assessment": "not_assessed"})
            self.assertEqual(reviewed["finding_attribution"], "unknown")
            _, missing_task = invoke("run", str(root), "--base", "HEAD")
            self.assertEqual(missing_task["requirements"], {"reference": None, "assessment": "not_assessed"})
            self.assertEqual({name: (root / name).read_bytes() for name in original}, original)
            receipt = Path(reviewed["receipt"]).read_bytes()
            failed_report = Path(reviewed["report_path"]).read_bytes()
            # A separate human-decision note is never consumed as success evidence.
            override = Path(reviewed["report_path"]).parent / "human-decision.txt"
            override.write_text("Invented human decision: proceed despite this failed check.\n")
            proc, observation = invoke("check", reviewed["report_path"])
            self.assertEqual(proc.returncode, 3)
            self.assertEqual(observation["outcome"], "failed")
            self.assertEqual(Path(reviewed["receipt"]).read_bytes(), receipt)
            (root / "source.txt").write_text(fixture["repair"])
            _, observation = invoke("check", reviewed["report_path"])
            self.assertEqual(observation["freshness"], "stale")
            proc, repaired = invoke("run", str(root), "--base", "HEAD", "--task", "SPEC.md")
            self.assertEqual(proc.returncode, 0, repaired)
            self.assertEqual(repaired["outcome"], "succeeded")
            self.assertEqual(invoke("check", repaired["report_path"])[0].returncode, 0)
            self.assertEqual(Path(reviewed["report_path"]).read_bytes(), failed_report)
            for name in ("SPEC.md", ".claude/agent-guard.json"):
                self.assertEqual((root / name).read_bytes(), original[name])
            unavailable = project(temp / "unavailable", None)
            proc, missing = invoke("run", str(unavailable), "--base", "HEAD")
            self.assertEqual(proc.returncode, 3)
            self.assertEqual(missing["execution"]["outcome"], "not_run")
            self.assertEqual(missing["outcome"], "incomplete")


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

    def test_local_setup_preserves_linked_instructions(self):
        root = project(self.root / "project")
        (root / "CLAUDE.md").write_text("Shared project instructions.\n")
        (root / "AGENTS.md").symlink_to("CLAUDE.md")
        before = self.snapshot(root)
        for args in ((), ("--apply",), ("--apply",)):
            proc, report = self.setup(root, *args)
            self.assertEqual(proc.returncode, 0, report)
            self.assertEqual(report["changes"], {})
            self.assertEqual(self.snapshot(root), before)
        proc, report = self.setup(root, "--gate", "printf selected", "--apply")
        self.assertEqual(proc.returncode, 0, report)
        self.assertEqual(set(report["changes"]), {".claude/agent-guard.json"})
        self.assertEqual((root / "AGENTS.md").readlink(), Path("CLAUDE.md"))
        self.assertEqual((root / "CLAUDE.md").read_bytes(), before["CLAUDE.md"])

    def test_native_setup_still_refuses_linked_instructions(self):
        root = project(self.root / "project")
        (root / "CLAUDE.md").write_text("Shared project instructions.\n")
        (root / "AGENTS.md").symlink_to("CLAUDE.md")
        _, release = self.release()
        before = self.snapshot(root)
        proc, report = self.setup(root, "--guardian", "codex", *release, "--apply")
        self.assertEqual(proc.returncode, 3, report)
        self.assertEqual(report["outcome"], "refused")
        self.assertIn("reconcile symbolic links", report["error"])
        self.assertEqual(self.snapshot(root), before)
        self.assertEqual((root / "AGENTS.md").readlink(), Path("CLAUDE.md"))

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
        self.assertIn("preview", report["next_step"].lower())
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
        self.assertEqual(report["next_step"], report["verification"]["next_step"])
        self.assertEqual(json.loads((root / ".claude/quality-runtime.json").read_text())["commit"], sha)

    def test_setup_accepts_trusted_prior_launcher_and_rejects_tampering(self):
        source, _ = self.release()
        launcher = source / "scripts/quality-runtime.py"
        # The first release deliberately has a launcher from an older immutable
        # release.  The setup process itself is newer, so this catches identity
        # checks that silently equate the guard pin with the launcher source.
        launcher.write_text(launcher.read_text() + "\n# prior release launcher\n")
        command(["git", "add", "scripts/quality-runtime.py"], source, check=True)
        command(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                 "-c", "core.hooksPath=/dev/null", "commit", "-qm", "prior launcher"], source,
                check=True)
        command(["git", "tag", "-f", "v9.0.0"], source, check=True)
        prior_sha = command(["git", "rev-parse", "HEAD"], source, check=True).stdout.strip()
        prior_release = ["--source", str(source), "--version", "v9.0.0", "--commit", prior_sha]

        root = project(self.root / "project")
        proc, report = self.setup(root, "--guardian", "codex", *prior_release, "--apply")
        self.assertEqual(proc.returncode, 0, report)
        installed = self.home / ".local/share/maxi-quality/launchers" / prior_sha / "quality-runtime"
        self.assertNotEqual(installed.read_bytes(), (BASELINE / "scripts/quality-runtime.py").read_bytes())

        # A read-only preview of the existing installation must accept that
        # trusted prior launcher and preserve the target byte-for-byte.
        before = self.snapshot(root)
        proc, report = self.setup(root, "--source", str(source))
        self.assertEqual(proc.returncode, 0, report)
        self.assertEqual(report["changes"], {})
        self.assertEqual(self.snapshot(root), before)

        # A deliberate immutable update selects a newer launcher and payload.
        launcher.write_text((BASELINE / "scripts/quality-runtime.py").read_text()
                            + "\n# selected update launcher\n")
        (source / "scripts/agent-guard/guard.py").write_text(
            (source / "scripts/agent-guard/guard.py").read_text() + "\n# selected update\n")
        command(["git", "add", "."], source, check=True)
        command(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                 "-c", "core.hooksPath=/dev/null", "commit", "-qm", "selected update"], source,
                check=True)
        command(["git", "tag", "v9.0.1"], source, check=True)
        update_sha = command(["git", "rev-parse", "HEAD"], source, check=True).stdout.strip()
        update = ["--source", str(source), "--version", "v9.0.1", "--commit", update_sha]
        proc, report = self.setup(root, *update)
        self.assertEqual(proc.returncode, 0, report)
        self.assertEqual(report["current_version"]["commit"], prior_sha)
        self.assertEqual(report["requested_version"]["commit"], update_sha)
        self.assertIn(".codex/hooks.json", report["changes"])
        self.assertIn("AGENTS.md", report["changes"])
        self.assertEqual(installed.read_bytes(), (source / "scripts/quality-runtime.py").read_bytes()
                         .replace(b"# selected update launcher", b"# prior release launcher"))
        proc, report = self.setup(root, *update, "--apply")
        self.assertEqual(proc.returncode, 0, report)
        updated_launcher = self.home / ".local/share/maxi-quality/launchers" / update_sha / "quality-runtime"
        # Updates install the selected compatible launcher at a new immutable
        # location and leave the prior launcher untouched.
        self.assertEqual(installed.read_bytes(), (source / "scripts/quality-runtime.py").read_bytes()
                         .replace(b"# selected update launcher", b"# prior release launcher"))
        self.assertEqual(updated_launcher.read_bytes(), (source / "scripts/quality-runtime.py").read_bytes())
        diagnosed = command([str(updated_launcher), "diagnose", "--root", str(root),
                             "--host", "codex", "--json"], root, env=self.env)
        self.assertEqual(diagnosed.returncode, 0, diagnosed.stderr + diagnosed.stdout)
        self.assertTrue(json.loads(diagnosed.stdout)["healthy"])

        # A launcher that is absent from the explicit source's immutable tags
        # is untrusted; setup must refuse before touching the target.
        updated_launcher.write_bytes(updated_launcher.read_bytes() + b"\n# tampered\n")
        before = self.snapshot(root)
        proc, report = self.setup(root, "--source", str(source))
        self.assertEqual(proc.returncode, 3, report)
        self.assertIn("trusted", report["error"].lower())
        self.assertEqual(self.snapshot(root), before)

    def test_setup_upgrades_format1_launcher_to_format2(self):
        source, _ = self.release()
        # Make a self-contained format-1 release: its launcher and payload have
        # no native Codex adapter, so a later format-2 update must move to a
        # new launcher location instead of overwriting this one.
        (source / "scripts/agent-guard/codex-patch-guard.py").unlink()
        old_launcher = source / "scripts/quality-runtime.py"
        old_launcher.write_text(old_launcher.read_text().replace("FORMAT = 2", "FORMAT = 1", 1))
        command(["git", "add", "."], source, check=True)
        command(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                 "-c", "core.hooksPath=/dev/null", "commit", "-qm", "format one release"], source,
                check=True)
        command(["git", "tag", "-f", "v9.0.0"], source, check=True)
        prior_sha = command(["git", "rev-parse", "HEAD"], source, check=True).stdout.strip()
        root = project(self.root / "format-one")
        prior_launcher_dir = self.home / ".local/share/maxi-quality/launchers" / prior_sha
        prepare = command([sys.executable, str(BASELINE / "scripts/quality-runtime.py"), "prepare",
                           "--source", str(source), "--version", "v9.0.0", "--commit", prior_sha,
                           "--cache-root", str(self.root / "cache")], root, env=self.env)
        self.assertEqual(prepare.returncode, 0, prepare.stderr)
        install = command([sys.executable, str(BASELINE / "scripts/quality-runtime.py"), "install",
                           "--source", str(source), "--commit", prior_sha,
                           "--install-root", str(prior_launcher_dir)], root, env=self.env)
        self.assertEqual(install.returncode, 0, install.stderr)
        migrate = command([sys.executable, str(BASELINE / "scripts/quality-runtime-migrate.py"),
                           "--target", str(root), "--host", "claude", "--version", "v9.0.0",
                           "--commit", prior_sha, "--launcher", str(prior_launcher_dir / "quality-runtime")],
                          root, env=self.env)
        self.assertEqual(migrate.returncode, 0, migrate.stderr)
        old_bytes = (prior_launcher_dir / "quality-runtime").read_bytes()

        # Select a tagged format-2 release containing the native adapter.
        shutil.copy(BASELINE / "scripts/agent-guard/codex-patch-guard.py",
                    source / "scripts/agent-guard/codex-patch-guard.py")
        shutil.copy(BASELINE / "scripts/quality-runtime.py", source / "scripts/quality-runtime.py")
        command(["git", "add", "."], source, check=True)
        command(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                 "-c", "core.hooksPath=/dev/null", "commit", "-qm", "format two update"], source,
                check=True)
        command(["git", "tag", "v9.0.1"], source, check=True)
        update_sha = command(["git", "rev-parse", "HEAD"], source, check=True).stdout.strip()
        update = ["--source", str(source), "--version", "v9.0.1", "--commit", update_sha]
        proc, report = self.setup(root, *update)
        self.assertEqual(proc.returncode, 0, report)
        self.assertIn(".claude/settings.json", report["changes"])
        proc, report = self.setup(root, *update, "--apply")
        self.assertEqual(proc.returncode, 0, report)
        updated_launcher = self.home / ".local/share/maxi-quality/launchers" / update_sha / "quality-runtime"
        self.assertEqual((prior_launcher_dir / "quality-runtime").read_bytes(), old_bytes)
        self.assertEqual(updated_launcher.read_bytes(), (source / "scripts/quality-runtime.py").read_bytes())
        diagnosed = command([str(updated_launcher), "diagnose", "--root", str(root), "--json"],
                            root, env=self.env)
        self.assertEqual(diagnosed.returncode, 0, diagnosed.stderr + diagnosed.stdout)
        self.assertTrue(json.loads(diagnosed.stdout)["healthy"])

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
        # Native setup writes instructions; local-only setup does not.
        _, release = self.release()
        before = self.snapshot(root)
        proc, report = self.setup(root, "--guardian", "codex", *release,
                                  "--gate", "true", "--apply")
        self.assertEqual(proc.returncode, 3, report)
        self.assertEqual(self.snapshot(root), before)
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
