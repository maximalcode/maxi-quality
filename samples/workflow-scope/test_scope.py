#!/usr/bin/env python3
"""Observable workflow-scope contract fixtures.

These tests exercise the helper's command boundary and the existing detector
body extracted from quality.yml.  They deliberately keep detector discovery
and scope presence as separate observations.
"""

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
HELPER = ROOT / "scripts" / "workflow_scope.py"
WORKFLOW = ROOT / ".github" / "workflows" / "quality.yml"


def run_helper(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(HELPER), *args],
        cwd=cwd or ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def extract_detector_body() -> str:
    lines = WORKFLOW.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line == "      - id: scan")
    run = next(i for i in range(start, len(lines)) if lines[i] == "        run: |" )
    end = next(
        (i for i in range(run + 1, len(lines)) if lines[i].strip() and not lines[i].startswith("          ")),
        len(lines),
    )
    return textwrap.dedent("\n".join(lines[run + 1 : end]) + "\n")


class WorkflowScopeTests(unittest.TestCase):
    def test_presence_is_independent_from_selection_and_detect_body_stays_compatible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text('{"name":"fixture"}\n')
            (root / "package-lock.json").write_text('{}\n')
            (root / "pyproject.toml").write_text("[project]\nname='fixture'\nversion='0'\n")
            (root / "package.json").chmod(0o644)
            output = root / "detect.out"
            env = {**os.environ, "LANGS": "ts", "GITHUB_OUTPUT": str(output)}
            result = subprocess.run(
                ["bash", "-c", extract_detector_body()],
                cwd=root,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            detector = output.read_text()
            self.assertIn("has_ts=true", detector)
            self.assertIn("has_python=false", detector)

            scope = root / "scope.json"
            init = run_helper(
                "init",
                "--out",
                str(scope),
                "--root",
                str(root),
                "--languages",
                "ts",
                "--workflow",
                "quality",
                "--invocation-id",
                "invocation-a",
                "--run-id",
                "run-a",
                "--run-attempt",
                "1",
                "--commit",
                "fixture",
                "--ref",
                "refs/heads/test",
            )
            self.assertEqual(init.returncode, 0, init.stderr)
            data = json.loads(scope.read_text())
            self.assertEqual(data["presence"]["python"]["state"], "present")
            self.assertEqual(data["languages"]["python"]["state"], "skipped")
            self.assertEqual(data["languages"]["python"]["reason_code"], "deselected")
            self.assertEqual(data["presence"]["dotnet"]["state"], "absent")
            self.assertEqual(data["languages"]["dotnet"]["state"], "not_applicable")
            self.assertEqual(data["languages"]["ts"]["state"], "selected")

    def test_collector_reconciles_legs_without_turning_missing_into_zero_or_never_ran(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "manifest.json"
            fragments = root / "fragments"
            fragments.mkdir()
            result = run_helper(
                "init",
                "--out",
                str(manifest),
                "--root",
                str(root),
                "--languages",
                "auto",
                "--workflow",
                "quality",
                "--invocation-id",
                "invocation-b",
                "--run-id",
                "run-b",
                "--run-attempt",
                "2",
                "--commit",
                "fixture",
                "--ref",
                "refs/heads/test",
                "--expected-job",
                "typescript|typescript|pkg-a",
                "--expected-job",
                "typescript|typescript|pkg-b",
                "--expected-job",
                "layer2|layer2|",
                "--coverage-state",
                "not_applicable",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            fragment = {
                "schema_version": 1,
                "kind": "workflow-scope-fragment",
                "identity": {
                    "producer": "gate",
                    "workflow": "quality",
                    "invocation_id": "invocation-b",
                    "run_id": "run-b",
                    "run_attempt": "2",
                    "logical_job": "typescript",
                    "leg": "pkg-a",
                },
                "state": "run",
                "outcome": "success",
                "reason": "command completed",
            }
            (fragments / "a.json").write_text(json.dumps(fragment))
            collect = run_helper(
                "collect",
                "--manifest",
                str(manifest),
                "--fragments-dir",
                str(fragments),
                "--out",
                str(root / "collected.json"),
            )
            self.assertEqual(collect.returncode, 0, collect.stderr)
            data = json.loads((root / "collected.json").read_text())
            jobs = {job["logical_job"] + ":" + job["leg"]: job for job in data["jobs"]}
            self.assertEqual(jobs["typescript:pkg-a"]["outcome"], "success")
            self.assertEqual(jobs["typescript:pkg-b"]["state"], "unknown")
            self.assertEqual(jobs["typescript:pkg-b"]["reason_code"], "missing_fragment")
            self.assertIsNone(jobs["typescript:pkg-b"]["examined"]["count"])
            self.assertEqual(data["collection"]["status"], "partial")
            self.assertIn("typescript|pkg-b", data["collection"]["missing"])
            self.assertEqual(data["coverage"]["state"], "not_applicable")

    def test_deselected_unsupported_shape_is_observed_without_detector_refusal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text('{"name":"fixture"}\n')
            (root / "package-lock.json").write_text('{}\n')
            (root / "build.gradle").write_text("plugins { id 'java' }\n")
            output = root / "detect.out"
            env = {**os.environ, "LANGS": "ts", "GITHUB_OUTPUT": str(output)}
            result = subprocess.run(
                ["bash", "-c", extract_detector_body()], cwd=root, env=env,
                text=True, capture_output=True, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            scope = root / "scope.json"
            self.assertEqual(run_helper("init", "--out", str(scope), "--root", str(root), "--languages", "ts", "--workflow", "quality", "--invocation-id", "i", "--run-id", "r", "--run-attempt", "1", "--commit", "c", "--ref", "r").returncode, 0)
            data = json.loads(scope.read_text())
            self.assertEqual(data["presence"]["java"]["state"], "present")
            self.assertEqual(data["languages"]["java"]["state"], "skipped")
            self.assertEqual(data["languages"]["java"]["reason_code"], "deselected")

    def test_selected_malformed_shape_keeps_detector_failure_separate_from_presence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text('{"name":"fixture"}\n')
            (root / "yarn.lock").write_text("# unsupported lockfile\n")
            output = root / "detect.out"
            env = {**os.environ, "LANGS": "ts", "GITHUB_OUTPUT": str(output)}
            result = subprocess.run(["bash", "-c", extract_detector_body()], cwd=root, env=env, text=True, capture_output=True, check=False)
            self.assertNotEqual(result.returncode, 0)
            scope = root / "scope.json"
            self.assertEqual(run_helper("init", "--out", str(scope), "--root", str(root), "--languages", "ts", "--workflow", "quality", "--invocation-id", "i", "--run-id", "r", "--run-attempt", "1", "--commit", "c", "--ref", "r", "--expected-job", "detect||", "--expected-job", "layer2||").returncode, 0)
            fragment = root / "detect.json"
            diagnostic = result.stderr + result.stdout
            self.assertEqual(run_helper("fragment", "--out", str(fragment), "--logical-job", "detect", "--invocation-id", "i", "--run-id", "r", "--run-attempt", "1", "--state", "run", "--outcome", "failure", "--reason", "detector refused unsupported lockfile", "--reason-code", "detector_failure", "--diagnostic", diagnostic).returncode, 0)
            fragments = root / "fragments"
            fragments.mkdir()
            fragment.rename(fragments / "detect.json")
            collected = root / "collected.json"
            self.assertEqual(run_helper("collect", "--manifest", str(scope), "--fragments-dir", str(fragments), "--out", str(collected)).returncode, 0)
            data = json.loads(collected.read_text())
            self.assertEqual(data["detection"]["outcome"], "failure")
            self.assertIn("supported lockfile", data["detection"]["diagnostics"][0])
            self.assertEqual(data["languages"]["ts"]["state"], "selected")

    def test_attempt_filter_keeps_old_fragment_out_of_current_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "manifest.json"
            fragments = root / "fragments"
            fragments.mkdir()
            args = [
                "init", "--out", str(manifest), "--root", str(root), "--languages", "none",
                "--workflow", "quality", "--invocation-id", "same", "--run-id", "run-c",
                "--run-attempt", "2", "--commit", "fixture", "--ref", "fixture",
                "--expected-job", "detect|detect|",
            ]
            self.assertEqual(run_helper(*args).returncode, 0)
            old = {
                "schema_version": 1, "kind": "workflow-scope-fragment",
                "identity": {"producer": "gate", "workflow": "quality", "invocation_id": "same", "run_id": "run-c", "run_attempt": "1", "logical_job": "detect", "leg": ""},
                "state": "run", "outcome": "success", "reason": "old attempt",
            }
            (fragments / "old.json").write_text(json.dumps(old))
            self.assertEqual(run_helper("collect", "--manifest", str(manifest), "--fragments-dir", str(fragments), "--out", str(root / "out.json")).returncode, 0)
            data = json.loads((root / "out.json").read_text())
            job = data["jobs"][0]
            self.assertEqual(job["state"], "unknown")
            self.assertEqual(job["reason_code"], "missing_fragment")
            self.assertIn("attempt", " ".join(data["collection"]["issues"]).lower())

    def test_summary_escapes_bounded_lines_and_cancellation_is_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scope = root / "scope.json"
            self.assertEqual(run_helper("init", "--out", str(scope), "--root", str(root), "--languages", "none", "--workflow", "quality", "--invocation-id", "i", "--run-id", "r", "--run-attempt", "1", "--commit", "c", "--ref", "r", "--cancellation", "cancelled").returncode, 0)
            self.assertEqual(run_helper("summary", "--out", str(scope)).returncode, 0)
            data = json.loads(scope.read_text())
            self.assertEqual(data["identity"]["cancellation"], "cancelled")
            self.assertTrue(any("cancelled" in line.lower() for line in data["summary"]["lines"]))

    def test_failed_discovery_is_unknown_instead_of_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scope = Path(tmp) / "scope.json"
            result = run_helper(
                "init", "--out", str(scope), "--root", str(Path(tmp) / "missing"),
                "--languages", "auto", "--workflow", "quality", "--invocation-id", "i",
                "--run-id", "r", "--run-attempt", "1", "--commit", "c", "--ref", "r",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(scope.read_text())
            self.assertTrue(all(item["state"] == "unknown" for item in data["presence"].values()))
            self.assertTrue(all(item["state"] == "unknown" for item in data["languages"].values()))

    def test_workflow_wiring_directly_reaches_every_job_and_is_non_gating(self) -> None:
        workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        jobs = workflow["jobs"]
        collector = jobs["workflow-scope"]
        self.assertEqual(collector["if"], "always()")
        self.assertEqual(
            set(collector["needs"]),
            {"detect", "typescript", "dotnet", "python", "rust", "java", "layer2", "coverage"},
        )
        body = WORKFLOW.read_text(encoding="utf-8")
        self.assertGreaterEqual(body.count("actions/workflow-scope@"), 9)
        self.assertNotIn("actions/workflow-scope@v1", body)
        self.assertIn("mode: collect", body)
        self.assertIn("if: always()", body)

        action = yaml.safe_load((ROOT / "actions" / "workflow-scope" / "action.yml").read_text(encoding="utf-8"))
        for step in action["runs"]["steps"]:
            if step["name"] in {
                "Initialize workflow scope",
                "Upload workflow scope manifest",
                "Write workflow scope fragment",
                "Upload workflow scope fragment",
                "Download workflow scope fragments",
                "Collect and publish workflow scope",
                "Upload whole workflow scope",
            }:
                self.assertTrue(step.get("continue-on-error"), step["name"])


if __name__ == "__main__":
    unittest.main()
