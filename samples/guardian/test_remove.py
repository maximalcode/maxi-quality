"""Public CLI behavior for safely removing a selected-host Guardian integration."""

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
    baseline_instructions = (BASELINE / "CLAUDE.md").read_text()
    begin = baseline_instructions.index("<!-- BEGIN maxi-quality agent-guard")
    end = baseline_instructions.index("<!-- END maxi-quality agent-guard -->")
    region_end = baseline_instructions.index("\n", end) + 1
    region = baseline_instructions[begin:region_end]
    (path / "CLAUDE.md").write_text("# Project instructions\n\nKeep this text.\n\n" + region)
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                    "-c", "core.hooksPath=/dev/null", "commit", "-qm", "fixture"],
                   cwd=path, check=True)
    return path.resolve()


class RemoveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.home = self.base / "home"
        self.home.mkdir()
        self.cache = self.base / "shared-cache"
        self.env = {**os.environ, "HOME": str(self.home),
                    "MAXI_QUALITY_RUNTIME_CACHE": str(self.cache)}
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

    def setup_guardian(self, target=None, host="claude"):
        target = target or self.target
        result = command([sys.executable, str(RUNNER), "setup", str(target),
                          "--source", str(self.source), "--version", "v9.0.0",
                          "--commit", self.commit, "--guardian", host, "--apply"],
                         target, self.env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def lifecycle(self, action="remove", target=None, *args):
        target = target or self.target
        result = command([sys.executable, str(RUNNER), action, str(target),
                          *args, "--json"], target, self.env)
        return result, json.loads(result.stdout)

    def snapshot(self, root):
        return {str(path.relative_to(root)): path.read_bytes()
                for path in root.rglob("*") if path.is_file() and ".git" not in path.parts}

    def test_remove_preview_and_apply_preserve_checks_foreign_settings_and_shared_runtime(self):
        self.setup_guardian()
        run = command([sys.executable, str(RUNNER), "run", str(self.target),
                       "--base", "HEAD", "--json"], self.target, self.env)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        receipt = (self.target / ".claude/agent-guard-receipt.json").read_bytes()
        settings_path = self.target / ".claude/settings.json"
        settings = json.loads(settings_path.read_text())
        settings.setdefault("hooks", {}).setdefault("SessionStart", []).append(
            {"hooks": [{"type": "command", "command": "echo foreign"}]})
        settings.setdefault("permissions", {}).setdefault("deny", []).append("Edit(/private/**)")
        settings_path.write_text(json.dumps(settings, indent=2) + "\n")
        codex_path = self.target / ".codex/hooks.json"
        codex_path.parent.mkdir()
        codex_path.write_text('{"hooks":{"SessionStart":[{"hooks":[{"type":"command","command":"echo other host"}]}]}}\n')
        before_preview = self.snapshot(self.target)
        cache_before = self.snapshot(self.cache)

        preview_proc, preview = self.lifecycle()
        self.assertEqual(preview_proc.returncode, 0, preview)
        self.assertEqual(preview["outcome"], "preview")
        self.assertIn(".claude/settings.json", preview["changes"])
        self.assertIn("CLAUDE.md", preview["changes"])
        self.assertNotIn(".claude/agent-guard.json", preview["changes"])
        self.assertNotIn(".claude/agent-guard-receipt.json", preview["changes"])
        self.assertEqual(self.snapshot(self.target), before_preview)

        applied_proc, applied = self.lifecycle("remove", self.target, "--apply")
        self.assertEqual(applied_proc.returncode, 0, applied)
        self.assertEqual(applied["outcome"], "removed")
        self.assertEqual((self.target / ".claude/agent-guard.json").read_text(),
                         '{"gate_command":"true"}\n')
        self.assertEqual((self.target / ".claude/agent-guard-receipt.json").read_bytes(), receipt)
        remaining_settings = json.loads(settings_path.read_text())
        self.assertIn("foreign", json.dumps(remaining_settings))
        self.assertNotIn("no-verify-guard", json.dumps(remaining_settings))
        self.assertNotIn("stop-gate", json.dumps(remaining_settings))
        self.assertEqual(remaining_settings["permissions"]["deny"], ["Edit(/private/**)"])
        self.assertEqual(codex_path.read_bytes(), before_preview[".codex/hooks.json"])
        instructions_after = (self.target / "CLAUDE.md").read_text()
        self.assertIn("# Project instructions\n\nKeep this text.", instructions_after)
        self.assertNotIn("BEGIN maxi-quality agent-guard", instructions_after)
        self.assertFalse((self.target / ".claude/skills/guardian").exists())
        self.assertTrue((self.target / ".claude/quality-runtime.json").is_file())
        self.assertEqual(self.snapshot(self.cache), cache_before)
        status = command([sys.executable, str(RUNNER), "status", str(self.target), "--json"],
                         self.target, self.env)
        self.assertEqual(json.loads(status.stdout)["installation"]["status"], "not-installed")
        repeated, report = self.lifecycle("remove", self.target, "--apply")
        self.assertEqual(repeated.returncode, 0, report)
        self.assertEqual(report["outcome"], "unchanged")

    def test_codex_remove_keeps_claude_settings_and_removes_only_its_exact_skill_link(self):
        claude_settings = self.target / ".claude/settings.json"
        claude_settings.write_text(
            '{"hooks":{"SessionStart":[{"hooks":[{"type":"command","command":"echo claude"}]}]}}\n')
        claude_before = claude_settings.read_bytes()
        self.setup_guardian(host="codex")
        instructions = self.target / "AGENTS.md"
        instructions.write_text("# Project instructions\n\nKeep Codex text.\n\n" + instructions.read_text())
        unrelated_skill = self.target / ".agents/skills/other"
        unrelated_skill.mkdir()
        codex_config = self.target / ".codex/config.toml"
        codex_config.write_text("[features]\nhooks = true\n")
        codex_config_before = codex_config.read_bytes()

        preview_proc, preview = self.lifecycle("remove", self.target)
        self.assertEqual(preview_proc.returncode, 0, preview)
        self.assertIn(".codex/hooks.json", preview["changes"])
        self.assertIn("AGENTS.md", preview["changes"])
        self.assertIn(".agents/skills/guardian", preview["remove"])
        apply_proc, report = self.lifecycle("remove", self.target, "--apply")
        self.assertEqual(apply_proc.returncode, 0, report)
        self.assertEqual(claude_settings.read_bytes(), claude_before)
        self.assertEqual(codex_config.read_bytes(), codex_config_before)
        self.assertTrue(unrelated_skill.is_dir())
        self.assertFalse((self.target / ".agents/skills/guardian").exists())
        agents_text = instructions.read_text()
        self.assertIn("Keep Codex text.", agents_text)
        self.assertNotIn("BEGIN maxi-quality codex-guard", agents_text)

    def test_remove_refuses_changed_owned_hook_or_instruction_region_without_writes(self):
        self.setup_guardian()
        settings_path = self.target / ".claude/settings.json"
        settings = json.loads(settings_path.read_text())
        settings["hooks"]["Stop"][0]["hooks"][0]["timeout"] = 1
        settings_path.write_text(json.dumps(settings, indent=2) + "\n")
        before = self.snapshot(self.target)
        result, report = self.lifecycle("remove", self.target, "--apply")
        self.assertEqual(result.returncode, 3, report)
        self.assertEqual(report["outcome"], "refused")
        self.assertTrue(report["conflicts"])
        self.assertEqual(self.snapshot(self.target), before)

        # A separate installation proves managed prose is independently owned.
        target = project(self.base / "changed-region")
        self.setup_guardian(target)
        instructions = target / "CLAUDE.md"
        instructions.write_text(instructions.read_text().replace(
            "This repo's quality baseline is enforced", "Changed by user inside owned region"))
        before = self.snapshot(target)
        result, report = self.lifecycle("remove", target, "--apply")
        self.assertEqual(result.returncode, 3, report)
        self.assertTrue(any("instruction" in item.lower() for item in report["conflicts"]))
        self.assertEqual(self.snapshot(target), before)

    def test_remove_paused_installation_and_second_project_shared_cache(self):
        self.setup_guardian()
        second = project(self.base / "second")
        self.setup_guardian(second)
        cache_before = self.snapshot(self.cache)
        pause, paused = self.lifecycle("pause", self.target, "--apply")
        self.assertEqual(pause.returncode, 0, paused)
        remove, report = self.lifecycle("remove", self.target, "--apply")
        self.assertEqual(remove.returncode, 0, report)
        self.assertEqual(report["outcome"], "removed")
        self.assertEqual(self.snapshot(self.cache), cache_before)
        other_status = command([sys.executable, str(RUNNER), "status", str(second), "--json"],
                               second, self.env)
        self.assertEqual(json.loads(other_status.stdout)["installation"]["status"], "ok")
        repeated, report = self.lifecycle("remove", self.target, "--apply")
        self.assertEqual(repeated.returncode, 0, report)
        self.assertEqual(report["outcome"], "unchanged")


if __name__ == "__main__":
    unittest.main()
