"""Public CLI slices for selected-host Guardian setup."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

BASELINE = Path(__file__).resolve().parents[2]
RUNNER = BASELINE / "scripts/guardian.py"


def command(argv, cwd, env=None):
    return subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True, check=False)


def project(path, *, guardian_gate=True):
    path.mkdir()
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    (path / "source.txt").write_text("fixture\n")
    if guardian_gate:
        (path / ".claude").mkdir()
        (path / ".claude/agent-guard.json").write_text('{"gate_command":"true"}\n')
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                    "-c", "core.hooksPath=/dev/null", "commit", "-qm", "fixture"], cwd=path, check=True)
    return path.resolve()


class SelectedHostSetupTests(unittest.TestCase):
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
        subprocess.run(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                        "-c", "core.hooksPath=/dev/null", "commit", "-qm", "release fixture"],
                       cwd=self.source, check=True)
        subprocess.run(["git", "tag", "v9.0.0"], cwd=self.source, check=True)
        self.commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.source,
                                              text=True).strip()
        self.target = project(self.root / "target")

    def setup(self, *args):
        result = command([sys.executable, str(RUNNER), "setup", str(self.target),
                          "--source", str(self.source), "--version", "v9.0.0",
                          "--commit", self.commit, *args], self.target, self.env)
        return result, json.loads(result.stdout)

    def installed_runner(self, host):
        skill = self.target / (".claude/skills/guardian/SKILL.md" if host == "claude"
                               else ".agents/skills/guardian/SKILL.md")
        resolved_skill = skill.resolve(strict=True)
        source = resolved_skill.parents[2]
        runner = source / "scripts/guardian.py"
        self.assertTrue(runner.is_file())
        return runner

    def snapshot(self):
        return {str(path.relative_to(self.target)): path.read_bytes()
                for path in self.target.rglob("*") if path.is_file() and ".git" not in path.parts}

    def test_claude_setup_preview_apply_run_and_selected_status(self):
        codex_hooks = self.target / ".codex/hooks.json"
        codex_hooks.parent.mkdir()
        codex_hooks.write_text('{"hooks":{"SessionStart":[{"hooks":[{"type":"command","command":"echo foreign-codex"}]}]}}')
        (self.target / ".codex/config.toml").write_text("[features]\nhooks = false\n")
        foreign_codex = codex_hooks.read_bytes()
        before = self.snapshot()
        result, preview = self.setup("--guardian", "claude")
        self.assertEqual(result.returncode, 0, preview)
        self.assertEqual(preview["host"], "claude")
        self.assertEqual(preview["outcome"], "preview")
        self.assertIn(".claude/skills/guardian", preview["changes"])
        self.assertEqual(self.snapshot(), before)

        result, applied = self.setup("--guardian", "claude", "--apply")
        self.assertEqual(result.returncode, 0, applied)
        self.assertTrue((self.target / ".claude/skills/guardian").is_symlink())
        self.assertEqual((self.target / ".claude/skills/guardian").resolve(),
                         self.source / "skills/guardian")
        self.assertEqual(applied["verification"]["outcome"], "succeeded")
        installed = self.snapshot()
        result, repeated = self.setup("--guardian", "claude", "--apply")
        self.assertEqual(result.returncode, 0, repeated)
        self.assertEqual(repeated["outcome"], "unchanged")
        self.assertEqual(self.snapshot(), installed)
        self.assertEqual(codex_hooks.read_bytes(), foreign_codex)

        runner = self.installed_runner("claude")
        result = command([sys.executable, str(runner), "run", str(self.target),
                          "--base", "HEAD", "--json"], self.target, self.env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        result = command([sys.executable, str(runner), "status", str(self.target), "--json"],
                         self.target, self.env)
        report = json.loads(result.stdout)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(report["host"]["name"], "claude")
        self.assertEqual(report["verification"]["outcome"], "succeeded")
        self.assertEqual(report["installation"]["release"]["version"], "v9.0.0")

    def test_fresh_selected_host_setup_uses_planned_gate_candidate(self):
        for host in ("claude", "codex"):
            with self.subTest(host=host):
                target = project(self.root / f"fresh-{host}", guardian_gate=False)
                (target / "Makefile").write_text("check:\n\t@test -f source.txt\n")
                result = command(
                    [sys.executable, str(RUNNER), "setup", str(target),
                     "--source", str(self.source), "--version", "v9.0.0",
                     "--commit", self.commit, "--gate", "make check",
                     "--guardian", host, "--apply"],
                    target, self.env)
                report = json.loads(result.stdout)
                self.assertEqual(result.returncode, 0, report)
                self.assertEqual(report["host"], host)
                self.assertEqual(
                    json.loads((target / ".claude/agent-guard.json").read_text())["gate_command"],
                    "make check")

    def test_re_setup_does_not_claim_an_edited_instruction_region(self):
        for host, filename in (("claude", "CLAUDE.md"), ("codex", "AGENTS.md")):
            with self.subTest(host=host):
                target = project(self.root / f"edited-{host}")
                (target / filename).write_text("# Personal instructions\nKeep this workflow.\n")
                args = [sys.executable, str(RUNNER), "setup", str(target),
                        "--source", str(self.source), "--version", "v9.0.0",
                        "--commit", self.commit, "--guardian", host, "--apply"]
                first = command(args, target, self.env)
                self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
                instructions = target / filename
                original = instructions.read_text()
                edited = original.replace("<!-- END maxi-quality", "Keep my change.\n<!-- END maxi-quality")
                self.assertNotEqual(edited, original)
                instructions.write_text(edited)

                repeated = command(args, target, self.env)
                report = json.loads(repeated.stdout)
                self.assertEqual(repeated.returncode, 3, report)
                self.assertIn("instruction region", report["error"])
                self.assertEqual(instructions.read_text(), edited)

                removed = command([sys.executable, str(RUNNER), "remove", str(target),
                                   "--apply", "--json"], target, self.env)
                remove_report = json.loads(removed.stdout)
                self.assertEqual(removed.returncode, 3, remove_report)
                self.assertEqual(instructions.read_text(), edited)

    def test_claude_setup_preserves_plain_claude_instructions(self):
        personal = "# Personal instructions\nKeep the existing project workflow.\n"
        instruction = self.target / "CLAUDE.md"
        instruction.write_text(personal)

        result, applied = self.setup("--guardian", "claude", "--apply")
        self.assertEqual(result.returncode, 0, applied)
        text = instruction.read_text()
        self.assertTrue(text.startswith(personal))
        self.assertEqual(text.count("<!-- BEGIN maxi-quality agent-guard"), 1)
        self.assertEqual(text.count("<!-- END maxi-quality agent-guard -->"), 1)
        self.assertIn("record-gate", text)

        result, repeated = self.setup("--guardian", "claude", "--apply")
        self.assertEqual(result.returncode, 0, repeated)
        self.assertEqual(repeated["outcome"], "unchanged")
        self.assertEqual(instruction.read_text(), text)

    def test_claude_setup_preserves_plain_agents_instructions(self):
        personal = "# Shared instructions\nKeep the existing project workflow.\n"
        instruction = self.target / "AGENTS.md"
        instruction.write_text(personal)

        result, applied = self.setup("--guardian", "claude", "--apply")
        self.assertEqual(result.returncode, 0, applied)
        text = instruction.read_text()
        self.assertTrue(text.startswith(personal))
        self.assertEqual(text.count("<!-- BEGIN maxi-quality agent-guard"), 1)
        self.assertEqual(text.count("<!-- END maxi-quality agent-guard -->"), 1)

    def test_claude_region_in_agents_is_removed_using_recorded_path(self):
        personal = "# Shared instructions\nKeep this exact text.\n"
        agents = self.target / "AGENTS.md"
        agents.write_text(personal)
        result, applied = self.setup("--guardian", "claude", "--apply")
        self.assertEqual(result.returncode, 0, applied)
        state = json.loads((self.target / ".claude/guardian-state.json").read_text())
        self.assertEqual(state["owned"]["instruction_region"]["path"], "AGENTS.md")

        removed = command([sys.executable, str(RUNNER), "remove", str(self.target),
                           "--apply", "--json"], self.target, self.env)
        report = json.loads(removed.stdout)
        self.assertEqual(removed.returncode, 0, report)
        self.assertEqual(agents.read_text(), personal)

    def test_switch_back_to_claude_preserves_personal_agents_instructions(self):
        personal = "# Personal instructions\nKeep this workflow.\n"
        agents = self.target / "AGENTS.md"
        agents.write_text(personal)
        result, applied = self.setup("--guardian", "codex", "--apply")
        self.assertEqual(result.returncode, 0, applied)
        codex_agents = agents.read_bytes()
        self.assertTrue(agents.read_text().startswith(personal))

        result = command([sys.executable, str(RUNNER), "switch", str(self.target),
                          "--host", "claude", "--apply", "--json"],
                         self.target, self.env)
        report = json.loads(result.stdout)
        self.assertEqual(result.returncode, 0, report)
        self.assertEqual(report["outcome"], "switched")
        self.assertEqual(agents.read_text(), personal)
        self.assertNotIn("<!-- BEGIN maxi-quality codex-guard", agents.read_text())
        self.assertIn("<!-- BEGIN maxi-quality codex-guard", codex_agents.decode())
        claude = self.target / "CLAUDE.md"
        self.assertTrue(claude.is_file())
        self.assertEqual(claude.read_text().count("<!-- BEGIN maxi-quality agent-guard"), 1)
        self.assertEqual(claude.read_text().count("<!-- END maxi-quality agent-guard -->"), 1)

    def test_claude_setup_keeps_damaged_instruction_region_as_conflict(self):
        instruction = self.target / "CLAUDE.md"
        instruction.write_text(
            "Personal instructions.\n\n"
            "<!-- BEGIN maxi-quality agent-guard -->\n"
            "unfinished\n"
        )
        before = instruction.read_bytes()
        result, refused = self.setup("--guardian", "claude", "--apply")
        self.assertEqual(result.returncode, 3, refused)
        self.assertIn("no complete maxi-quality agent region", refused["error"])
        self.assertEqual(instruction.read_bytes(), before)

    def test_codex_setup_run_and_selected_status(self):
        claude_settings = self.target / ".claude/settings.json"
        claude_settings.write_text('{"hooks":{"SessionStart":[{"hooks":[{"type":"command","command":"echo foreign-claude"}]}]}}')
        foreign_claude = claude_settings.read_bytes()
        result, preview = self.setup("--guardian", "codex")
        self.assertEqual(result.returncode, 0, preview)
        self.assertEqual(preview["host"], "codex")
        self.assertIn(".agents/skills/guardian", preview["changes"])

        result, applied = self.setup("--guardian", "codex", "--apply")
        self.assertEqual(result.returncode, 0, applied)
        self.assertTrue((self.target / ".agents/skills/guardian").is_symlink())
        self.assertEqual((self.target / ".agents/skills/guardian").resolve(),
                         self.source / "skills/guardian")
        self.assertTrue((self.target / ".codex/hooks.json").is_file())
        self.assertEqual(claude_settings.read_bytes(), foreign_claude)
        self.assertTrue((self.target / ".claude/quality-runtime.json").is_file())
        self.assertEqual(applied["host_trust"], "unverified")
        self.assertEqual(applied["verification"]["outcome"], "succeeded")
        state = json.loads((self.target / ".claude/guardian-state.json").read_text())
        self.assertIn("PreToolUse", {hook["event"] for hook in state["owned"]["hooks"]})

        runner = self.installed_runner("codex")
        result = command([sys.executable, str(runner), "run", str(self.target),
                          "--base", "HEAD", "--json"], self.target, self.env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        result = command([sys.executable, str(runner), "status", str(self.target), "--json"],
                         self.target, self.env)
        report = json.loads(result.stdout)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(report["host"]["name"], "codex")
        self.assertEqual(report["host"]["trust"], "unverified")
        state_path = self.target / ".claude/guardian-state.json"
        saved_state = state_path.read_bytes()
        state_path.unlink()
        detected = command([sys.executable, str(runner), "status", str(self.target), "--json"],
                           self.target, self.env)
        detected_report = json.loads(detected.stdout)
        self.assertEqual(detected_report["host"]["name"], "codex")
        self.assertEqual(detected_report["selection"]["source"], "detected-integration")
        state_path.write_bytes(saved_state)
        state["lifecycle"] = "paused"
        state_path.write_text(json.dumps(state))
        explicit = command([sys.executable, str(runner), "status", str(self.target),
                            "--host", "claude", "--json"], self.target, self.env)
        explicit_report = json.loads(explicit.stdout)
        self.assertEqual(explicit_report["host"]["name"], "claude")
        self.assertNotEqual(explicit_report["installation"]["status"], "paused")
        self.assertEqual(explicit_report["installation"]["lifecycle"], "other-host")
        active = command([sys.executable, str(runner), "status", str(self.target), "--json"],
                         self.target, self.env)
        self.assertEqual(active.returncode, 0, active.stderr)
        active_report = json.loads(active.stdout)
        self.assertNotEqual(active_report["installation"]["status"], "paused")
        self.assertEqual(active_report["installation"]["lifecycle"], "broken")
        before = self.snapshot()
        refused, refusal = self.setup("--guardian", "codex", "--apply")
        self.assertEqual(refused.returncode, 3, refusal)
        self.assertIn("is paused", refusal["error"])
        self.assertEqual(self.snapshot(), before)

        state["lifecycle"] = "removed"
        state_path.write_text(json.dumps(state))
        (self.target / ".codex/hooks.json").unlink()
        status_after_remove = command(
            [sys.executable, str(runner), "status", str(self.target), "--json"],
            self.target, self.env)
        self.assertEqual(json.loads(status_after_remove.stdout)["installation"]["status"],
                         "not-installed")
        implicit, implicit_report = self.setup()
        self.assertEqual(implicit.returncode, 3, implicit_report)
        self.assertIn("re-setup requires explicit", implicit_report["error"])
        explicit, explicit_report = self.setup("--guardian", "codex", "--apply")
        self.assertEqual(explicit.returncode, 0, explicit_report)
        self.assertEqual(explicit_report["verification"]["outcome"], "succeeded")

    def test_codex_setup_preserves_foreign_skill_link(self):
        foreign = self.root / "foreign-skill"
        foreign.mkdir()
        codex_skills = self.target / ".agents/skills"
        codex_skills.mkdir(parents=True)
        link = codex_skills / "guardian"
        link.symlink_to(foreign, target_is_directory=True)
        before_link = link.readlink()
        result, preview = self.setup("--guardian", "codex")
        self.assertEqual(result.returncode, 0, preview)
        self.assertIn(".agents/skills/guardian", preview["conflicts"])
        result, applied = self.setup("--guardian", "codex", "--apply")
        self.assertEqual(result.returncode, 0, applied)
        self.assertEqual(link.readlink(), before_link)

    def test_setup_refuses_silent_switch_from_existing_host(self):
        result, _ = self.setup("--guardian", "claude", "--apply")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        before = self.snapshot()
        result, report = self.setup("--guardian", "codex", "--apply")
        self.assertEqual(result.returncode, 3, report)
        self.assertIn("changing an existing host", report["error"])
        self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
