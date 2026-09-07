"""Exercise installation ownership through commands and real installed hooks."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

BASELINE = Path(__file__).resolve().parents[2]
INSTALL = [sys.executable, str(BASELINE / "scripts/agent-install.py")]
ADOPT = ["bash", str(BASELINE / "scripts/adopt.sh")]


class InstallationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="agent-install-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.home = self.root / "isolated home"
        self.home.mkdir()
        self.runtime = self.home / ".claude/agent-guard"
        self.env = {**os.environ, "HOME": str(self.home), "GIT_CONFIG_NOSYSTEM": "1"}
        self.create_repo("adopter repo")

    def create_repo(self, name: str) -> None:
        self.repo = self.root / name
        self.repo.mkdir()
        self.run_command(["git", "init", "-q"])
        (self.repo / "work.txt").write_text("initial\n")
        self.run_command(["git", "add", "."])
        self.run_command(["git", "-c", "user.name=fixture", "-c",
                          "user.email=fixture@example.invalid", "commit", "-qm", "initial"])

    def run_command(self, command: list[str], payload: dict | None = None,
                    *, expected: int = 0) -> str:
        result = subprocess.run(command, cwd=self.repo, env=self.env,
                                input=json.dumps(payload) if payload is not None else None,
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result.stdout

    def snapshot(self, directory: Path) -> dict[str, bytes]:
        return {str(path.relative_to(directory)): path.read_bytes()
                for path in directory.rglob("*") if path.is_file()}

    def test_installer_owns_all_four_repository_profiles(self) -> None:
        # No shell orchestration: a caller needs only the repository and mode.
        self.run_command([*INSTALL, "shared"])
        for samples, shared in ((False, False), (True, False), (True, True), (False, True)):
            with self.subTest(samples=samples, shared=shared):
                self.create_repo(f"adopter samples={samples} shared={shared}")
                manifests = self.repo / "samples/expected"
                if samples:
                    manifests.mkdir(parents=True, exist_ok=True)
                self.run_command([*INSTALL, "repo", str(self.repo),
                                  *(["--shared"] if shared else [])])
                installed = self.repo / ".claude/agent-guard"
                names = {path.name for path in installed.glob("*.py")}
                wanted = {"shim.py"} if shared else {
                    "guard.py", "record-gate.py", "no-verify-guard.py", "stop-gate.py",
                } | ({"sample-guard.py"} if samples else set())
                self.assertEqual(names, wanted)
                doc = json.loads((self.repo / ".claude/settings.json").read_text())
                self.assertEqual(len(doc["permissions"]["deny"]), 2 if samples else 1)
                text = (self.repo / "CLAUDE.md").read_text()
                self.assertIn("three hooks and two deny rules" if samples
                              else "two hooks and one deny rule", text)
                command = text.split("```bash\n", 1)[1].split("\n```", 1)[0].strip()
                (self.repo / ".claude/agent-guard.json").write_text(
                    json.dumps({"gate_command": "true"}))
                self.run_command(shlex.split(command))
                stop = next(entry["command"] for group in doc["hooks"]["Stop"]
                            for entry in group["hooks"])
                self.assertEqual(self.run_command(
                    shlex.split(stop.replace("${CLAUDE_PROJECT_DIR}", str(self.repo))),
                    {"cwd": str(self.repo), "hook_event_name": "Stop"}), "")

    def test_repository_adoption_never_updates_shared_runtime(self) -> None:
        self.run_command([*ADOPT, str(self.repo), "--agent", "--shared"])
        self.assertFalse(self.runtime.exists(), "repository adoption published shared code")
        self.run_command([*ADOPT, "--install-shared"])
        script = self.runtime / "stop-gate.py"
        script.write_text("# older shared runtime\n")
        foreign = self.runtime / "adopter-owned.py"
        foreign.write_text("# not owned by the baseline\n")
        before = self.snapshot(self.runtime)
        self.run_command([*ADOPT, str(self.repo), "--agent", "--shared", "--force"])
        self.assertEqual(self.snapshot(self.runtime), before)
        self.run_command([*ADOPT, "--install-shared"])
        self.assertEqual(script.read_bytes(),
                         (BASELINE / "scripts/agent-guard/stop-gate.py").read_bytes())
        self.assertEqual(foreign.read_text(), "# not owned by the baseline\n")
        self.assertTrue((self.runtime / "sample-guard.py").is_file())
        self.assertFalse((self.runtime / "selftest.py").exists())

    def test_shared_dry_run_does_not_write(self) -> None:
        for existing in (False, True):
            with self.subTest(existing=existing):
                if existing:
                    self.runtime.mkdir(parents=True)
                    (self.runtime / "stop-gate.py").write_text("# keep during preview\n")
                before = self.snapshot(self.root)
                self.run_command([*ADOPT, "--install-shared", "--dry-run"])
                self.assertEqual(self.snapshot(self.root), before)
                self.assertEqual(self.runtime.exists(), existing)

    def test_ignore_append_preserves_adopter_bytes(self) -> None:
        path = self.repo / ".gitignore"
        original = b"# existing non-UTF-8 comment: \xff\r\nprivate-files/"
        path.write_bytes(original)
        self.run_command([*ADOPT, str(self.repo), "--agent"])
        installed = path.read_bytes()
        self.assertTrue(installed.startswith(original + b"\n\n"))
        self.assertIn(b".claude/agent-guard-ledger.jsonl\n", installed)
        self.run_command([*ADOPT, str(self.repo), "--agent"])
        self.assertEqual(path.read_bytes(), installed)

    def test_undecodable_settings_refuses_before_writing(self) -> None:
        directory = self.repo / ".claude"
        directory.mkdir()
        (directory / "settings.json").write_bytes(b"\xff")
        before = self.snapshot(self.repo)
        self.run_command([*ADOPT, str(self.repo), "--agent"], expected=6)
        self.assertEqual(self.snapshot(self.repo), before)

    def test_undecodable_instructions_preserves_partial_installation(self) -> None:
        path = self.repo / "CLAUDE.md"
        path.write_bytes(b"\xff")
        self.run_command([*ADOPT, str(self.repo), "--agent"], expected=7)
        self.assertEqual(path.read_bytes(), b"\xff")
        self.assertTrue((self.repo / ".claude/settings.json").is_file())
        self.assertTrue((self.repo / ".claude/agent-guard/stop-gate.py").is_file())


if __name__ == "__main__":
    unittest.main()
