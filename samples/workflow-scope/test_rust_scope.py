#!/usr/bin/env python3
"""Pinned Cargo fixture proving Rust scope evidence from a real Clippy run."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import shutil
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "scripts" / "workflow_scope.py"
SOURCE_FIXTURE = ROOT / "samples" / "workflow-scope" / "rust-fixture"


def copied_fixture(root: Path) -> tuple[Path, str]:
    """Copy the fixture and configure the actual pinned compiler host."""
    fixture = root / "fixture"
    shutil.copytree(SOURCE_FIXTURE, fixture)
    version = subprocess.run(["rustup", "run", "1.97.1", "rustc", "-vV"], text=True, capture_output=True, check=True)
    host = next(line.split(":", 1)[1].strip() for line in version.stdout.splitlines() if line.startswith("host:"))
    cargo_dir = fixture / ".cargo"
    cargo_dir.mkdir(exist_ok=True)
    (cargo_dir / "config.toml").write_text(f"[build]\ntarget = \"{host}\"\n", encoding="utf-8")
    return fixture, host


class PinnedRustScope(unittest.TestCase):
    def test_real_pinned_fixture_crosses_extracted_workflow_and_copied_helper(self) -> None:
        workflow = yaml.safe_load((ROOT / ".github/workflows/quality.yml").read_text(encoding="utf-8"))
        body = next(step["run"] for step in workflow["jobs"]["rust"]["steps"] if step.get("name") == "Format, lint and audit")
        action = yaml.safe_load((ROOT / "actions/workflow-scope/action.yml").read_text(encoding="utf-8"))
        helper_body = next(step["run"] for step in action["runs"]["steps"] if step.get("name") == "Prepare workflow scope helper")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture, host = copied_fixture(root)
            runner = root / "runner"
            runner.mkdir()
            bin_dir = root / "bin"
            bin_dir.mkdir()
            cargo = bin_dir / "cargo"
            cargo.write_text(
                "#!/usr/bin/env bash\n"
                "if [[ $1 == deny ]]; then exit 0; fi\n"
                "exec rustup run 1.97.1 cargo \"$@\"\n"
            )
            cargo.chmod(0o755)
            output = runner / "helper-output"
            helper_env = {
                **os.environ,
                "GITHUB_ACTION_PATH": str(ROOT / "actions/workflow-scope"),
                "RUNNER_TEMP": str(runner),
                "GITHUB_OUTPUT": str(output),
                "OUT": str(runner / "workflow_scope.py"),
            }
            prepared = subprocess.run(["bash", "-c", helper_body], cwd=fixture, env=helper_env, text=True, capture_output=True)
            self.assertEqual(prepared.returncode, 0, prepared.stderr)
            helper = next(line.split("=", 1)[1] for line in output.read_text().splitlines() if line.startswith("helper_path="))
            env = {
                **helper_env,
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
                "GITHUB_WORKSPACE": str(fixture),
                "SCOPE_HELPER": helper,
                "SCOPE_TOOLS_FILE": str(runner / "tools.json"),
                "CARGO_TARGET_DIR": str(root / "target"),
            }
            result = subprocess.run(["bash", "-c", body], cwd=fixture, env=env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            records = json.loads((runner / "tools.json").read_text())
            clippy = next(item for item in records if item["name"] == "clippy")
            self.assertEqual(clippy["exit_code"], 0)
            self.assertTrue(clippy["rust"]["observed"]["artifacts"])
            self.assertEqual(clippy["rust"]["observed"]["build_finished"], {"success": True})
            self.assertEqual(clippy["rust"]["observed"]["platform"]["target"], host)

    def test_real_partial_failure_preserves_artifacts_and_skips_deny_in_extracted_body(self) -> None:
        workflow = yaml.safe_load((ROOT / ".github/workflows/quality.yml").read_text(encoding="utf-8"))
        body = next(step["run"] for step in workflow["jobs"]["rust"]["steps"] if step.get("name") == "Format, lint and audit")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture, _host = copied_fixture(root)
            (fixture / "member/src/lib.rs").write_text(
                "pub fn member_value() -> u32 {\n    let broken: u32 = \"compiler failure\";\n    broken\n}\n",
                encoding="utf-8",
            )
            bin_dir = root / "bin"
            bin_dir.mkdir()
            cargo = bin_dir / "cargo"
            cargo.write_text(
                "#!/usr/bin/env bash\n"
                "echo \"cargo-$*\" >> \"$TRACE\"\n"
                "if [[ $1 == deny ]]; then exit 0; fi\n"
                "exec rustup run 1.97.1 cargo \"$@\"\n"
            )
            cargo.chmod(0o755)
            env = {
                **os.environ,
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
                "TRACE": str(root / "trace"),
                "GITHUB_WORKSPACE": str(fixture),
                "RUNNER_TEMP": str(root),
                "SCOPE_HELPER": str(HELPER),
                "SCOPE_TOOLS_FILE": str(root / "tools.json"),
                "CARGO_TARGET_DIR": str(root / "target"),
            }
            result = subprocess.run(["bash", "-c", body], cwd=fixture, env=env, text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("mismatched types", result.stdout + result.stderr)
            records = json.loads((root / "tools.json").read_text())
            clippy = next(item for item in records if item["name"] == "clippy")
            self.assertNotEqual(clippy["exit_code"], 0)
            self.assertEqual(clippy["rust"]["observed"]["build_finished"], {"success": False})
            self.assertTrue(clippy["rust"]["observed"]["artifacts"])
            self.assertTrue(any(item["target"]["name"] == "scope_member" for item in clippy["rust"]["observed"]["compiler_messages"]))
            self.assertIn("RUSTFLAGS=-Dwarnings", clippy["command"])
            self.assertNotIn("cargo-deny", (root / "trace").read_text(encoding="utf-8"))

    def test_real_pinned_fixture_records_default_features_freshness_and_platform(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target_dir = Path(tmp) / "target"
            fixture, host = copied_fixture(Path(tmp))
            env = {**os.environ, "CARGO_TARGET_DIR": str(target_dir)}
            command = ["rustup", "run", "1.97.1", "cargo", "clippy", "--workspace", "--all-targets", "--locked", "--message-format=json"]
            first = subprocess.run(command, cwd=fixture, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            self.assertEqual(first.returncode, 0, first.stdout)
            first_log = Path(tmp) / "first.jsonl"
            first_log.write_text(first.stdout, encoding="utf-8")
            first_tools = Path(tmp) / "first-tools.json"
            parsed = subprocess.run(
                [sys.executable, str(HELPER), "tool", "--file", str(first_tools), "--name", "clippy", "--working-directory", str(fixture), "--rust-evidence-file", str(first_log), "--argv", "env", "RUSTFLAGS=-Dwarnings", "cargo", "clippy", "--workspace", "--all-targets", "--locked", "--message-format=json"],
                text=True,
                capture_output=True,
                env=env,
            )
            self.assertEqual(parsed.returncode, 0, parsed.stderr)
            first_record = json.loads(first_tools.read_text())[0]["rust"]
            first_artifacts = first_record["observed"]["artifacts"]
            self.assertGreaterEqual(len(first_artifacts), 1)
            self.assertTrue(all(item["package_id"] for item in first_artifacts))
            self.assertTrue(all(item["target"]["name"] and item["target"]["kind"] for item in first_artifacts))
            self.assertTrue(all(item["profile"]["test"] in (True, False) for item in first_artifacts))
            self.assertTrue(all(item["filenames"] for item in first_artifacts))
            self.assertTrue(all(item["fresh"] is False for item in first_artifacts))
            self.assertFalse(any(item["target"]["name"] == "gated-bin" for item in first_artifacts))
            self.assertEqual(first_record["observed"]["build_finished"], {"success": True})
            self.assertEqual(first_record["observed"]["platform"]["target"], host)
            self.assertEqual(first_record["requested"]["platform"]["target"], host)

            rerun = subprocess.run(command, cwd=fixture, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            self.assertEqual(rerun.returncode, 0, rerun.stdout)
            rerun_log = Path(tmp) / "rerun.jsonl"
            rerun_log.write_text(rerun.stdout, encoding="utf-8")
            rerun_tools = Path(tmp) / "rerun-tools.json"
            parsed = subprocess.run(
                [sys.executable, str(HELPER), "tool", "--file", str(rerun_tools), "--name", "clippy", "--working-directory", str(fixture), "--rust-evidence-file", str(rerun_log), "--argv", *command[3:]],
                text=True,
                capture_output=True,
                env=env,
            )
            self.assertEqual(parsed.returncode, 0, parsed.stderr)
            rerun_record = json.loads(rerun_tools.read_text())[0]["rust"]
            self.assertTrue(all(item["fresh"] is True for item in rerun_record["observed"]["artifacts"]))

            feature_command = [*command, "--features", "gated"]
            feature = subprocess.run(feature_command, cwd=fixture, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            self.assertEqual(feature.returncode, 0, feature.stdout)
            feature_log = Path(tmp) / "feature.jsonl"
            feature_log.write_text(feature.stdout, encoding="utf-8")
            feature_tools = Path(tmp) / "feature-tools.json"
            parsed = subprocess.run(
                [sys.executable, str(HELPER), "tool", "--file", str(feature_tools), "--name", "clippy", "--working-directory", str(fixture), "--rust-evidence-file", str(feature_log), "--argv", "env", "RUSTFLAGS=-Dwarnings", "cargo", "clippy", "--workspace", "--all-targets", "--locked", "--message-format=json", "--features", "gated"],
                text=True,
                capture_output=True,
                env=env,
            )
            self.assertEqual(parsed.returncode, 0, parsed.stderr)
            feature_artifacts = json.loads(feature_tools.read_text())[0]["rust"]["observed"]["artifacts"]
            gated = next(item for item in feature_artifacts if item["target"]["name"] == "gated-bin")
            self.assertEqual(gated["features"], ["gated"])


if __name__ == "__main__":
    raise SystemExit(unittest.main())
