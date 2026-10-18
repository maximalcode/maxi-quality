"""Public CLI behavior for pausing and resuming selected-host Guardian enforcement."""

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


class PauseResumeTests(unittest.TestCase):
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

    def lifecycle(self, action, *args):
        result = command([sys.executable, str(RUNNER), action, str(self.target),
                          *args, "--json"], self.target, self.env)
        return result, json.loads(result.stdout)

    def snapshot(self):
        return {str(path.relative_to(self.target)): path.read_bytes()
                for path in self.target.rglob("*") if path.is_file() and ".git" not in path.parts}

    def test_pause_preview_apply_keeps_gate_and_evidence_then_resume_restores_hooks(self):
        self.setup_guardian("claude")
        settings = self.target / ".claude/settings.json"
        value = json.loads(settings.read_text())
        value.setdefault("hooks", {}).setdefault("SessionStart", []).append({
            "hooks": [{"type": "command", "command": "echo foreign"}]
        })
        settings.write_text(json.dumps(value, indent=2) + "\n")
        foreign_before = settings.read_bytes()
        run = command([sys.executable, str(RUNNER), "run", str(self.target),
                       "--base", "HEAD", "--json"], self.target, self.env)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        evidence = json.loads(run.stdout)
        receipt_path = self.target / ".claude/agent-guard-receipt.json"
        receipt_before = receipt_path.read_bytes()
        before = self.snapshot()

        preview_proc, preview = self.lifecycle("pause")
        self.assertEqual(preview_proc.returncode, 0, preview)
        self.assertEqual(preview["outcome"], "preview")
        self.assertEqual(self.snapshot(), before)

        applied_proc, applied = self.lifecycle("pause", "--apply")
        self.assertEqual(applied_proc.returncode, 0, applied)
        self.assertEqual(applied["outcome"], "paused")
        paused_settings = json.loads(settings.read_text())
        self.assertIn("foreign", json.dumps(paused_settings))
        self.assertFalse(any("stop-gate" in json.dumps(entry) or "no-verify-guard" in json.dumps(entry)
                             for entry in paused_settings.get("hooks", {}).values()))
        lock = json.loads((self.target / ".claude/quality-runtime.json").read_text())
        self.assertFalse(lock["guard_enabled"])
        self.assertEqual((self.target / ".claude/agent-guard.json").read_text(),
                         '{"gate_command":"true"}\n')
        self.assertEqual(receipt_path.read_bytes(), receipt_before)
        check = command([sys.executable, str(RUNNER), "run", str(self.target),
                         "--base", "HEAD", "--json"], self.target, self.env)
        self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
        status = command([sys.executable, str(RUNNER), "status", str(self.target), "--json"],
                         self.target, self.env)
        status_report = json.loads(status.stdout)
        self.assertEqual(status_report["installation"]["status"], "paused")
        self.assertEqual(status_report["host"]["observed_enforcement"], "inactive")
        self.assertEqual(status_report["verification"]["freshness"], "current")
        self.assertEqual(status_report["verification"]["outcome"], "succeeded")
        self.assertEqual(evidence["outcome"], "succeeded")

        paused_settings.setdefault("hooks", {}).setdefault("SessionStart", []).append({
            "hooks": [{"type": "command", "command": "echo added while paused"}]
        })
        settings.write_text(json.dumps(paused_settings, indent=2) + "\n")
        foreign_after_pause = json.loads(settings.read_text())

        resume_preview_proc, resume_preview = self.lifecycle("resume")
        self.assertEqual(resume_preview_proc.returncode, 0, resume_preview)
        self.assertEqual(resume_preview["outcome"], "preview")
        resume_proc, resumed = self.lifecycle("resume", "--apply")
        self.assertEqual(resume_proc.returncode, 0, resumed)
        self.assertEqual(resumed["outcome"], "resumed")
        resumed_settings = json.loads(settings.read_text())
        self.assertIn("added while paused", json.dumps(resumed_settings))
        self.assertIn("foreign", json.dumps(resumed_settings))
        self.assertEqual(len(resumed_settings["hooks"]["Stop"]),
                         len(json.loads(foreign_before)["hooks"]["Stop"]))
        self.assertTrue(json.loads((self.target / ".claude/quality-runtime.json").read_text())["guard_enabled"])
        state = json.loads((self.target / ".claude/guardian-state.json").read_text())
        self.assertEqual(state["lifecycle"], "active")
        repeated, unchanged = self.lifecycle("resume", "--apply")
        self.assertEqual(repeated.returncode, 0, unchanged)
        self.assertEqual(unchanged["outcome"], "unchanged")

    def test_pause_refuses_modified_owned_hook_and_preserves_everything(self):
        self.setup_guardian("claude")
        settings = self.target / ".claude/settings.json"
        value = json.loads(settings.read_text())
        value["hooks"]["Stop"][0]["hooks"][0]["timeout"] = 1
        settings.write_text(json.dumps(value, indent=2) + "\n")
        before = self.snapshot()
        result, report = self.lifecycle("pause", "--apply")
        self.assertEqual(result.returncode, 3, report)
        self.assertEqual(report["outcome"], "refused")
        self.assertTrue(report["conflicts"])
        self.assertEqual(self.snapshot(), before)

    def test_codex_pause_keeps_claude_settings_and_unknown_host_trust(self):
        claude = self.target / ".claude/settings.json"
        claude.write_text('{"hooks":{"SessionStart":[{"hooks":[{"type":"command","command":"echo claude"}]}]}}\n')
        claude_before = claude.read_bytes()
        self.setup_guardian("codex")
        result, report = self.lifecycle("pause", "--apply")
        self.assertEqual(result.returncode, 0, report)
        self.assertEqual(report["host"], "codex")
        self.assertEqual(claude.read_bytes(), claude_before)
        resumed, resume_report = self.lifecycle("resume", "--apply")
        self.assertEqual(resumed.returncode, 0, resume_report)
        self.assertEqual(claude.read_bytes(), claude_before)
        status = command([sys.executable, str(RUNNER), "status", str(self.target), "--json"],
                         self.target, self.env)
        self.assertEqual(json.loads(status.stdout)["host"]["trust"], "unverified")

    def test_pause_keeps_shared_lock_enabled_for_an_existing_other_host_guardian(self):
        self.setup_guardian("claude")
        claude = json.loads((self.target / ".claude/settings.json").read_text())
        codex_hooks = json.loads(json.dumps(claude["hooks"]).replace(
            '"${CLAUDE_PROJECT_DIR}"', '"$(git rev-parse --show-toplevel)"'))
        codex_path = self.target / ".codex/hooks.json"
        codex_path.parent.mkdir()
        codex_path.write_text(json.dumps({"hooks": codex_hooks}, indent=2) + "\n")
        before = codex_path.read_bytes()

        paused, report = self.lifecycle("pause", "--apply")
        self.assertEqual(paused.returncode, 0, report)
        lock = json.loads((self.target / ".claude/quality-runtime.json").read_text())
        self.assertTrue(lock["guard_enabled"])
        self.assertEqual(codex_path.read_bytes(), before)

        resumed, resume_report = self.lifecycle("resume", "--apply")
        self.assertEqual(resumed.returncode, 0, resume_report)
        self.assertTrue(json.loads((self.target / ".claude/quality-runtime.json").read_text())[
            "guard_enabled"])
        self.assertEqual(codex_path.read_bytes(), before)

    def test_resume_refuses_changed_pin_and_missing_prerequisite(self):
        self.setup_guardian("claude")
        paused, report = self.lifecycle("pause", "--apply")
        self.assertEqual(paused.returncode, 0, report)
        lock_path = self.target / ".claude/quality-runtime.json"
        original = json.loads(lock_path.read_text())
        changed = dict(original, commit="0" * 40)
        lock_path.write_text(json.dumps(changed) + "\n")
        before = self.snapshot()
        result, refused = self.lifecycle("resume", "--apply")
        self.assertEqual(result.returncode, 3, refused)
        self.assertEqual(self.snapshot(), before)
        lock_path.write_text(json.dumps(original) + "\n")
        shutil.rmtree(self.base / "cache")
        before = self.snapshot()
        result, refused = self.lifecycle("resume", "--apply")
        self.assertEqual(result.returncode, 3, refused)
        self.assertEqual(self.snapshot(), before)

    def test_paused_status_exposes_a_broken_runtime_prerequisite(self):
        for host in ("claude", "codex"):
            with self.subTest(host=host):
                self.target = project(self.base / f"paused-{host}")
                self.setup_guardian(host)
                paused, report = self.lifecycle("pause", "--apply")
                self.assertEqual(paused.returncode, 0, report)
                shutil.rmtree(self.base / "cache")

                status = command([sys.executable, str(RUNNER), "status", str(self.target),
                                  "--json"], self.target, self.env)
                value = json.loads(status.stdout)
                self.assertEqual(status.returncode, 0, status.stderr)
                self.assertEqual(value["installation"]["status"], "broken", value)
                self.assertEqual(value["installation"]["lifecycle"], "broken", value)
                self.assertEqual(value["installation"]["selected_lifecycle"], "paused", value)

    def test_status_and_resume_share_paused_installation_prerequisites(self):
        for host in ("claude", "codex"):
            with self.subTest(host=host):
                self.target = project(self.base / f"preflight-{host}")
                gate = self.target / ".claude/agent-guard.json"
                sentinel = self.home / "status-gate-ran"
                gate_command = f"touch {sentinel}"
                gate.write_text(json.dumps({"gate_command": gate_command}) + "\n")
                self.setup_guardian(host)
                self.assertTrue(sentinel.is_file())
                sentinel.unlink()
                paused, report = self.lifecycle("pause", "--apply")
                self.assertEqual(paused.returncode, 0, report)
                gate_before = gate.read_bytes()
                state_path = self.target / ".claude/guardian-state.json"
                state_before = state_path.read_bytes()

                def assert_broken_without_writes(label):
                    before = self.snapshot()
                    status = command([sys.executable, str(RUNNER), "status", str(self.target),
                                      "--json"], self.target, self.env)
                    value = json.loads(status.stdout)
                    self.assertEqual(status.returncode, 0, f"{label}: {status.stderr}")
                    self.assertEqual(value["installation"]["status"], "broken", label)
                    self.assertEqual(value["installation"]["lifecycle"], "broken", label)
                    self.assertEqual(value["installation"]["selected_lifecycle"], "paused", label)
                    self.assertFalse(sentinel.exists(), label)
                    self.assertEqual(self.snapshot(), before, label)
                    refused, refusal = self.lifecycle("resume", "--apply")
                    self.assertEqual(refused.returncode, 3, f"{label}: {refusal}")
                    self.assertFalse(sentinel.exists(), label)
                    self.assertEqual(self.snapshot(), before, label)

                gate.unlink()
                assert_broken_without_writes("missing gate")
                gate.write_text("not json\n")
                assert_broken_without_writes("invalid gate JSON")
                gate.write_bytes(gate_before)

                state = json.loads(state_before)
                state["owned"].pop("paused_restore")
                state_path.write_text(json.dumps(state))
                assert_broken_without_writes("missing paused restoration data")
                state_path.write_bytes(state_before)

                if host == "codex":
                    config = self.target / ".codex/config.toml"
                    config.parent.mkdir(parents=True, exist_ok=True)
                    config.write_text("[features]\nhooks = false\n")
                    assert_broken_without_writes("Codex hooks disabled")
                    config.unlink()
                else:
                    settings = self.target / ".claude/settings.json"
                    value = json.loads(settings.read_text())
                    value["disableAllHooks"] = True
                    settings.write_text(json.dumps(value) + "\n")
                    assert_broken_without_writes("Claude hooks disabled")

                lock = json.loads((self.target / ".claude/quality-runtime.json").read_text())
                launcher = (self.home / ".local/share/maxi-quality/launchers"
                            / lock["commit"] / "quality-runtime")
                launcher_before = launcher.read_bytes()
                launcher_mode = launcher.stat().st_mode & 0o777
                launcher.write_text("#!/bin/sh\nexit 99\n")
                launcher.chmod(launcher_mode)
                assert_broken_without_writes("replaced executable launcher")
                launcher.write_bytes(launcher_before)
                launcher.chmod(launcher_mode)
if __name__ == "__main__":
    unittest.main()
