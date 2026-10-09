#!/usr/bin/env python3
"""Actual quality command-boundary fixtures for language scope records."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "quality.yml"
HELPER = ROOT / "scripts" / "workflow_scope.py"
DEADCODE = ROOT / "actions" / "deadcode" / "action.yml"


def quality_run_body(step_name: str) -> str:
    document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    for job in document["jobs"].values():
        for step in job.get("steps", []):
            if step.get("name") == step_name:
                return step["run"]
    raise AssertionError(f"quality step not found: {step_name}")


def run_body(body: str, root: Path, bin_dir: Path, tools: Path, **extra: str) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "GITHUB_WORKSPACE": str(ROOT),
        "RUNNER_TEMP": str(root),
        "SCOPE_HELPER": str(HELPER),
        "SCOPE_TOOLS_FILE": str(tools),
        **extra,
    }
    return subprocess.run(["bash", "-c", textwrap.dedent(body)], cwd=root, env=env, text=True, capture_output=True)


class LanguageToolFixtures(unittest.TestCase):
    def test_actual_typescript_body_records_failed_lint_and_preserves_exit(self) -> None:
        body = textwrap.dedent(quality_run_body("Install and lint"))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text('{"name":"fixture"}\n')
            (root / "package-lock.json").write_text('{}\n')
            bin_dir = root / "bin"
            bin_dir.mkdir()
            (bin_dir / "npm").write_text(
                "#!/usr/bin/env bash\n"
                "echo npm-$* >> \"$TRACE\"\n"
                "[[ $1 == ci ]] && exit 0\n"
                "for i in $(seq 1 12000); do echo delayed-diagnostic-$i; done\n"
                "sleep 0.05\n"
                "exit 17\n"
            )
            (bin_dir / "npm").chmod(0o755)
            tools = root / "tools.json"
            trace = root / "trace"
            env = {
                **os.environ,
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
                "TRACE": str(trace),
                "GITHUB_WORKSPACE": str(ROOT),
                "RUNNER_TEMP": str(root),
                "SCOPE_HELPER": str(HELPER),
                "SCOPE_TOOLS_FILE": str(tools),
            }
            result = subprocess.run(["bash", "-c", body], cwd=root, env=env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 17, result.stderr)
            self.assertEqual(trace.read_text().splitlines(), ["npm-ci", "npm-run lint"])
            records = json.loads(tools.read_text())
            self.assertEqual([item["name"] for item in records], ["install", "lint"])
            self.assertEqual(records[-1]["outcome"], "failure")
            self.assertEqual(records[-1]["exit_code"], 17)
            self.assertEqual(records[-1]["command"], ["npm", "run", "lint"])
            self.assertIn("delayed-diagnostic-12000", records[-1]["diagnostics"][0])

    def test_actual_python_body_records_setup_failure_and_blocks_later_tools(self) -> None:
        body = quality_run_body("Lint and type-check (uv)")
        with tempfile.TemporaryDirectory() as tmp:
            root, bin_dir = Path(tmp), Path(tmp) / "bin"
            bin_dir.mkdir()
            (bin_dir / "uv").write_text("#!/usr/bin/env bash\necho uv-$* >> \"$TRACE\"\nexit 31\n")
            (bin_dir / "uv").chmod(0o755)
            trace, tools = root / "trace", root / "tools.json"
            result = run_body(body, root, bin_dir, tools, TRACE=str(trace))
            self.assertEqual(result.returncode, 31, result.stderr)
            self.assertEqual(trace.read_text().splitlines(), ["uv-sync --frozen --all-extras --dev"])
            records = json.loads(tools.read_text())
            self.assertEqual(records[0]["name"], "setup")
            self.assertEqual(records[0]["exit_code"], 31)

    def test_actual_rust_body_does_not_run_clippy_after_format_failure(self) -> None:
        body = quality_run_body("Format, lint and audit")
        with tempfile.TemporaryDirectory() as tmp:
            root, bin_dir = Path(tmp), Path(tmp) / "bin"
            bin_dir.mkdir()
            (bin_dir / "cargo").write_text(
                "#!/usr/bin/env bash\n"
                "echo cargo-$* >> \"$TRACE\"\n"
                "[[ $1 == fmt ]] && exit 41\n"
                "exit 0\n"
            )
            (bin_dir / "cargo").chmod(0o755)
            result = run_body(body, root, bin_dir, root / "tools.json", TRACE=str(root / "trace"))
            self.assertEqual(result.returncode, 41, result.stderr)
            self.assertEqual((root / "trace").read_text().splitlines(), ["cargo-fmt --all --check"])
            records = json.loads((root / "tools.json").read_text())
            self.assertEqual(records[0]["name"], "fmt")
            self.assertEqual(records[0]["exit_code"], 41)

    def test_actual_java_body_keeps_partial_output_and_maven_rc(self) -> None:
        body = quality_run_body("Compile with Error Prone and NullAway")
        with tempfile.TemporaryDirectory() as tmp:
            root, bin_dir = Path(tmp), Path(tmp) / "bin"
            bin_dir.mkdir()
            (bin_dir / "mvn").write_text(
                "#!/usr/bin/env bash\n"
                "echo 'warnings found and -Werror specified'\n"
                "echo 'partial analyzer diagnostic' >&2\n"
                "exit 47\n"
            )
            (bin_dir / "mvn").chmod(0o755)
            result = run_body(body, root, bin_dir, root / "tools.json")
            self.assertEqual(result.returncode, 47)
            records = json.loads((root / "tools.json").read_text())
            self.assertEqual(records[0]["name"], "test-compile")
            self.assertEqual(records[0]["exit_code"], 47)
            self.assertIn("partial analyzer diagnostic", records[0]["diagnostics"][0])

    def test_scope_write_fault_does_not_prevent_actual_command_or_change_rc(self) -> None:
        body = textwrap.dedent(quality_run_body("Install and lint"))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text('{"name":"fixture"}\n')
            (root / "package-lock.json").write_text('{}\n')
            bin_dir = root / "bin"
            bin_dir.mkdir()
            (bin_dir / "npm").write_text(
                "#!/usr/bin/env bash\n"
                "echo invoked >> \"$TRACE\"\n"
                "[[ $1 == ci ]] && exit 0\n"
                "exit 23\n"
            )
            (bin_dir / "npm").chmod(0o755)
            trace = root / "trace"
            env = {
                **os.environ,
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
                "TRACE": str(trace),
                "GITHUB_WORKSPACE": str(ROOT),
                "RUNNER_TEMP": str(root),
                "SCOPE_HELPER": str(HELPER),
                "SCOPE_TOOLS_FILE": "/dev/null/scope.json",
            }
            result = subprocess.run(["bash", "-c", body], cwd=root, env=env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 23, result.stderr)
            self.assertEqual(trace.read_text().splitlines(), ["invoked", "invoked"])

    def test_helper_preparation_fault_does_not_become_command_prerequisite(self) -> None:
        body = textwrap.dedent(quality_run_body("Install and lint"))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text('{"name":"fixture"}\n')
            (root / "package-lock.json").write_text('{}\n')
            bin_dir = root / "bin"
            bin_dir.mkdir()
            (bin_dir / "npm").write_text(
                "#!/usr/bin/env bash\n"
                "echo invoked >> \"$TRACE\"\n"
                "[[ $1 == ci ]] && exit 0\n"
                "exit 29\n"
            )
            (bin_dir / "npm").chmod(0o755)
            trace = root / "trace"
            env = {
                **os.environ,
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
                "TRACE": str(trace),
                "GITHUB_WORKSPACE": str(ROOT),
                "RUNNER_TEMP": str(root),
                "SCOPE_HELPER": "/dev/null/missing-workflow-scope.py",
                "SCOPE_TOOLS_FILE": str(root / "tools.json"),
            }
            result = subprocess.run(["bash", "-c", body], cwd=root, env=env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 29, result.stderr)
            self.assertEqual(trace.read_text().splitlines(), ["invoked", "invoked"])

    def test_fragment_renders_tool_diagnostics_and_blocked_expected_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tools = root / "tools.json"
            diagnostic = root / "lint.log"
            diagnostic.write_text("lint failed before the next boundary\n", encoding="utf-8")
            record = subprocess.run(
                [sys.executable, str(HELPER), "tool", "--file", str(tools), "--name", "ruff", "--state", "run", "--outcome", "failure", "--exit-code", "9", "--diagnostic-file", str(diagnostic), "--argv", "ruff", "check", "."],
                text=True,
                capture_output=True,
            )
            self.assertEqual(record.returncode, 0, record.stderr)
            fragment = root / "fragment.json"
            result = subprocess.run(
                [sys.executable, str(HELPER), "fragment", "--out", str(fragment), "--tools-file", str(tools), "--expected-tool", "mypy|skipped|unknown|blocked|prevented by Ruff failure"],
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(fragment.read_text())
            self.assertEqual(data["tools"][0]["diagnostics"], [diagnostic.read_text()])
            self.assertEqual(data["tools"][1]["reason_code"], "blocked")
            unknown_fragment = root / "unknown-fragment.json"
            result = subprocess.run(
                [sys.executable, str(HELPER), "fragment", "--out", str(unknown_fragment), "--expected-tool", "mypy|skipped|unknown|blocked|prevented by Ruff failure", "--job-outcome", "success"],
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            unknown = json.loads(unknown_fragment.read_text())["tools"][0]
            self.assertEqual(unknown["state"], "unknown")
            self.assertEqual(unknown["reason_code"], "missing_tool_record")

    def test_actual_deadcode_action_records_unavailable_auto_and_require(self) -> None:
        action = yaml.safe_load(DEADCODE.read_text(encoding="utf-8"))
        body = next(step["run"] for step in action["runs"]["steps"] if step.get("name") == "Dead code and unused dependencies")
        for mode, expected_rc, expected_outcome in (("auto", 0, "success"), ("require", 1, "failure")):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                root, tools = Path(tmp), Path(tmp) / "tools.json"
                (root / "package").mkdir()
                env = {
                    **os.environ,
                    "ACTION_PATH": str(ROOT / "actions" / "deadcode"),
                    "TOOL": "knip",
                    "DIR": "package",
                    "MODE": mode,
                    "GATE_EXPORTS": "false",
                    "CHANGED_ONLY": "",
                    "KNIP_MIN": "6.33.0",
                    "RUNNER_TEMP": str(root),
                    "SCOPE_TOOLS_FILE": str(tools),
                }
                result = subprocess.run(["bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", body], cwd=root, env=env, text=True, capture_output=True)
                self.assertEqual(result.returncode, expected_rc, result.stdout + result.stderr)
                record = json.loads(tools.read_text())[0]
                self.assertEqual(record["name"], "knip")
                self.assertEqual(record["state"], "skipped")
                self.assertEqual(record["outcome"], expected_outcome)
                self.assertEqual(record["reason_code"], "unavailable")


if __name__ == "__main__":
    unittest.main()
