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

    def test_actual_pnpm_body_records_the_pinned_package_manager_boundary(self) -> None:
        body = quality_run_body("Install and lint")
        with tempfile.TemporaryDirectory() as tmp:
            root, bin_dir = Path(tmp), Path(tmp) / "bin"
            bin_dir.mkdir()
            (root / "package.json").write_text('{"name":"fixture","packageManager":"pnpm@9.0.0"}\n')
            (root / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n")
            for name in ("corepack", "pnpm"):
                (bin_dir / name).write_text(f"#!/usr/bin/env bash\necho {name}-$* >> \"$TRACE\"\nexit 0\n")
                (bin_dir / name).chmod(0o755)
            result = run_body(body, root, bin_dir, root / "tools.json", TRACE=str(root / "trace"))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((root / "trace").read_text().splitlines(), ["corepack-enable", "pnpm-install --frozen-lockfile", "pnpm-run lint"])
            self.assertEqual([item["name"] for item in json.loads((root / "tools.json").read_text())], ["setup-corepack", "install", "lint"])

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

    def test_actual_pip_body_records_setup_failure_before_ruff_and_mypy(self) -> None:
        body = quality_run_body("Lint and type-check (pip)")
        with tempfile.TemporaryDirectory() as tmp:
            root, bin_dir = Path(tmp), Path(tmp) / "bin"
            bin_dir.mkdir()
            (root / "requirements.txt").write_text("fixture\n")
            (bin_dir / "pip").write_text("#!/usr/bin/env bash\necho pip-$* >> \"$TRACE\"\nexit 31\n")
            (bin_dir / "ruff").write_text("#!/usr/bin/env bash\necho ruff >> \"$TRACE\"\nexit 0\n")
            (bin_dir / "mypy").write_text("#!/usr/bin/env bash\necho mypy >> \"$TRACE\"\nexit 0\n")
            for path in bin_dir.iterdir(): path.chmod(0o755)
            result = run_body(body, root, bin_dir, root / "tools.json", TRACE=str(root / "trace"))
            self.assertEqual(result.returncode, 31, result.stderr)
            self.assertEqual((root / "trace").read_text().splitlines(), ["pip-install -r requirements.txt"])
            records = json.loads((root / "tools.json").read_text())
            self.assertEqual([item["name"] for item in records], ["setup"])

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

    def test_actual_rust_body_does_not_run_deny_after_clippy_failure(self) -> None:
        body = quality_run_body("Format, lint and audit")
        with tempfile.TemporaryDirectory() as tmp:
            root, bin_dir = Path(tmp), Path(tmp) / "bin"
            bin_dir.mkdir()
            (bin_dir / "cargo").write_text("#!/usr/bin/env bash\necho cargo-$* >> \"$TRACE\"\n[[ $1 == fmt ]] && exit 0\n[[ $1 == clippy ]] && exit 43\n[[ $1 == deny ]] && exit 0\nexit 0\n")
            (bin_dir / "cargo").chmod(0o755)
            (bin_dir / "env").write_text("#!/usr/bin/env bash\necho env-$* >> \"$TRACE\"\nexec /usr/bin/env \"$@\"\n")
            (bin_dir / "env").chmod(0o755)
            result = run_body(body, root, bin_dir, root / "tools.json", TRACE=str(root / "trace"))
            self.assertEqual(result.returncode, 43, result.stderr)
            trace = (root / "trace").read_text().splitlines()
            self.assertTrue(any("cargo-clippy" in line for line in trace))
            self.assertFalse(any("cargo-deny" in line for line in trace))
            records = json.loads((root / "tools.json").read_text())
            self.assertEqual([item["name"] for item in records], ["fmt", "clippy"])
            self.assertEqual(records[-1]["exit_code"], 43)

    def test_actual_rust_body_records_structured_clippy_scope(self) -> None:
        body = quality_run_body("Format, lint and audit")
        with tempfile.TemporaryDirectory() as tmp:
            root, bin_dir = Path(tmp), Path(tmp) / "bin"
            bin_dir.mkdir()
            (root / "Cargo.toml").write_text("[workspace]\nmembers=[]\n")
            (bin_dir / "cargo").write_text(
                "#!/usr/bin/env bash\n"
                "if [[ $1 == fmt ]]; then exit 0; fi\n"
                "if [[ $1 == clippy ]]; then\n"
                "  printf '%s\\n' '{\"reason\":\"compiler-artifact\",\"package_id\":\"path+file:///fixture#scope-root@0.1.0\",\"manifest_path\":\"/fixture/Cargo.toml\",\"target\":{\"kind\":[\"lib\"],\"name\":\"scope-root\",\"required-features\":[]},\"features\":[],\"fresh\":false}'\n"
                "  printf '%s\\n' '{\"reason\":\"build-finished\",\"success\":true}'\n"
                "  exit 0\n"
                "fi\n"
                "if [[ $1 == deny ]]; then exit 0; fi\n"
                "exit 99\n"
            )
            (bin_dir / "cargo").chmod(0o755)
            tools = root / "tools.json"
            result = run_body(
                body,
                root,
                bin_dir,
                tools,
                CARGO_BUILD_TARGET="aarch64-apple-darwin",
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            records = json.loads(tools.read_text())
            clippy = next(item for item in records if item["name"] == "clippy")
            self.assertIn("--message-format=json", clippy["command"])
            self.assertEqual(clippy["rust"]["requested"]["target"]["env"], "aarch64-apple-darwin")
            self.assertEqual(clippy["rust"]["observed"]["artifacts"][0]["package_id"], "path+file:///fixture#scope-root@0.1.0")
            self.assertEqual(clippy["rust"]["observed"]["artifacts"][0]["fresh"], False)
            self.assertEqual(clippy["rust"]["observed"]["platform"]["status"], "unknown")
            self.assertEqual(clippy["rust"]["observed"]["build_finished"], {"success": True})

    def test_rust_partial_json_keeps_emitted_artifacts_and_marks_completion_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log = root / "clippy.jsonl"
            log.write_text(
                "\n".join([
                    json.dumps({"reason": "compiler-artifact", "package_id": "pkg#root", "manifest_path": "/fixture/Cargo.toml", "target": {"kind": ["lib"], "name": "root"}, "features": [], "fresh": True}),
                    json.dumps({"reason": "compiler-message", "package_id": "pkg#member", "manifest_path": "/fixture/member/Cargo.toml", "target": {"kind": ["lib"], "name": "member"}, "message": {"level": "error", "message": "type mismatch"}}),
                    json.dumps({"reason": "build-finished", "success": False}),
                ]) + "\n",
                encoding="utf-8",
            )
            tools = root / "tools.json"
            result = subprocess.run(
                [sys.executable, str(HELPER), "tool", "--file", str(tools), "--name", "clippy", "--exit-code", "101", "--rust-evidence-file", str(log), "--argv", "cargo", "clippy", "--workspace", "--all-targets", "--locked", "--message-format=json"],
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            record = json.loads(tools.read_text())[0]
            self.assertEqual(record["exit_code"], 101)
            self.assertEqual(len(record["rust"]["observed"]["artifacts"]), 1)
            self.assertEqual(record["rust"]["observed"]["build_finished"], {"success": False})
            self.assertEqual(record["rust"]["observed"]["compiler_messages"][0]["target"]["name"], "member")

    def test_rust_custom_target_directory_name_is_not_platform_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".cargo").mkdir()
            (root / ".cargo/config.toml").write_text("[build]\ntarget-dir = \"target/aarch64-apple-darwin\"\n", encoding="utf-8")
            log = root / "clippy.jsonl"
            log.write_text(json.dumps({
                "reason": "compiler-artifact", "package_id": "pkg#root", "manifest_path": str(root / "Cargo.toml"),
                "target": {"kind": ["lib"], "name": "root"}, "features": [],
                "filenames": [str(root / "target/aarch64-apple-darwin/debug/deps/libroot.rmeta")], "fresh": False,
            }) + "\n" + json.dumps({"reason": "build-finished", "success": True}) + "\n", encoding="utf-8")
            tools = root / "tools.json"
            result = subprocess.run(
                [sys.executable, str(HELPER), "tool", "--file", str(tools), "--name", "clippy", "--working-directory", str(root), "--rust-evidence-file", str(log), "--argv", "cargo", "clippy", "--workspace", "--all-targets", "--locked", "--message-format=json"],
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            rust = json.loads(tools.read_text())[0]["rust"]
            self.assertEqual(rust["requested"]["platform"]["status"], "unknown")
            self.assertEqual(rust["observed"]["platform"]["status"], "unknown")

    def test_rust_format_failure_handoff_marks_clippy_skipped_without_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tools = root / "tools.json"
            tools.write_text(json.dumps([{
                "name": "fmt", "command": ["cargo", "fmt"], "working_directory": str(root), "state": "run", "outcome": "failure", "reason": "format failed", "reason_code": "command", "exit_code": 1, "diagnostics": ["format diff"], "measurements": {name: {"status": "unknown", "count": None, "unit": "source_path", "method": "boundary", "reason": "not measured"} for name in ("examined", "unparsed", "policy_excluded")},
            }]) + "\n")
            fragment = root / "fragment.json"
            result = subprocess.run(
                [sys.executable, str(HELPER), "fragment", "--out", str(fragment), "--tools-file", str(tools), "--logical-job", "rust", "--language", "rust", "--leg", "fixture", "--expected-tool", "fmt|skipped|unknown|blocked|format step was not reached", "--expected-tool", "clippy|skipped|unknown|blocked|Clippy step was not reached", "--expected-tool", "cargo-deny|skipped|unknown|blocked|audit step was not reached", "--job-outcome", "failure"],
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            records = json.loads(fragment.read_text())["tools"]
            clippy = next(item for item in records if item["name"] == "clippy")
            self.assertEqual((clippy["state"], clippy["reason_code"]), ("skipped", "blocked"))
            self.assertNotIn("rust", clippy)

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
            self.assertEqual([item["name"] for item in records[1:3]], ["error-prone", "nullaway"])
            self.assertTrue(all(item["state"] == "skipped" and item["reason_code"] == "blocked" for item in records[1:3]))

    def test_fragment_off_and_opaque_nested_tools_remain_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            off = root / "off.json"
            result = subprocess.run([sys.executable, str(HELPER), "fragment", "--out", str(off), "--dead-code-mode", "off", "--expected-tool", "knip|skipped|unknown|blocked|unused"], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(off.read_text())["tools"][0]["reason_code"], "disabled")
            opaque = root / "opaque.json"
            result = subprocess.run([sys.executable, str(HELPER), "fragment", "--out", str(opaque), "--expected-tool", "roslyn|unknown|unknown|opaque|nested"], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            nested = json.loads(opaque.read_text())["tools"][0]
            self.assertEqual((nested["state"], nested["reason_code"], nested["reason"]), ("unknown", "opaque", "nested"))

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

    def test_capture_write_fault_does_not_change_original_command_rc(self) -> None:
        body = textwrap.dedent(quality_run_body("Install and lint"))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text('{"name":"fixture"}\n')
            (root / "package-lock.json").write_text('{}\n')
            bin_dir = root / "bin"
            bin_dir.mkdir()
            (bin_dir / "npm").write_text("#!/usr/bin/env bash\n[[ $1 == ci ]] && exit 0\necho original-output\nexit 37\n")
            (bin_dir / "tee").write_text("#!/usr/bin/env bash\ncat\nexit 120\n")
            (bin_dir / "npm").chmod(0o755)
            (bin_dir / "tee").chmod(0o755)
            env = {
                **os.environ,
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
                "GITHUB_WORKSPACE": str(ROOT),
                "RUNNER_TEMP": str(root),
                "SCOPE_HELPER": str(HELPER),
                "SCOPE_TOOLS_FILE": str(root / "tools.json"),
            }
            result = subprocess.run(["bash", "-c", body], cwd=root, env=env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 37, result.stderr)
            self.assertIn("original-output", result.stdout)

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
                [sys.executable, str(HELPER), "fragment", "--out", str(fragment), "--tools-file", str(tools), "--expected-tool", "ruff|skipped|unknown|blocked|Ruff boundary", "--expected-tool", "mypy|skipped|unknown|blocked|prevented by Ruff failure"],
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(fragment.read_text())
            self.assertEqual(data["tools"][0]["diagnostics"], [diagnostic.read_text()])
            self.assertEqual(data["tools"][1]["reason_code"], "blocked")
            unknown_fragment = root / "unknown-fragment.json"
            result = subprocess.run(
                [sys.executable, str(HELPER), "fragment", "--out", str(unknown_fragment), "--expected-tool", "ruff|skipped|unknown|blocked|Ruff boundary", "--expected-tool", "mypy|skipped|unknown|blocked|prevented by Ruff failure", "--job-outcome", "success"],
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            unknown = json.loads(unknown_fragment.read_text())["tools"][1]
            self.assertEqual(unknown["state"], "unknown")
            self.assertEqual(unknown["reason_code"], "missing_tool_record")

    def test_missing_tool_file_reaches_aggregate_as_partial_unknown_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "manifest.json"
            fragments = root / "fragments"
            fragments.mkdir()
            common = ["--producer", "gate", "--workflow", "quality", "--invocation-id", "inv", "--run-id", "run", "--run-attempt", "1"]
            init = subprocess.run([sys.executable, str(HELPER), "init", "--out", str(manifest), "--root", str(root), "--languages", "ts", "--expected-job", "typescript|ts|pkg", *common], text=True, capture_output=True)
            self.assertEqual(init.returncode, 0, init.stderr)
            fragment = fragments / "fragment.json"
            result = subprocess.run([sys.executable, str(HELPER), "fragment", "--out", str(fragment), "--logical-job", "typescript", "--language", "ts", "--leg", "pkg", "--tools-file", str(root / "missing-tools.json"), "--expected-tool", "lint|skipped|unknown|blocked|lint boundary", *common], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            collected = root / "collected.json"
            result = subprocess.run([sys.executable, str(HELPER), "collect", "--manifest", str(manifest), "--fragments-dir", str(fragments), "--out", str(collected), "--invocation-id", "inv", "--run-id", "run", "--run-attempt", "1"], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(collected.read_text())
            job = next(job for job in data["jobs"] if job["logical_job"] == "typescript")
            self.assertEqual(job["tools"][0]["state"], "unknown")
            self.assertEqual(job["tool_collection"]["status"], "partial")
            self.assertEqual(data["collection"]["status"], "partial")
            self.assertTrue(any("tool record file unavailable" in issue for issue in data["collection"]["issues"]))

    def test_malformed_tool_file_is_a_visible_collection_issue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tools = root / "tools.json"
            tools.write_text("not-json\n")
            fragment = root / "fragment.json"
            result = subprocess.run([sys.executable, str(HELPER), "fragment", "--out", str(fragment), "--tools-file", str(tools), "--expected-tool", "lint|skipped|unknown|blocked|lint boundary"], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(fragment.read_text())
            self.assertEqual(data["tool_collection"]["status"], "partial")
            self.assertTrue(any("malformed tool record file" in issue for issue in data["tool_collection"]["issues"]))
            self.assertEqual(data["tools"][0]["reason_code"], "missing_tool_record")

    def test_semantically_invalid_tool_records_become_unknown_at_fragment_collector_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tools = root / "tools.json"
            tools.write_text(json.dumps([
                {"name": "lint", "command": ["ruff", "check", "."], "working_directory": ".", "state": "run", "outcome": "bogus", "reason": "bad outcome", "reason_code": "command", "exit_code": 0, "diagnostics": [], "measurements": {}},
                {"name": "mypy", "command": ["mypy", "."], "working_directory": ".", "state": "run", "outcome": "success", "reason": "command boundary executed", "reason_code": "command", "exit_code": 0, "diagnostics": [], "measurements": {"examined": {"status": "unknown", "count": None, "unit": "source_path", "method": "boundary", "reason": "not measured"}, "unparsed": {"status": "unknown", "count": None, "unit": "source_path", "method": "boundary", "reason": "not measured"}, "policy_excluded": {"status": "unknown", "count": None, "unit": "source_path", "method": "boundary", "reason": "not measured"}}},
                {"name": "format", "command": ["ruff", "format"], "working_directory": ".", "state": [], "outcome": "success", "reason": "bad state", "reason_code": "command", "exit_code": 0, "diagnostics": [], "measurements": {"examined": {"status": "known", "count": None, "unit": "source_path", "method": "boundary", "reason": "invalid nullable count"}, "unparsed": {"status": "unknown", "count": None, "unit": "source_path", "method": "boundary", "reason": "not measured"}, "policy_excluded": {"status": "unknown", "count": None, "unit": "source_path", "method": "boundary", "reason": "not measured"}}},
                {"name": "audit", "command": ["audit"], "working_directory": ".", "state": "run", "outcome": "success", "reason": "bad measurement", "reason_code": "command", "exit_code": 0, "diagnostics": [], "measurements": {"examined": {"status": "unknown", "count": 1, "unit": "source_path", "method": "boundary", "reason": "invalid count"}, "unparsed": {"status": "unknown", "count": None, "unit": "source_path", "method": "boundary", "reason": "not measured"}, "policy_excluded": {"status": "unknown", "count": None, "unit": "source_path", "method": "boundary", "reason": "not measured"}}},
            ]) + "\n")
            fragment = root / "fragment.json"
            result = subprocess.run([sys.executable, str(HELPER), "fragment", "--out", str(fragment), "--tools-file", str(tools), "--producer", "gate", "--workflow", "quality", "--invocation-id", "inv", "--run-id", "run", "--run-attempt", "1", "--logical-job", "python", "--language", "python", "--leg", "pkg", "--expected-tool", "lint|skipped|unknown|blocked|lint boundary", "--expected-tool", "mypy|skipped|unknown|blocked|mypy boundary"], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            fragments = root / "fragments"; fragments.mkdir(); (fragments / "fragment.json").write_text(fragment.read_text())
            manifest = root / "manifest.json"
            result = subprocess.run([sys.executable, str(HELPER), "init", "--out", str(manifest), "--root", str(root), "--languages", "python", "--invocation-id", "inv", "--run-id", "run", "--run-attempt", "1", "--expected-job", "python|python|pkg"], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            collected = root / "collected.json"
            result = subprocess.run([sys.executable, str(HELPER), "collect", "--manifest", str(manifest), "--fragments-dir", str(fragments), "--out", str(collected), "--invocation-id", "inv", "--run-id", "run", "--run-attempt", "1"], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            job = json.loads(collected.read_text())["jobs"][0]
            self.assertEqual(job["tools"][0]["name"], "lint")
            self.assertEqual((job["tools"][0]["state"], job["tools"][0]["outcome"]), ("unknown", "unknown"))
            self.assertEqual(job["tools"][1]["name"], "mypy")
            self.assertEqual(job["tools"][1]["outcome"], "success")
            self.assertEqual([(tool["name"], tool["state"], tool["outcome"]) for tool in job["tools"][2:]], [("format", "unknown", "unknown"), ("audit", "unknown", "unknown")])
            self.assertEqual(job["tool_collection"]["status"], "partial")
            self.assertTrue(any("outcome" in issue for issue in job["tool_collection"]["issues"]))
            self.assertTrue(any("python|pkg" in issue for issue in json.loads(collected.read_text())["collection"]["issues"]))

    def test_helper_fragment_and_collector_work_from_an_adopter_without_scripts(self) -> None:
        scope_action = yaml.safe_load((ROOT / "actions" / "workflow-scope" / "action.yml").read_text(encoding="utf-8"))
        helper_body = next(step["run"] for step in scope_action["runs"]["steps"] if step.get("name") == "Prepare workflow scope helper")
        fragment_body = next(step["run"] for step in scope_action["runs"]["steps"] if step.get("name") == "Write workflow scope fragment")
        with tempfile.TemporaryDirectory() as tmp:
            adopter = Path(tmp) / "adopter"
            runner = Path(tmp) / "runner"
            bin_dir = adopter / "bin"
            bin_dir.mkdir(parents=True); runner.mkdir()
            (adopter / "package.json").write_text('{"name":"fixture"}\n')
            (adopter / "package-lock.json").write_text('{}\n')
            (bin_dir / "npm").write_text("#!/usr/bin/env bash\n[[ $1 == ci ]] && exit 0\nexit 0\n")
            (bin_dir / "npm").chmod(0o755)
            output = runner / "helper-output"
            env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "GITHUB_ACTION_PATH": str(ROOT / "actions" / "workflow-scope"), "RUNNER_TEMP": str(runner), "GITHUB_OUTPUT": str(output), "OUT": str(runner / "helper.py")}
            result = subprocess.run(["bash", "-c", textwrap.dedent(helper_body)], cwd=adopter, env=env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            helper_path = next(line.split("=", 1)[1] for line in output.read_text().splitlines() if line.startswith("helper_path="))
            self.assertTrue(Path(helper_path).is_file())
            tools = runner / "tools.json"
            command = run_body(quality_run_body("Install and lint"), adopter, bin_dir, tools, GITHUB_WORKSPACE=str(adopter), SCOPE_HELPER=helper_path)
            self.assertEqual(command.returncode, 0, command.stderr)
            manifest = runner / "manifest.json"
            init = subprocess.run([sys.executable, str(HELPER), "init", "--out", str(manifest), "--root", str(adopter), "--languages", "ts", "--invocation-id", "synthetic-invocation", "--run-id", "synthetic-run", "--run-attempt", "7", "--expected-job", "typescript|ts|pkg"], text=True, capture_output=True)
            self.assertEqual(init.returncode, 0, init.stderr)
            fragment = runner / "fragment.json"
            frag_env = {**env, "OUT": str(fragment), "PRODUCER": "gate", "WORKFLOW": "quality", "INVOCATION": "synthetic-invocation", "RUN_ID": "synthetic-run", "RUN_ATTEMPT": "7", "LOGICAL_JOB": "typescript", "LANGUAGE": "ts", "LEG": "pkg", "STATE": "run", "OUTCOME": "success", "REASON": "fixture", "REASON_CODE": "fixture", "DIAGNOSTIC": "", "DIAGNOSTIC_FILE": "", "TOOLS_FILE": str(tools), "EXPECTED_TOOLS": "install|skipped|unknown|blocked|not reached\nlint|skipped|unknown|blocked|not reached", "DEAD_CODE_MODE": "auto", "JOB_OUTCOME": "success", "ARTIFACT_PREFIX": "synthetic"}
            result = subprocess.run(["bash", "-c", textwrap.dedent(fragment_body)], cwd=adopter, env=frag_env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            collected = runner / "collected.json"
            result = subprocess.run([sys.executable, str(HELPER), "collect", "--manifest", str(manifest), "--fragments-dir", str(runner), "--out", str(collected), "--invocation-id", "synthetic-invocation", "--run-id", "synthetic-run", "--run-attempt", "7"], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            job = json.loads(collected.read_text())["jobs"][0]
            self.assertEqual([tool["name"] for tool in job["tools"][:2]], ["install", "lint"])

    def test_rust_command_and_fragment_use_copied_helper_without_adopter_scripts(self) -> None:
        scope_action = yaml.safe_load((ROOT / "actions" / "workflow-scope" / "action.yml").read_text(encoding="utf-8"))
        helper_body = next(step["run"] for step in scope_action["runs"]["steps"] if step.get("name") == "Prepare workflow scope helper")
        fragment_body = next(step["run"] for step in scope_action["runs"]["steps"] if step.get("name") == "Write workflow scope fragment")
        with tempfile.TemporaryDirectory() as tmp:
            adopter = Path(tmp) / "adopter"
            runner = Path(tmp) / "runner"
            bin_dir = adopter / "bin"
            bin_dir.mkdir(parents=True)
            runner.mkdir()
            (adopter / "Cargo.toml").write_text("[workspace]\nmembers=[]\n")
            cargo = bin_dir / "cargo"
            cargo.write_text(
                "#!/usr/bin/env bash\n"
                "[[ $1 == fmt ]] && exit 0\n"
                "[[ $1 == clippy ]] && { printf '%s\\n' '{\"reason\":\"compiler-artifact\",\"package_id\":\"pkg#fixture\",\"manifest_path\":\"/adopter/Cargo.toml\",\"target\":{\"kind\":[\"lib\"],\"name\":\"fixture\"},\"features\":[],\"fresh\":false}' '{\"reason\":\"build-finished\",\"success\":true}'; exit 0; }\n"
                "[[ $1 == deny ]] && exit 0\nexit 1\n"
            )
            cargo.chmod(0o755)
            output = runner / "helper-output"
            helper_env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "GITHUB_ACTION_PATH": str(ROOT / "actions" / "workflow-scope"), "RUNNER_TEMP": str(runner), "GITHUB_OUTPUT": str(output), "OUT": str(runner / "helper.py")}
            result = subprocess.run(["bash", "-c", textwrap.dedent(helper_body)], cwd=adopter, env=helper_env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            helper_path = next(line.split("=", 1)[1] for line in output.read_text().splitlines() if line.startswith("helper_path="))
            tools = runner / "tools.json"
            command = run_body(quality_run_body("Format, lint and audit"), adopter, bin_dir, tools, GITHUB_WORKSPACE=str(adopter), SCOPE_HELPER=helper_path, CARGO_BUILD_TARGET="aarch64-apple-darwin")
            self.assertEqual(command.returncode, 0, command.stdout + command.stderr)
            records = json.loads(tools.read_text())
            self.assertIn("rust", next(item for item in records if item["name"] == "clippy"))
            fragment = runner / "fragment.json"
            fragment_env = {
                **helper_env,
                "OUT": str(fragment),
                "PRODUCER": "gate", "WORKFLOW": "quality", "INVOCATION": "inv", "RUN_ID": "run", "RUN_ATTEMPT": "1",
                "LOGICAL_JOB": "rust", "LANGUAGE": "rust", "LEG": "adopter", "STATE": "run", "OUTCOME": "success",
                "REASON": "fixture", "REASON_CODE": "fixture", "DIAGNOSTIC": "", "DIAGNOSTIC_FILE": "", "TOOLS_FILE": str(tools),
                "EXPECTED_TOOLS": "fmt|skipped|unknown|blocked|format step was not reached\nclippy|skipped|unknown|blocked|Clippy step was not reached\ncargo-deny|skipped|unknown|blocked|audit step was not reached",
                "DEAD_CODE_MODE": "auto", "JOB_OUTCOME": "success", "ARTIFACT_PREFIX": "synthetic",
            }
            result = subprocess.run(["bash", "-c", textwrap.dedent(fragment_body)], cwd=adopter, env=fragment_env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            fragment_tools = json.loads(fragment.read_text())["tools"]
            clippy = next(item for item in fragment_tools if item["name"] == "clippy")
            self.assertEqual(clippy["rust"]["observed"]["artifacts"][0]["target"]["name"], "fixture")

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

    def test_actual_deadcode_action_runs_knip_and_records_normal_execution(self) -> None:
        action = yaml.safe_load(DEADCODE.read_text(encoding="utf-8"))
        body = next(step["run"] for step in action["runs"]["steps"] if step.get("name") == "Dead code and unused dependencies")
        with tempfile.TemporaryDirectory() as tmp:
            root, bin_dir = Path(tmp), Path(tmp) / "bin"
            bin_dir.mkdir()
            package = root / "package"
            (package / "node_modules" / ".bin").mkdir(parents=True)
            (package / "package.json").write_text('{"name":"fixture"}\n')
            (package / "knip.json").write_text('{}\n')
            knip = package / "node_modules" / ".bin" / "knip"
            knip.write_text("#!/usr/bin/env bash\n[[ $1 == --version ]] && { echo 6.33.0; exit 0; }\nprintf '{\"issues\":[]}\\n'\n")
            knip.chmod(0o755)
            tools = root / "tools.json"
            env = {**os.environ, "ACTION_PATH": str(ROOT / "actions" / "deadcode"), "TOOL": "knip", "DIR": "package", "MODE": "auto", "GATE_EXPORTS": "false", "CHANGED_ONLY": "", "KNIP_MIN": "6.33.0", "RUNNER_TEMP": str(root), "SCOPE_TOOLS_FILE": str(tools)}
            result = subprocess.run(["bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", body], cwd=root, env=env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            record = json.loads(tools.read_text())[0]
            self.assertEqual((record["name"], record["state"], record["outcome"]), ("knip", "run", "success"))

    def test_deadcode_capture_sink_fault_preserves_knip_verdict_and_marks_collection(self) -> None:
        action = yaml.safe_load(DEADCODE.read_text(encoding="utf-8"))
        body = next(step["run"] for step in action["runs"]["steps"] if step.get("name") == "Dead code and unused dependencies")
        with tempfile.TemporaryDirectory() as tmp:
            root, bin_dir = Path(tmp), Path(tmp) / "bin"
            bin_dir.mkdir()
            package = root / "package"
            (package / "node_modules" / ".bin").mkdir(parents=True)
            (package / "package.json").write_text('{"name":"fixture"}\n')
            (package / "knip.json").write_text('{}\n')
            knip = package / "node_modules" / ".bin" / "knip"
            knip.write_text("#!/usr/bin/env bash\n[[ $1 == --version ]] && { echo 6.33.0; exit 0; }\nprintf '{\"issues\":[]}\\n'\necho capture-tail >&2\nexit 0\n")
            knip.chmod(0o755)
            (bin_dir / "tee").write_text("#!/usr/bin/env bash\ncat\nexit 120\n")
            (bin_dir / "tee").chmod(0o755)
            tools = root / "tools.json"
            env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "ACTION_PATH": str(ROOT / "actions" / "deadcode"), "TOOL": "knip", "DIR": "package", "MODE": "auto", "GATE_EXPORTS": "false", "CHANGED_ONLY": "", "KNIP_MIN": "6.33.0", "RUNNER_TEMP": str(root), "SCOPE_TOOLS_FILE": str(tools)}
            result = subprocess.run(["bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", body], cwd=root, env=env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            record = json.loads(tools.read_text())[0]
            self.assertEqual(record["outcome"], "success")
            self.assertIn("capture sink failed", record["collection"]["issues"][0])

    def test_deptry_no_input_is_one_not_applicable_record(self) -> None:
        action = yaml.safe_load(DEADCODE.read_text(encoding="utf-8"))
        body = next(step["run"] for step in action["runs"]["steps"] if step.get("name") == "Dead code and unused dependencies")
        with tempfile.TemporaryDirectory() as tmp:
            root, bin_dir = Path(tmp), Path(tmp) / "bin"
            bin_dir.mkdir(); (root / "workspace").mkdir()
            (bin_dir / "deptry").write_text("#!/usr/bin/env bash\nexit 0\n"); (bin_dir / "deptry").chmod(0o755)
            tools = root / "tools.json"
            env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "ACTION_PATH": str(ROOT / "actions" / "deadcode"), "TOOL": "deptry", "DIR": "workspace", "MODE": "auto", "GATE_EXPORTS": "false", "CHANGED_ONLY": "", "KNIP_MIN": "6.33.0", "RUNNER_TEMP": str(root), "SCOPE_TOOLS_FILE": str(tools)}
            result = subprocess.run(["bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", body], cwd=root, env=env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            records = json.loads(tools.read_text())
            self.assertEqual(len(records), 1)
            self.assertEqual((records[0]["name"], records[0]["reason_code"]), ("deptry", "not_applicable"))

    def test_deptry_action_continues_each_enumerated_package_and_records_real_cwds(self) -> None:
        action = yaml.safe_load(DEADCODE.read_text(encoding="utf-8"))
        body = next(step["run"] for step in action["runs"]["steps"] if step.get("name") == "Dead code and unused dependencies")
        with tempfile.TemporaryDirectory() as tmp:
            root, bin_dir = Path(tmp), Path(tmp) / "bin"
            bin_dir.mkdir(); workspace = root / "workspace"; member = workspace / "member"
            member.mkdir(parents=True)
            manifest = "[project]\nname='fixture'\nversion='0.1.0'\ndependencies=[]\n"
            (workspace / "pyproject.toml").write_text(manifest); (member / "pyproject.toml").write_text(manifest)
            (bin_dir / "deptry").write_text("#!/usr/bin/env bash\nargs=(\"$@\")\nfor ((i=0; i<${#args[@]}; i++)); do if [[ ${args[$i]} == --json-output ]]; then out=${args[$((i+1))]}; printf '[]\\n' > \"$out\"; break; fi; done\necho \"cwd=$PWD\" >> \"$TRACE\"\nexit 0\n")
            (bin_dir / "deptry").chmod(0o755)
            tools = root / "tools.json"
            env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "TRACE": str(root / "trace"), "ACTION_PATH": str(ROOT / "actions" / "deadcode"), "TOOL": "deptry", "DIR": str(workspace), "MODE": "require", "GATE_EXPORTS": "false", "CHANGED_ONLY": "", "KNIP_MIN": "6.33.0", "RUNNER_TEMP": str(root), "SCOPE_TOOLS_FILE": str(tools)}
            result = subprocess.run(["bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", body], cwd=root, env=env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            records = json.loads(tools.read_text())
            self.assertEqual(len(records), 2)
            self.assertEqual({Path(item["working_directory"]).name for item in records}, {"workspace", "member"})


if __name__ == "__main__":
    unittest.main()
