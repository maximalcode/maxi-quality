"""Public CLI behavior for explicitly switching the selected Guardian host."""

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
    return subprocess.run(argv, cwd=cwd, env=env, capture_output=True,
                          text=True, check=False)


def project(path):
    path.mkdir()
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    (path / "source.txt").write_text("fixture\n")
    (path / ".claude").mkdir()
    (path / ".claude/agent-guard.json").write_text('{"gate_command":"true"}\n')
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                    "-c", "core.hooksPath=/dev/null", "commit", "-qm", "fixture"],
                   cwd=path, check=True)
    return path.resolve()


class SwitchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.home = self.base / "home"
        self.home.mkdir()
        self.env = {**os.environ, "HOME": str(self.home),
                    "MAXI_QUALITY_RUNTIME_CACHE": str(self.base / "cache")}
        self.source = project(self.base / "source")
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
        self.target = project(self.base / "target")

    def setup_guardian(self, host="claude"):
        result = command([sys.executable, str(RUNNER), "setup", str(self.target),
                          "--source", str(self.source), "--version", "v9.0.0",
                          "--commit", self.commit, "--guardian", host, "--apply"],
                         self.target, self.env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def switch(self, host, apply=False):
        argv = [sys.executable, str(RUNNER), "switch", str(self.target),
                "--host", host, "--json"]
        if apply:
            argv.append("--apply")
        result = command(argv, self.target, self.env)
        return result, json.loads(result.stdout)

    def snapshot(self):
        return {str(path.relative_to(self.target)): path.read_bytes()
                for path in self.target.rglob("*") if path.is_file() and ".git" not in path.parts}

    def test_switches_both_directions_with_preview_idempotency_and_foreign_settings(self):
        self.setup_guardian("claude")
        codex_settings = self.target / ".codex/hooks.json"
        codex_settings.parent.mkdir()
        codex_settings.write_text(json.dumps({"hooks": {"SessionStart": [{
            "hooks": [{"type": "command", "command": "echo foreign-codex"}]
        }]}}, indent=2) + "\n")
        gate_before = (self.target / ".claude/agent-guard.json").read_bytes()
        lock_before = (self.target / ".claude/quality-runtime.json").read_bytes()
        before = self.snapshot()

        preview_proc, preview = self.switch("codex")
        self.assertEqual(preview_proc.returncode, 0, preview)
        self.assertEqual(preview["outcome"], "preview")
        self.assertEqual(preview["from_host"], "claude")
        self.assertEqual(preview["to_host"], "codex")
        self.assertEqual(self.snapshot(), before)

        applied_proc, applied = self.switch("codex", apply=True)
        self.assertEqual(applied_proc.returncode, 0, applied)
        self.assertEqual(applied["outcome"], "switched")
        self.assertEqual(applied["trust"], "unverified")
        self.assertEqual((self.target / ".claude/agent-guard.json").read_bytes(), gate_before)
        self.assertEqual((self.target / ".claude/quality-runtime.json").read_bytes(), lock_before)
        self.assertFalse(any("stop-gate" in json.dumps(entry)
                             for entry in json.loads((self.target / ".claude/settings.json").read_text())
                             .get("hooks", {}).values()))
        self.assertIn("foreign-codex", codex_settings.read_text())
        self.assertTrue((self.target / ".agents/skills/guardian").is_symlink())
        self.assertFalse((self.target / ".claude/skills/guardian").exists())
        state = json.loads((self.target / ".claude/guardian-state.json").read_text())
        self.assertEqual(state["selected_host"], "codex")

        repeated_proc, repeated = self.switch("codex", apply=True)
        self.assertEqual(repeated_proc.returncode, 0, repeated)
        self.assertEqual(repeated["outcome"], "unchanged")

        claude_settings = self.target / ".claude/settings.json"
        claude_settings.write_text(json.dumps({"hooks": {"SessionStart": [{
            "hooks": [{"type": "command", "command": "echo foreign-claude"}]
        }]}}, indent=2) + "\n")
        back_proc, back = self.switch("claude", apply=True)
        self.assertEqual(back_proc.returncode, 0, back)
        self.assertEqual(back["outcome"], "switched")
        self.assertIn("foreign-claude", claude_settings.read_text())
        self.assertIn("foreign-codex", codex_settings.read_text())
        self.assertFalse(any("codex-patch-guard" in json.dumps(entry)
                             for entry in json.loads(codex_settings.read_text())
                             .get("hooks", {}).values()))
        self.assertTrue((self.target / ".claude/skills/guardian").is_symlink())
        self.assertFalse((self.target / ".agents/skills/guardian").exists())
        self.assertNotIn("<!-- BEGIN maxi-quality codex-guard",
                         (self.target / "AGENTS.md").read_text())
        self.assertEqual(json.loads((self.target / ".claude/guardian-state.json").read_text())["selected_host"],
                         "claude")

    def test_refuses_target_hooks_prerequisite_and_keeps_old_state(self):
        self.setup_guardian("claude")
        codex_settings = self.target / ".codex/hooks.json"
        codex_settings.parent.mkdir()
        codex_settings.write_text(json.dumps({"hooks": {"PreToolUse": [{
            "matcher": "apply_patch",
            "hooks": [{"type": "command", "command": "quality-runtime custom-guard"}]
        }]}}, indent=2) + "\n")
        before = self.snapshot()
        result, report = self.switch("codex", apply=True)
        self.assertEqual(result.returncode, 3, report)
        self.assertEqual(report["outcome"], "refused")
        self.assertIn("reconcile", report["error"])
        self.assertEqual(self.snapshot(), before)

        codex_settings.write_text('{}\n')
        (self.target / ".codex/config.toml").write_text("[features]\nhooks = false\n")
        before = self.snapshot()
        result, report = self.switch("codex", apply=True)
        self.assertEqual(result.returncode, 3, report)
        self.assertIn("disables hooks", report["error"])
        self.assertEqual(self.snapshot(), before)

    def test_paused_origin_requires_resume_and_keeps_state(self):
        self.setup_guardian("claude")
        paused = command([sys.executable, str(RUNNER), "pause", str(self.target), "--apply", "--json"],
                         self.target, self.env)
        self.assertEqual(paused.returncode, 0, paused.stdout + paused.stderr)
        before = self.snapshot()
        result, report = self.switch("codex", apply=True)
        self.assertEqual(result.returncode, 3, report)
        self.assertIn("resume", report["error"])
        self.assertEqual(self.snapshot(), before)

    def test_instruction_ownership_survives_pause_switch_back_remove_and_re_setup(self):
        personal = "# Personal project instructions\nKeep this workflow.\n"
        (self.target / "CLAUDE.md").write_text(personal)
        self.setup_guardian("claude")

        for action in ("pause", "resume"):
            result = command([sys.executable, str(RUNNER), action, str(self.target),
                              "--apply", "--json"], self.target, self.env)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        switched, report = self.switch("codex", apply=True)
        self.assertEqual(switched.returncode, 0, report)
        switched, report = self.switch("claude", apply=True)
        self.assertEqual(switched.returncode, 0, report)

        removed = command([sys.executable, str(RUNNER), "remove", str(self.target),
                           "--apply", "--json"], self.target, self.env)
        remove_report = json.loads(removed.stdout)
        self.assertEqual(removed.returncode, 0, remove_report)
        self.assertEqual(remove_report["outcome"], "removed")
        self.assertEqual((self.target / "CLAUDE.md").read_text(), personal)

        re_setup = command([sys.executable, str(RUNNER), "setup", str(self.target),
                            "--source", str(self.source), "--version", "v9.0.0",
                            "--commit", self.commit, "--guardian", "claude", "--apply"],
                           self.target, self.env)
        self.assertEqual(re_setup.returncode, 0, re_setup.stdout + re_setup.stderr)

    def test_claude_region_in_personal_agents_is_removed_on_switch(self):
        personal = "# Shared project instructions\nKeep this workflow.\n"
        (self.target / "AGENTS.md").write_text(personal)
        self.setup_guardian("claude")
        self.assertIn("<!-- BEGIN maxi-quality agent-guard", (self.target / "AGENTS.md").read_text())

        switched, report = self.switch("codex", apply=True)
        self.assertEqual(switched.returncode, 0, report)
        agents = (self.target / "AGENTS.md").read_text()
        self.assertTrue(agents.startswith(personal))
        self.assertNotIn("<!-- BEGIN maxi-quality agent-guard", agents)

    def test_switch_preserves_edited_old_instruction_region_as_conflict(self):
        (self.target / "CLAUDE.md").write_text("# Personal instructions\n")
        self.setup_guardian("claude")
        instructions = self.target / "CLAUDE.md"
        instructions.write_text(instructions.read_text().replace("Run the project gate", "Skip the project gate"))
        before = self.snapshot()

        switched, report = self.switch("codex", apply=True)
        self.assertEqual(switched.returncode, 3, report)
        self.assertEqual(report["outcome"], "refused")
        self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
