"""Own isolated Git trees and command execution for installation scenarios."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path

BASELINE = Path(__file__).resolve().parents[2]
ADOPT = ["bash", str(BASELINE / "scripts/adopt.sh")]


class InstallationFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="agent-install-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.home = self.root / "isolated home"
        self.home.mkdir()
        self.runtime = self.home / ".claude/agent-guard"
        # Git's inherited worktree, index, identity and config overrides must
        # not turn a fixture command into an operation on the caller's repo.
        self.env = {key: value for key, value in os.environ.items()
                    if not key.startswith(("GIT_", "MAXI_QUALITY_RUNTIME_")) and key not in
                    {"BASH_ENV", "ENV", "PYTHONPATH", "PYTHONHOME", "PYTHONDONTWRITEBYTECODE"}}
        self.env.update({"HOME": str(self.home), "XDG_CONFIG_HOME": str(self.home / ".config"),
                         "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                         "GIT_TERMINAL_PROMPT": "0", "TMPDIR": str(self.root)})
        self.create_repo("adopter repo")

    def create_repo(self, name: str, *, git: bool = True) -> Path:
        self.repo = self.root / name
        self.repo.mkdir()
        (self.repo / "work.txt").write_text("initial\n")
        if git:
            self.run_command(["git", "init", "-q"])
            self.run_command(["git", "config", "user.name", "fixture"])
            self.run_command(["git", "config", "user.email", "fixture@example.invalid"])
            self.commit()
        return self.repo

    def commit(self) -> None:
        self.run_command(["git", "add", "-A"])
        self.run_command(["git", "commit", "-qm", "fixture"])

    def run_result(self, command: list[str], payload: dict | None = None,
                   *, expected: int | None = 0, cwd: Path | None = None
                   ) -> subprocess.CompletedProcess[str]:
        directory = cwd if cwd is not None else self.repo
        context = f"cwd: {directory}\ncommand: {shlex.join(command)}"
        try:
            result = subprocess.run(command, cwd=directory, env=self.env,
                                    input=json.dumps(payload) if payload is not None else None,
                                    capture_output=True, text=True, timeout=60)
        except subprocess.TimeoutExpired as error:
            self.fail(f"{context}\ntimed out after 60s\n{error.stdout!r}\n{error.stderr!r}")
        except OSError as error:
            self.fail(f"{context}\n{error}")
        if expected is not None:
            self.assertEqual(result.returncode, expected,
                             f"{context}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}")
        return result

    def run_command(self, command: list[str], payload: dict | None = None,
                    *, expected: int = 0, cwd: Path | None = None) -> str:
        return self.run_result(command, payload, expected=expected, cwd=cwd).stdout

    def adopt(self, *flags: str, expected: int = 0) -> str:
        result = self.run_result([*ADOPT, str(self.repo), "--agent", *flags], expected=expected)
        return result.stdout + result.stderr

    def write(self, path: str, content: str) -> Path:
        target = self.repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        return target

    def read(self, path: str) -> str:
        return (self.repo / path).read_text()

    def settings(self) -> dict:
        return json.loads(self.read(".claude/settings.json"))

    def samples(self) -> None:
        self.write("samples/expected/demo.json", "{}\n")

    def snapshot(self, directory: Path) -> dict[str, bytes | str | None]:
        # Include empty directories and dangling links; a refusal must not
        # create either, and following links would miss replacement of a link.
        return {str(path.relative_to(directory)):
                os.readlink(path) if path.is_symlink() else
                path.read_bytes() if path.is_file() else None
                for path in directory.rglob("*")}
