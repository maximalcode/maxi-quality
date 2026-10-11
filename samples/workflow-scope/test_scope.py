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


def extract_action_body(name: str) -> str:
    action = yaml.safe_load((ROOT / "actions/workflow-scope/action.yml").read_text(encoding="utf-8"))
    step = next(item for item in action["runs"]["steps"] if item["name"] == name)
    return step["run"]


class WorkflowScopeTests(unittest.TestCase):
    def test_presence_is_independent_from_selection_and_detect_body_stays_compatible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text('{"name":"fixture"}\n')
            (root / "package-lock.json").write_text('{}\n')
            (root / "pyproject.toml").write_text("[project]\nname='fixture'\nversion='0'\n")
            (root / "package.json").chmod(0o644)
            output = root / "detect.out"
            env = {**os.environ, "LANGS": "ts", "GITHUB_OUTPUT": str(output), "RUNNER_TEMP": str(root)}
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

    def test_detector_capture_sink_failure_preserves_detector_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text('{"name":"fixture"}\n')
            (root / "yarn.lock").write_text("# unsupported lockfile\n")
            fake_bin = root / "bin"
            fake_bin.mkdir()
            (fake_bin / "tee").write_text("#!/usr/bin/env bash\nexit 99\n")
            (fake_bin / "tee").chmod(0o755)
            env = {
                **os.environ,
                "PATH": f"{fake_bin}:{os.environ['PATH']}",
                "LANGS": "ts",
                "GITHUB_OUTPUT": str(root / "detect.out"),
                "RUNNER_TEMP": str(root),
            }
            result = subprocess.run(["bash", "-c", extract_detector_body()], cwd=root, env=env, text=True, capture_output=True, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotEqual(result.returncode, -13)
            self.assertIn("supported lockfile", result.stdout + result.stderr)

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

    def test_collect_merges_cancellation_into_valid_manifest_and_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "manifest.json"
            fragments = root / "fragments"
            fragments.mkdir()
            init = run_helper(
                "init", "--out", str(manifest), "--root", str(root), "--languages", "none",
                "--workflow", "quality", "--invocation-id", "collect-cancel",
                "--run-id", "collect-run", "--run-attempt", "2", "--commit", "c", "--ref", "r",
                "--expected-job", "typescript|ts|pkg",
            )
            self.assertEqual(init.returncode, 0, init.stderr)
            fragment = run_helper(
                "fragment", "--out", str(fragments / "typescript.json"),
                "--workflow", "quality", "--invocation-id", "collect-cancel", "--run-id", "collect-run",
                "--run-attempt", "2", "--logical-job", "typescript", "--language", "ts", "--leg", "pkg",
                "--state", "run", "--outcome", "cancelled", "--reason", "cancelled at boundary",
            )
            self.assertEqual(fragment.returncode, 0, fragment.stderr)
            collected = root / "collected.json"
            collect = run_helper(
                "collect", "--manifest", str(manifest), "--fragments-dir", str(fragments), "--out", str(collected),
                "--workflow", "quality", "--invocation-id", "collect-cancel", "--run-id", "collect-run",
                "--run-attempt", "2", "--cancellation", "cancelled",
            )
            self.assertEqual(collect.returncode, 0, collect.stderr)
            data = json.loads(collected.read_text())
            self.assertEqual(data["identity"]["cancellation"], "cancelled")
            self.assertTrue(any("Cancellation metadata: cancelled" in line for line in data["summary"]["lines"]))

    def test_collect_retains_upstream_cancellation_without_overclaiming_missing_matrix_leg(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "manifest.json"
            fragments = root / "fragments"
            fragments.mkdir()
            init = run_helper(
                "init", "--out", str(manifest), "--root", str(root), "--languages", "none",
                "--workflow", "quality", "--invocation-id", "upstream-cancel",
                "--run-id", "upstream-run", "--run-attempt", "1", "--commit", "c", "--ref", "r",
                "--expected-job", "rust|rust|linux", "--expected-job", "rust|rust|macos",
            )
            self.assertEqual(init.returncode, 0, init.stderr)
            fragment = run_helper(
                "fragment", "--out", str(fragments / "linux.json"),
                "--workflow", "quality", "--invocation-id", "upstream-cancel", "--run-id", "upstream-run",
                "--run-attempt", "1", "--logical-job", "rust", "--language", "rust", "--leg", "linux",
                "--state", "run", "--outcome", "success", "--reason", "completed",
            )
            self.assertEqual(fragment.returncode, 0, fragment.stderr)
            collected = root / "collected.json"
            collect = run_helper(
                "collect", "--manifest", str(manifest), "--fragments-dir", str(fragments), "--out", str(collected),
                "--workflow", "quality", "--invocation-id", "upstream-cancel", "--run-id", "upstream-run",
                "--run-attempt", "1", "--job-outcomes", '{"rust":{"result":"cancelled"}}',
            )
            self.assertEqual(collect.returncode, 0, collect.stderr)
            data = json.loads(collected.read_text())
            self.assertEqual(data["identity"]["upstream_cancelled_jobs"], ["rust"])
            self.assertNotIn("cancellation", data["identity"])
            jobs = {(job["logical_job"], job["leg"]): job for job in data["jobs"]}
            self.assertEqual(jobs[("rust", "linux")]["outcome"], "success")
            self.assertEqual(jobs[("rust", "macos")]["state"], "unknown")
            self.assertEqual(jobs[("rust", "macos")]["outcome"], "unknown")
            self.assertEqual(jobs[("rust", "macos")]["reason_code"], "missing_fragment")
            self.assertEqual(data["analysis"]["outcome"], "unknown")
            self.assertEqual(data["collection"]["status"], "partial")
            self.assertTrue(any("Upstream cancelled jobs: rust" in line for line in data["summary"]["lines"]))

    def test_collect_retains_upstream_cancellation_in_missing_manifest_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fragments = root / "fragments"
            fragments.mkdir()
            fragment = run_helper(
                "fragment", "--out", str(fragments / "linux.json"),
                "--workflow", "quality", "--invocation-id", "fallback-cancel", "--run-id", "fallback-run",
                "--run-attempt", "2", "--logical-job", "rust", "--language", "rust", "--leg", "linux",
                "--state", "run", "--outcome", "success", "--reason", "completed",
            )
            self.assertEqual(fragment.returncode, 0, fragment.stderr)
            collected = root / "collected.json"
            collect = run_helper(
                "collect", "--manifest", str(root / "missing-manifest.json"), "--fragments-dir", str(fragments),
                "--out", str(collected), "--root", str(root / "empty-workspace"), "--workflow", "quality",
                "--invocation-id", "fallback-cancel", "--run-id", "fallback-run", "--run-attempt", "2",
                "--expected-job", "rust|rust|linux", "--expected-job", "rust|rust|macos",
                "--job-outcomes", '{"rust":{"result":"cancelled"}}',
            )
            self.assertEqual(collect.returncode, 0, collect.stderr)
            data = json.loads(collected.read_text())
            self.assertEqual(data["identity"]["upstream_cancelled_jobs"], ["rust"])
            jobs = {(job["logical_job"], job["leg"]): job for job in data["jobs"]}
            self.assertEqual(jobs[("rust", "linux")]["outcome"], "success")
            self.assertEqual(jobs[("rust", "macos")]["state"], "unknown")
            self.assertEqual(jobs[("rust", "macos")]["outcome"], "unknown")
            self.assertEqual(data["analysis"]["outcome"], "unknown")
            self.assertEqual(data["collection"]["status"], "partial")

    def test_collect_does_not_invent_upstream_cancellation_for_absent_malformed_or_success_needs(self) -> None:
        for needs in (None, "not-json", "[]", '{"rust":{"result":"success"}}'):
            with self.subTest(needs=needs), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                manifest = root / "manifest.json"
                fragments = root / "fragments"
                fragments.mkdir()
                init = run_helper(
                    "init", "--out", str(manifest), "--root", str(root), "--languages", "none",
                    "--workflow", "quality", "--invocation-id", "needs-control", "--run-id", "needs-run",
                    "--run-attempt", "1", "--commit", "c", "--ref", "r",
                    "--expected-job", "rust|rust|linux",
                )
                self.assertEqual(init.returncode, 0, init.stderr)
                fragment = run_helper(
                    "fragment", "--out", str(fragments / "linux.json"),
                    "--workflow", "quality", "--invocation-id", "needs-control", "--run-id", "needs-run",
                    "--run-attempt", "1", "--logical-job", "rust", "--language", "rust", "--leg", "linux",
                    "--state", "run", "--outcome", "success", "--reason", "completed",
                )
                self.assertEqual(fragment.returncode, 0, fragment.stderr)
                collected = root / "collected.json"
                args = [
                    "collect", "--manifest", str(manifest), "--fragments-dir", str(fragments), "--out", str(collected),
                    "--workflow", "quality", "--invocation-id", "needs-control", "--run-id", "needs-run",
                    "--run-attempt", "1",
                ]
                if needs is not None:
                    args.extend(("--job-outcomes", needs))
                collect = run_helper(*args)
                self.assertEqual(collect.returncode, 0, collect.stderr)
                data = json.loads(collected.read_text())
                self.assertNotIn("upstream_cancelled_jobs", data["identity"])
                self.assertEqual(data["jobs"][0]["outcome"], "success")
                self.assertEqual(data["analysis"]["outcome"], "success")
                self.assertEqual(data["collection"]["status"], "complete")

    def test_deselected_unsupported_shape_is_observed_without_detector_refusal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text('{"name":"fixture"}\n')
            (root / "package-lock.json").write_text('{}\n')
            (root / "build.gradle").write_text("plugins { id 'java' }\n")
            output = root / "detect.out"
            env = {**os.environ, "LANGS": "ts", "GITHUB_OUTPUT": str(output), "RUNNER_TEMP": str(root)}
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
            env = {**os.environ, "LANGS": "ts", "GITHUB_OUTPUT": str(output), "RUNNER_TEMP": str(root)}
            result = subprocess.run(["bash", "-c", extract_detector_body()], cwd=root, env=env, text=True, capture_output=True, check=False)
            self.assertNotEqual(result.returncode, 0)
            detector_log = root / "maxi-quality-detect.log"
            self.assertTrue(detector_log.exists())
            self.assertIn("supported lockfile", detector_log.read_text())
            quality_body = WORKFLOW.read_text(encoding="utf-8")
            self.assertIn('exec > >(tee "${RUNNER_TEMP:-/tmp}/maxi-quality-detect.log" ||', quality_body)
            self.assertIn("diagnostic-file: ${{ runner.temp }}/maxi-quality-detect.log", quality_body)
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

    def test_action_diagnostic_file_preserves_terminal_newline_and_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            diagnostic = root / "diagnostic.log"
            diagnostic.write_text("failure [details](https://example.invalid)|\n", encoding="utf-8")
            env = {
                **os.environ,
                "OUT": str(root / "fragment.json"), "PRODUCER": "gate", "WORKFLOW": "quality",
                "INVOCATION": "i", "RUN_ID": "r", "RUN_ATTEMPT": "1", "LOGICAL_JOB": "detect",
                "LANGUAGE": "", "LEG": "", "STATE": "run", "OUTCOME": "failure", "REASON": "detector",
                "REASON_CODE": "detector", "DIAGNOSTIC": "", "DIAGNOSTIC_FILE": str(diagnostic),
                "ARTIFACT_PREFIX": "safe", "GITHUB_ACTION_PATH": str(ROOT / "actions/workflow-scope"),
                "GITHUB_OUTPUT": str(root / "output"),
            }
            result = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", extract_action_body("Write workflow scope fragment")], env=env, text=True, capture_output=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            fragment = json.loads((root / "fragment.json").read_text())
            self.assertEqual(fragment["diagnostics"][0], "failure [details](https://example.invalid)|\n")

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

    def test_invocation_filter_keeps_same_run_foreign_fragments_out(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "manifest.json"
            fragments = root / "fragments"
            fragments.mkdir()
            self.assertEqual(run_helper(
                "init", "--out", str(manifest), "--root", str(root), "--languages", "none",
                "--workflow", "quality", "--invocation-id", "current", "--run-id", "same-run",
                "--run-attempt", "3", "--commit", "c", "--ref", "r",
                "--expected-job", "typescript|ts|pkg",
            ).returncode, 0)
            for name, invocation, outcome in (("current", "current", "success"), ("foreign", "other", "failure")):
                self.assertEqual(run_helper(
                    "fragment", "--out", str(fragments / f"{name}.json"), "--logical-job", "typescript",
                    "--language", "ts", "--leg", "pkg", "--invocation-id", invocation,
                    "--run-id", "same-run", "--run-attempt", "3", "--state", "run", "--outcome", outcome,
                    "--reason", name,
                ).returncode, 0)
            out = root / "out.json"
            self.assertEqual(run_helper("collect", "--manifest", str(manifest), "--fragments-dir", str(fragments), "--out", str(out)).returncode, 0)
            data = json.loads(out.read_text())
            self.assertEqual(data["collection"]["received"], 1)
            self.assertEqual(data["jobs"][0]["outcome"], "success")
            self.assertTrue(any("invocation" in issue for issue in data["collection"]["issues"]))

    def test_needs_outcome_proves_dependency_skip_but_missing_record_stays_unknown_otherwise(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "manifest.json"
            fragments = root / "fragments"
            fragments.mkdir()
            self.assertEqual(run_helper(
                "init", "--out", str(manifest), "--root", str(root), "--languages", "none",
                "--workflow", "quality", "--invocation-id", "i", "--run-id", "r", "--run-attempt", "1",
                "--commit", "c", "--ref", "r", "--expected-job", "typescript|ts|pkg",
            ).returncode, 0)
            out = root / "out.json"
            self.assertEqual(run_helper(
                "collect", "--manifest", str(manifest), "--fragments-dir", str(fragments), "--out", str(out),
                "--job-outcomes", '{"typescript":{"result":"skipped"}}',
            ).returncode, 0)
            skipped = json.loads(out.read_text())["jobs"][0]
            self.assertEqual(skipped["state"], "skipped")
            self.assertEqual(skipped["reason_code"], "dependency_skipped")

    def test_complete_ts_only_run_ignores_known_napplicable_rows_and_keeps_layer2(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text('{}\n')
            (root / "package-lock.json").write_text('{}\n')
            (root / "pyproject.toml").write_text("[project]\nname='deselected'\nversion='0'\n")
            manifest = root / "manifest.json"
            expected = ["detect||", "typescript|ts|packages/a", "layer2||"]
            self.assertEqual(run_helper(
                "init", "--out", str(manifest), "--root", str(root), "--languages", "ts", "--workflow", "quality",
                "--invocation-id", "i", "--run-id", "r", "--run-attempt", "1", "--commit", "c", "--ref", "r",
                "--coverage-state", "not_applicable", *sum((["--expected-job", item] for item in expected), []),
            ).returncode, 0)
            fragments = root / "fragments"
            fragments.mkdir()
            for index, (logical, language, leg) in enumerate((("detect", "", ""), ("typescript", "ts", "packages/a"), ("layer2", "", ""))):
                self.assertEqual(run_helper(
                    "fragment", "--out", str(fragments / f"{index}.json"), "--logical-job", logical,
                    "--language", language, "--leg", leg, "--invocation-id", "i", "--run-id", "r",
                    "--run-attempt", "1", "--state", "run", "--outcome", "success", "--reason", "ok",
                ).returncode, 0)
            layer2 = root / "layer2.json"
            self.assertEqual(subprocess.run([
                sys.executable, str(ROOT / "scripts/layer2_scope.py"), "init", "--out", str(layer2),
                "--producer", "gate", "--workflow", "quality", "--invocation-id", "l2", "--run-id", "r",
                "--run-attempt", "1", "--job", "layer2", "--commit", "c", "--ref", "r", "--mode", "full",
            ], capture_output=True, text=True).returncode, 0)
            self.assertEqual(subprocess.run([
                sys.executable, str(ROOT / "scripts/layer2_scope.py"), "finalize", "--out", str(layer2),
                "--analysis-outcome", "success", "--analysis-exit-code", "0", "--collection-status", "complete",
            ], capture_output=True, text=True).returncode, 0)
            out = root / "out.json"
            self.assertEqual(run_helper(
                "collect", "--manifest", str(manifest), "--fragments-dir", str(fragments), "--out", str(out),
                "--layer2-dir", str(root), "--layer2-invocation-id", "l2",
            ).returncode, 0)
            data = json.loads(out.read_text())
            self.assertEqual(data["collection"]["status"], "complete")
            self.assertEqual(data["analysis"]["outcome"], "success")
            self.assertEqual(data["coverage"]["state"], "not_applicable")
            self.assertEqual(data["languages"]["python"]["state"], "skipped")
            self.assertEqual(len(data["layer2"]), 1)

    def test_layer2_collection_degradation_is_propagated_and_siblings_survive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "manifest.json"
            fragments = root / "fragments"
            layer2 = root / "layer2"
            fragments.mkdir()
            layer2.mkdir()
            self.assertEqual(run_helper(
                "init", "--out", str(manifest), "--root", str(root), "--languages", "none",
                "--workflow", "quality", "--invocation-id", "layer2-collect", "--run-id", "run",
                "--run-attempt", "1", "--commit", "c", "--ref", "r", "--expected-job", "layer2||",
            ).returncode, 0)
            self.assertEqual(run_helper(
                "fragment", "--out", str(fragments / "layer2.json"), "--logical-job", "layer2",
                "--invocation-id", "layer2-collect", "--run-id", "run", "--run-attempt", "1",
                "--state", "run", "--outcome", "success", "--reason", "scope collected",
            ).returncode, 0)
            producer = layer2 / "valid.json"
            self.assertEqual(subprocess.run([
                sys.executable, str(ROOT / "scripts/layer2_scope.py"), "init", "--out", str(producer),
                "--producer", "gate", "--workflow", "quality", "--invocation-id", "layer2-producer",
                "--run-id", "run", "--run-attempt", "1", "--job", "layer2", "--commit", "c",
                "--ref", "r", "--mode", "full",
            ], capture_output=True, text=True).returncode, 0)
            valid = json.loads(producer.read_text())
            valid["analysis"] = {
                "outcome": "success",
                "exit_code": 0,
                "findings": 0,
                "diagnostics": [{"stream": "stderr", "source": "semgrep", "text": "diagnostic"}],
            }
            valid["tools"]["semgrep"]["diagnostics"] = [
                {"stream": "stderr", "source": "semgrep", "text": "tool diagnostic"},
            ]
            valid["tools"]["semgrep"]["effective"] = {"version": "fixture"}
            valid["tools"]["semgrep"]["native"] = {"result": "fixture"}
            valid["collection"] = {"status": "partial", "issues": ["producer capture unavailable"], "finalized_at": "fixture"}
            producer.write_text(json.dumps(valid))
            malformed = dict(valid)
            malformed["collection"] = {"status": "complete", "issues": ["existing producer issue", None]}
            malformed_tool = dict(valid["tools"]["semgrep"])
            malformed_tool["measurements"] = dict(malformed_tool["measurements"])
            malformed_tool["measurements"]["examined"] = {
                **malformed_tool["measurements"]["examined"], "status": "known", "count": None,
            }
            malformed_generic = dict(valid["tools"]["semgrep"])
            malformed_generic["state"] = "bogus"
            malformed["tools"] = {"broken": malformed_tool, "bad-state": malformed_generic}
            (layer2 / "malformed.json").write_text(json.dumps(malformed))

            out = root / "collected.json"
            result = run_helper(
                "collect", "--manifest", str(manifest), "--fragments-dir", str(fragments), "--out", str(out),
                "--layer2-dir", str(layer2), "--layer2-invocation-id", "layer2-producer",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(out.read_text())
            self.assertEqual(len(data["layer2"]), 2)
            self.assertEqual(data["layer2"][0]["analysis"]["outcome"], "success")
            valid_record = next(record for record in data["layer2"] if record["collection"]["issues"] == ["producer capture unavailable"])
            self.assertEqual(valid_record["analysis"]["diagnostics"][0]["text"], "diagnostic")
            self.assertEqual(valid_record["tools"]["semgrep"]["diagnostics"][0]["text"], "tool diagnostic")
            self.assertEqual(valid_record["tools"]["semgrep"]["effective"]["version"], "fixture")
            self.assertEqual(valid_record["tools"]["semgrep"]["native"]["result"], "fixture")
            malformed_record = next(record for record in data["layer2"] if "broken" in record["tools"])
            self.assertEqual(malformed_record["tools"]["broken"]["diagnostics"][0]["text"], "tool diagnostic")
            self.assertEqual(malformed_record["tools"]["broken"]["measurements"]["examined"]["status"], "unknown")
            self.assertEqual(malformed_record["tools"]["bad-state"]["diagnostics"][0]["text"], "tool diagnostic")
            self.assertEqual(malformed_record["tools"]["bad-state"]["effective"]["version"], "fixture")
            self.assertEqual(malformed_record["tools"]["bad-state"]["native"]["result"], "fixture")
            self.assertEqual(data["collection"]["status"], "partial")
            issues = " ".join(data["collection"]["issues"])
            self.assertIn("producer capture unavailable", issues)
            self.assertIn("existing producer issue", issues)
            self.assertIn("invalid measurement", issues)
            self.assertTrue(any("producer capture unavailable" in line for line in data["summary"]["lines"]))

    def test_layer2_missing_required_tools_degrades_collection(self) -> None:
        for remaining in ({}, {"semgrep": "keep"}):
            with self.subTest(remaining=remaining):
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    manifest = root / "manifest.json"
                    fragments = root / "fragments"
                    fragments.mkdir()
                    self.assertEqual(run_helper(
                        "init", "--out", str(manifest), "--root", str(root), "--languages", "none",
                        "--workflow", "quality", "--invocation-id", "missing-tools", "--run-id", "run",
                        "--run-attempt", "1", "--commit", "c", "--ref", "r", "--expected-job", "layer2||",
                    ).returncode, 0)
                    self.assertEqual(run_helper(
                        "fragment", "--out", str(fragments / "layer2.json"), "--logical-job", "layer2",
                        "--invocation-id", "missing-tools", "--run-id", "run", "--run-attempt", "1",
                        "--state", "run", "--outcome", "success", "--reason", "scope collected",
                    ).returncode, 0)
                    producer = root / "layer2.json"
                    self.assertEqual(subprocess.run([
                        sys.executable, str(ROOT / "scripts/layer2_scope.py"), "init", "--out", str(producer),
                        "--producer", "gate", "--workflow", "quality", "--invocation-id", "layer2-producer",
                        "--run-id", "run", "--run-attempt", "1", "--job", "layer2", "--commit", "c",
                        "--ref", "r", "--mode", "full",
                    ], capture_output=True, text=True).returncode, 0)
                    self.assertEqual(subprocess.run([
                        sys.executable, str(ROOT / "scripts/layer2_scope.py"), "finalize", "--out", str(producer),
                        "--analysis-outcome", "success", "--analysis-exit-code", "0", "--collection-status", "complete",
                    ], capture_output=True, text=True).returncode, 0)
                    value = json.loads(producer.read_text())
                    if remaining:
                        value["tools"] = {name: value["tools"][name] for name in remaining}
                    else:
                        value["tools"] = {}
                    producer.write_text(json.dumps(value))
                    out = root / "collected.json"
                    result = run_helper(
                        "collect", "--manifest", str(manifest), "--fragments-dir", str(fragments), "--out", str(out),
                        "--layer2-dir", str(root), "--layer2-invocation-id", "layer2-producer",
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    data = json.loads(out.read_text())
                    self.assertEqual(data["collection"]["status"], "partial")
                    issues = " ".join(data["collection"]["issues"])
                    self.assertIn("missing required Layer 2 tool record", issues)
                    if remaining:
                        self.assertIn("gitleaks", issues)
                    else:
                        self.assertIn("semgrep", issues)

    def test_layer2_native_measurement_fault_preserves_tool_execution(self) -> None:
        for native_count, expected_collection in ((-1, "partial"), (2, "complete")):
            with self.subTest(native_count=native_count):
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    manifest = root / "manifest.json"
                    fragments = root / "fragments"
                    fragments.mkdir()
                    self.assertEqual(run_helper(
                        "init", "--out", str(manifest), "--root", str(root), "--languages", "none",
                        "--workflow", "quality", "--invocation-id", "execution-preservation", "--run-id", "run",
                        "--run-attempt", "1", "--commit", "c", "--ref", "r", "--expected-job", "layer2||",
                    ).returncode, 0)
                    self.assertEqual(run_helper(
                        "fragment", "--out", str(fragments / "layer2.json"), "--logical-job", "layer2",
                        "--invocation-id", "execution-preservation", "--run-id", "run", "--run-attempt", "1",
                        "--state", "run", "--outcome", "success", "--reason", "scope collected",
                    ).returncode, 0)
                    producer = root / "layer2.json"
                    self.assertEqual(subprocess.run([
                        sys.executable, str(ROOT / "scripts/layer2_scope.py"), "init", "--out", str(producer),
                        "--producer", "gate", "--workflow", "quality", "--invocation-id", "layer2-producer",
                        "--run-id", "run", "--run-attempt", "1", "--job", "layer2", "--commit", "c",
                        "--ref", "r", "--mode", "full",
                    ], capture_output=True, text=True).returncode, 0)
                    self.assertEqual(subprocess.run([
                        sys.executable, str(ROOT / "scripts/layer2_scope.py"), "finalize", "--out", str(producer),
                        "--analysis-outcome", "success", "--analysis-exit-code", "0", "--collection-status", "complete",
                    ], capture_output=True, text=True).returncode, 0)
                    value = json.loads(producer.read_text())
                    semgrep = value["tools"]["semgrep"]
                    semgrep.update({"state": "run", "outcome": "success", "exit_code": 0,
                                    "reason": "scanner completed", "reason_code": "completed"})
                    semgrep["diagnostics"] = [{"stream": "stderr", "source": "semgrep", "text": "scanner diagnostic"}]
                    semgrep["measurements"]["examined"] = {
                        **semgrep["measurements"]["examined"], "status": "known", "count": 4,
                    }
                    semgrep["native"]["component_count"] = {
                        "status": "known", "count": native_count, "unit": "dependency_component",
                        "method": "fixture", "reason": "fixture native count",
                    }
                    producer.write_text(json.dumps(value))
                    out = root / "collected.json"
                    result = run_helper(
                        "collect", "--manifest", str(manifest), "--fragments-dir", str(fragments), "--out", str(out),
                        "--layer2-dir", str(root), "--layer2-invocation-id", "layer2-producer",
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    data = json.loads(out.read_text())
                    record = data["layer2"][0]["tools"]["semgrep"]
                    self.assertEqual(data["collection"]["status"], expected_collection)
                    self.assertEqual(record["state"], "run")
                    self.assertEqual(record["outcome"], "success")
                    self.assertEqual(record["exit_code"], 0)
                    self.assertEqual(record["reason"], "scanner completed")
                    self.assertEqual(record["diagnostics"][0]["text"], "scanner diagnostic")
                    self.assertEqual(record["measurements"]["examined"]["count"], 4)
                    if native_count < 0:
                        self.assertEqual(record["native"]["component_count"]["status"], "unknown")
                        self.assertIsNone(record["native"]["component_count"]["count"])
                    else:
                        self.assertEqual(record["native"]["component_count"]["count"], native_count)

    def test_presence_uses_language_boundaries_and_detector_selection_verbatim(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "target" / "generated"
            target.mkdir(parents=True)
            (target / "package.json").write_text('{}\n')
            (target / "package-lock.json").write_text('{}\n')
            (root / "pyproject.toml").write_text("[project]\nname='fixture'\nversion='0'\n")
            scope = root / "scope.json"
            self.assertEqual(run_helper(
                "init", "--out", str(scope), "--root", str(root), "--languages", "ts, python",
                "--workflow", "quality", "--invocation-id", "i", "--run-id", "r", "--run-attempt", "1",
                "--commit", "c", "--ref", "r",
            ).returncode, 0)
            data = json.loads(scope.read_text())
            self.assertEqual(data["presence"]["ts"]["state"], "present")
            self.assertEqual(data["languages"]["ts"]["state"], "selected")
            self.assertEqual(data["presence"]["python"]["state"], "present")
            self.assertEqual(data["languages"]["python"]["state"], "skipped")

    def test_malformed_fragment_is_a_visible_collection_issue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "manifest.json"
            fragments = root / "fragments"
            fragments.mkdir()
            self.assertEqual(run_helper(
                "init", "--out", str(manifest), "--root", str(root), "--languages", "none",
                "--workflow", "quality", "--invocation-id", "i", "--run-id", "r", "--run-attempt", "1",
                "--commit", "c", "--ref", "r", "--expected-job", "detect| |",
            ).returncode, 0)
            (fragments / "wrong-root.json").write_text("[]\n")
            (fragments / "bad-outcome.json").write_text(json.dumps({
                "schema_version": 1, "kind": "workflow-scope-fragment",
                "identity": {"producer": "gate", "workflow": "quality", "invocation_id": "local", "run_id": "local", "run_attempt": "1", "logical_job": "detect", "leg": ""},
                "state": "run", "outcome": "banana",
            }))
            out = root / "out.json"
            result = run_helper("collect", "--manifest", str(manifest), "--fragments-dir", str(fragments), "--out", str(out))
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(out.read_text())
            self.assertEqual(data["collection"]["status"], "partial")
            self.assertTrue(any("unsupported workflow scope contract" in issue for issue in data["collection"]["issues"]))
            self.assertTrue(any("outcome is invalid" in issue for issue in data["collection"]["issues"]))

    def test_malformed_nested_fragment_data_keeps_valid_sibling(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "manifest.json"
            fragments = root / "fragments"
            fragments.mkdir()
            self.assertEqual(run_helper(
                "init", "--out", str(manifest), "--root", str(root), "--languages", "none",
                "--workflow", "quality", "--invocation-id", "i", "--run-id", "r", "--run-attempt", "1",
                "--commit", "c", "--ref", "r", "--expected-job", "good| |",
                "--expected-job", "bad| |",
            ).returncode, 0)
            self.assertEqual(run_helper(
                "fragment", "--out", str(fragments / "good.json"), "--logical-job", "good",
                "--invocation-id", "i", "--run-id", "r", "--run-attempt", "1", "--state", "run",
                "--outcome", "success", "--reason", "completed", "--reason-code", "completed",
            ).returncode, 0)
            (fragments / "bad.json").write_text(json.dumps({
                "schema_version": 1, "kind": "workflow-scope-fragment",
                "identity": {"producer": "gate", "workflow": "quality", "invocation_id": "i", "run_id": "r", "run_attempt": "1", "logical_job": "bad", "leg": ""},
                "state": "run", "outcome": "success", "diagnostics": {"unexpected": "container"},
                "tools": "malformed", "tool_collection": [],
            }))
            (fragments / "malformed-kind.json").write_text(json.dumps({
                "schema_version": 1, "kind": [], "identity": {},
            }))
            for name, field, invalid in (("malformed-state", "state", []), ("malformed-outcome", "outcome", {})):
                malformed = {
                    "schema_version": 1, "kind": "workflow-scope-fragment",
                    "identity": {"producer": "gate", "workflow": "quality", "invocation_id": "i", "run_id": "r", "run_attempt": "1", "logical_job": name, "leg": ""},
                    "state": "run", "outcome": "success",
                }
                malformed[field] = invalid
                (fragments / f"{name}.json").write_text(json.dumps(malformed))
            out = root / "out.json"
            result = run_helper("collect", "--manifest", str(manifest), "--fragments-dir", str(fragments), "--out", str(out))
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(out.read_text())
            self.assertEqual(data["collection"]["status"], "partial")
            self.assertEqual(next(job for job in data["jobs"] if job["logical_job"] == "good")["outcome"], "success")
            bad = next(job for job in data["jobs"] if job["logical_job"] == "bad")
            self.assertEqual(bad["tool_collection"]["status"], "partial")
            self.assertTrue(any("tools container is not a list" in issue for issue in data["collection"]["issues"]))
            self.assertTrue(any("diagnostics container is malformed" in issue for issue in data["collection"]["issues"]))
            self.assertTrue(any("unsupported workflow scope contract" in issue for issue in data["collection"]["issues"]))
            self.assertTrue(any("fragment state is invalid" in issue for issue in data["collection"]["issues"]))
            self.assertTrue(any("fragment outcome is invalid" in issue for issue in data["collection"]["issues"]))
            self.assertTrue(any("bad" in line and "Tool collection issue" in line for line in data["summary"]["lines"]))

    def test_malformed_nested_rust_scope_keeps_collector_renderable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "manifest.json"
            fragments = root / "fragments"
            fragments.mkdir()
            self.assertEqual(run_helper(
                "init", "--out", str(manifest), "--root", str(root), "--languages", "none",
                "--workflow", "quality", "--invocation-id", "i", "--run-id", "r", "--run-attempt", "1",
                "--commit", "c", "--ref", "r", "--expected-job", "good| |",
                "--expected-job", "rust| |",
            ).returncode, 0)
            self.assertEqual(run_helper(
                "fragment", "--out", str(fragments / "good.json"), "--logical-job", "good",
                "--invocation-id", "i", "--run-id", "r", "--run-attempt", "1", "--state", "run",
                "--outcome", "success", "--reason", "completed", "--reason-code", "completed",
            ).returncode, 0)
            unknown_measurement = {"status": "unknown", "count": None, "unit": "source_path", "method": "fixture", "reason": "fixture"}
            tool = {
                "name": "clippy", "command": ["cargo", "clippy"], "working_directory": str(root),
                "state": "run", "outcome": "success", "reason": "completed", "reason_code": "completed",
                "exit_code": 0, "diagnostics": [],
                "measurements": {name: dict(unknown_measurement) for name in ("examined", "unparsed", "policy_excluded")},
                "rust": {"requested": {}, "observed": None, "collection": {"issues": None}},
            }
            (fragments / "rust.json").write_text(json.dumps({
                "schema_version": 1, "kind": "workflow-scope-fragment",
                "identity": {"producer": "gate", "workflow": "quality", "invocation_id": "i", "run_id": "r", "run_attempt": "1", "logical_job": "rust", "leg": ""},
                "state": "run", "outcome": "success", "diagnostics": [], "tools": [tool],
                "tool_collection": {"status": "complete", "issues": []},
            }))
            out = root / "out.json"
            result = run_helper("collect", "--manifest", str(manifest), "--fragments-dir", str(fragments), "--out", str(out))
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(out.read_text())
            self.assertEqual(data["collection"]["status"], "partial")
            self.assertEqual(next(job for job in data["jobs"] if job["logical_job"] == "good")["outcome"], "success")
            rust = next(job for job in data["jobs"] if job["logical_job"] == "rust")
            self.assertEqual(rust["tools"][0]["collection"]["status"], "partial")
            self.assertTrue(any("invalid Rust observed scope" in issue for issue in data["collection"]["issues"]))
            self.assertTrue(any("invalid Rust collection issues" in issue for issue in data["collection"]["issues"]))

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
        self.assertTrue(collector["continue-on-error"])
        self.assertEqual(
            set(collector["needs"]),
            {"detect", "typescript", "dotnet", "python", "rust", "java", "layer2", "coverage"},
        )
        body = WORKFLOW.read_text(encoding="utf-8")
        self.assertGreaterEqual(body.count("actions/workflow-scope@"), 9)
        self.assertNotIn("actions/workflow-scope@v1", body)
        self.assertIn("mode: collect", body)
        self.assertIn("if: always()", body)
        for line_number, line in enumerate(body.splitlines()):
            if "actions/workflow-scope@" in line:
                self.assertEqual(body.splitlines()[line_number + 1].strip(), "continue-on-error: true")
        self.assertIn("job-outcomes: ${{ toJSON(needs) }}", body)
        self.assertIn("if: '!cancelled()'", body)
        self.assertIn("steps.scan.outcome == 'skipped'", body)

        action = yaml.safe_load((ROOT / "actions" / "workflow-scope" / "action.yml").read_text(encoding="utf-8"))
        for step in action["runs"]["steps"]:
            uses = step.get("uses", "")
            if uses.startswith("actions/upload-artifact@"):
                self.assertEqual(uses.split("@", 1)[1].split()[0], "043fb46d1a93c77aae656e7c1c64a875d1fc6a0a")
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

    def test_real_collector_action_preserves_two_legs_and_missing_third(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inputs = root / "inputs"
            manifest_path = inputs / "manifest-artifact" / "maxi-quality-workflow-scope-manifest.json"
            manifest_path.parent.mkdir(parents=True)
            self.assertEqual(run_helper("init", "--out", str(manifest_path), "--root", str(root), "--languages", "none", "--workflow", "quality", "--invocation-id", "invocation", "--run-id", "run", "--run-attempt", "1", "--commit", "c", "--ref", "r", "--expected-job", "typescript|ts|packages/a", "--expected-job", "typescript|ts|packages/b", "--expected-job", "typescript|ts|packages/c").returncode, 0)
            for index, (leg, outcome) in enumerate((("packages/a", "success"), ("packages/b", "failure"))):
                path = inputs / f"artifact-{index}" / "maxi-quality-workflow-scope-fragment.json"
                path.parent.mkdir()
                reason = outcome if outcome == "success" else "bad\nreason `" + ("x" * 500)
                fragment_args = ["fragment", "--out", str(path), "--logical-job", "typescript", "--language", "ts", "--leg", leg, "--invocation-id", "invocation", "--run-id", "run", "--run-attempt", "1", "--state", "run", "--outcome", outcome, "--reason", reason]
                if outcome == "failure":
                    fragment_args += ["--diagnostic", reason]
                self.assertEqual(run_helper(*fragment_args).returncode, 0)
            env = {
                **os.environ,
                "INPUT_ROOT": str(inputs),
                "LAYER2_INPUT_ROOT": str(root / "no-layer2"),
                "OUT": str(root / "out.json"),
                "ROOT": str(root),
                "PRODUCER": "gate",
                "WORKFLOW": "quality",
                "INVOCATION": "invocation",
                "RUN_ID": "run",
                "RUN_ATTEMPT": "1",
                "COMMIT": "c",
                "REF": "r",
                "LANGUAGES": "none",
                "MODE_NAME": "full",
                "BASELINE": "",
                "EXPECTED": "[]",
                "COVERAGE": "not_applicable",
                "JOB_OUTCOMES": "{}",
                "LAYER2_INVOCATION": "",
                "CANCELLATION": "",
                "RUNNER_TEMP": str(root),
                "GITHUB_ACTION_PATH": str(ROOT / "actions/workflow-scope"),
                "GITHUB_STEP_SUMMARY": str(root / "summary.md"),
            }
            result = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", extract_action_body("Collect and publish workflow scope")], env=env, text=True, capture_output=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads((root / "out.json").read_text())
            jobs = {job["leg"]: job for job in data["jobs"] if job["logical_job"] == "typescript"}
            self.assertEqual(jobs["packages/a"]["outcome"], "success")
            self.assertEqual(jobs["packages/b"]["outcome"], "failure")
            self.assertEqual(jobs["packages/c"]["reason_code"], "missing_fragment")
            summary_lines = (root / "summary.md").read_text().splitlines()
            self.assertTrue(any("\\n" in line and "..." in line for line in summary_lines))
            self.assertTrue(all(len(line) <= 240 for line in summary_lines))
            self.assertTrue(any(line.startswith("Evidence artifact:") for line in summary_lines))
            self.assertTrue(any(line.startswith("Diagnostic ") for line in summary_lines))
            self.assertIn("bad\\nreason", json.dumps(data))

    def test_real_collector_action_preserves_legs_without_sha256sum(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inputs = root / "inputs"
            manifest_path = inputs / "manifest-artifact" / "maxi-quality-workflow-scope-manifest.json"
            manifest_path.parent.mkdir(parents=True)
            self.assertEqual(
                run_helper(
                    "init", "--out", str(manifest_path), "--root", str(root), "--languages", "none",
                    "--workflow", "quality", "--invocation-id", "transport", "--run-id", "run",
                    "--run-attempt", "1", "--commit", "c", "--ref", "r",
                    "--expected-job", "typescript|ts|packages/a",
                    "--expected-job", "typescript|ts|packages/b",
                ).returncode,
                0,
            )
            for index, (leg, outcome) in enumerate((("packages/a", "success"), ("packages/b", "failure"))):
                path = inputs / f"artifact-{index}" / "maxi-quality-workflow-scope-fragment.json"
                path.parent.mkdir()
                self.assertEqual(
                    run_helper(
                        "fragment", "--out", str(path), "--logical-job", "typescript", "--language", "ts",
                        "--leg", leg, "--invocation-id", "transport", "--run-id", "run",
                        "--run-attempt", "1", "--state", "run", "--outcome", outcome,
                        "--reason", f"{leg} {outcome}",
                    ).returncode,
                    0,
                )

            fake_bin = root / "bin"
            fake_bin.mkdir()
            unavailable = fake_bin / "sha256sum"
            unavailable.write_text("#!/bin/sh\nexit 127\n")
            unavailable.chmod(0o755)
            env = {
                **os.environ,
                "PATH": f"{fake_bin}:{os.environ['PATH']}",
                "INPUT_ROOT": str(inputs),
                "LAYER2_INPUT_ROOT": str(root / "no-layer2"),
                "OUT": str(root / "out.json"),
                "ROOT": str(root),
                "PRODUCER": "gate",
                "WORKFLOW": "quality",
                "INVOCATION": "transport",
                "RUN_ID": "run",
                "RUN_ATTEMPT": "1",
                "COMMIT": "c",
                "REF": "r",
                "LANGUAGES": "none",
                "MODE_NAME": "full",
                "BASELINE": "",
                "EXPECTED": "[]",
                "COVERAGE": "not_applicable",
                "JOB_OUTCOMES": "{}",
                "LAYER2_INVOCATION": "",
                "CANCELLATION": "",
                "RUNNER_TEMP": str(root),
                "GITHUB_ACTION_PATH": str(ROOT / "actions/workflow-scope"),
                "GITHUB_STEP_SUMMARY": str(root / "summary.md"),
            }
            result = subprocess.run(
                ["bash", "-e", "-o", "pipefail", "-c", extract_action_body("Collect and publish workflow scope")],
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads((root / "out.json").read_text())
            jobs = {job["leg"]: job for job in data["jobs"] if job["logical_job"] == "typescript"}
            self.assertEqual(jobs["packages/a"]["outcome"], "success")
            self.assertEqual(jobs["packages/b"]["outcome"], "failure")
            self.assertEqual(data["collection"]["status"], "complete")

    def test_fragment_transport_name_is_safe_for_matrix_paths(self) -> None:
        action = yaml.safe_load((ROOT / "actions/workflow-scope/action.yml").read_text(encoding="utf-8"))
        upload = next(step for step in action["runs"]["steps"] if step["name"] == "Upload workflow scope fragment")
        self.assertNotIn("inputs.leg", upload["with"]["name"])
        with tempfile.TemporaryDirectory() as tmp:
            env = {
                **os.environ,
                "OUT": str(Path(tmp) / "fragment.json"),
                "PRODUCER": "gate", "WORKFLOW": "quality", "INVOCATION": "i", "RUN_ID": "r", "RUN_ATTEMPT": "1",
                "LOGICAL_JOB": "typescript", "LANGUAGE": "ts", "LEG": "packages/a", "STATE": "run", "OUTCOME": "success",
                "REASON": "ok", "REASON_CODE": "matrix", "DIAGNOSTIC": "", "DIAGNOSTIC_FILE": "", "ARTIFACT_PREFIX": "safe",
                "GITHUB_ACTION_PATH": str(ROOT / "actions/workflow-scope"), "GITHUB_OUTPUT": str(Path(tmp) / "output"),
            }
            result = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", extract_action_body("Write workflow scope fragment")], env=env, text=True, capture_output=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            artifact_name = (Path(tmp) / "output").read_text().strip().split("=", 1)[1]
            self.assertNotIn("/", artifact_name)

    def test_collector_keeps_actual_layer2_scope_from_same_invocation_and_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inputs = root / "inputs"
            manifest = inputs / "manifest" / "maxi-quality-workflow-scope-manifest.json"
            manifest.parent.mkdir(parents=True)
            self.assertEqual(run_helper("init", "--out", str(manifest), "--root", str(root), "--languages", "none", "--workflow", "quality", "--invocation-id", "invocation", "--run-id", "run", "--run-attempt", "1", "--commit", "c", "--ref", "r", "--expected-job", "layer2||").returncode, 0)
            layer2 = root / "layer2" / "maxi-quality-layer2-scope.json"
            layer2.parent.mkdir()
            result = subprocess.run([sys.executable, str(ROOT / "scripts/layer2_scope.py"), "init", "--out", str(layer2), "--producer", "gate", "--workflow", "quality", "--invocation-id", "layer2-invocation", "--run-id", "run", "--run-attempt", "1", "--job", "layer2", "--commit", "c", "--ref", "r", "--mode", "full"], text=True, capture_output=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            layer2_artifact = inputs / "layer2-artifact" / layer2.name
            layer2_artifact.parent.mkdir(parents=True)
            layer2_artifact.write_text(layer2.read_text())
            foreign = json.loads(layer2.read_text())
            foreign["identity"]["invocation_id"] = "other-layer2"
            (inputs / "layer2-artifact" / "foreign.json").write_text(json.dumps(foreign))
            (inputs / "layer2-artifact" / "malformed.json").write_text("[]\n")
            env = {
                **os.environ,
                "INPUT_ROOT": str(inputs),
                "LAYER2_INPUT_ROOT": str(inputs / "layer2-artifact"),
                "OUT": str(root / "out.json"),
                "ROOT": str(root), "PRODUCER": "gate", "WORKFLOW": "quality", "INVOCATION": "invocation",
                "RUN_ID": "run", "RUN_ATTEMPT": "1", "COMMIT": "c", "REF": "r", "LANGUAGES": "none",
                "MODE_NAME": "full", "BASELINE": "", "EXPECTED": "[]", "COVERAGE": "not_applicable",
                "JOB_OUTCOMES": "{}",
                "LAYER2_INVOCATION": "layer2-invocation", "CANCELLATION": "", "RUNNER_TEMP": str(root),
                "GITHUB_ACTION_PATH": str(ROOT / "actions/workflow-scope"), "GITHUB_STEP_SUMMARY": str(root / "summary.md"),
            }
            action_result = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", extract_action_body("Collect and publish workflow scope")], env=env, text=True, capture_output=True, check=False)
            self.assertEqual(action_result.returncode, 0, action_result.stderr)
            data = json.loads((root / "out.json").read_text())
            self.assertEqual(len(data["layer2"]), 1)
            self.assertIn("semgrep", data["layer2"][0]["tools"])
            self.assertEqual(data["jobs"][0]["scope"][0]["identity"]["invocation_id"], "layer2-invocation")
            self.assertTrue(any("foreign Layer 2" in issue for issue in data["collection"]["issues"]))
            self.assertTrue(any("malformed Layer 2" in issue for issue in data["collection"]["issues"]))

    def test_real_collector_action_falls_back_on_missing_or_invalid_current_manifest(self) -> None:
        for invalid in (False, True):
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                inputs = root / "inputs"
                inputs.mkdir()
                empty_workspace = root / "empty-workspace"
                empty_workspace.mkdir()
                if invalid:
                    (inputs / "bad-manifest.json").write_text("not-json\n")
                else:
                    fresh = inputs / "fresh-artifact" / "maxi-quality-workflow-scope-fragment.json"
                    fresh.parent.mkdir()
                    self.assertEqual(run_helper(
                        "fragment", "--out", str(fresh), "--logical-job", "typescript", "--language", "ts",
                        "--leg", "pkg", "--invocation-id", "current", "--run-id", "run", "--run-attempt", "2",
                        "--state", "run", "--outcome", "failure", "--reason", "fresh failed rerun",
                    ).returncode, 0)
                env = {
                    **os.environ,
                    "INPUT_ROOT": str(inputs), "LAYER2_INPUT_ROOT": str(root / "no-layer2"), "OUT": str(root / "out.json"),
                    "ROOT": str(empty_workspace), "PRODUCER": "gate", "WORKFLOW": "quality", "INVOCATION": "current",
                    "RUN_ID": "run", "RUN_ATTEMPT": "2", "COMMIT": "c", "REF": "r", "LANGUAGES": "ts",
                    "MODE_NAME": "full", "BASELINE": "", "EXPECTED": "[{\"logical_job\":\"typescript\",\"language\":\"ts\",\"leg\":\"pkg\"}]",
                    "COVERAGE": "not_applicable", "LAYER2_INVOCATION": "", "CANCELLATION": "", "RUNNER_TEMP": str(root),
                    "JOB_OUTCOMES": "{}",
                    "GITHUB_ACTION_PATH": str(ROOT / "actions/workflow-scope"), "GITHUB_STEP_SUMMARY": str(root / "summary.md"),
                }
                result = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", extract_action_body("Collect and publish workflow scope")], env=env, text=True, capture_output=True, check=False)
                self.assertEqual(result.returncode, 0, result.stderr)
                data = json.loads((root / "out.json").read_text())
                self.assertEqual(data["identity"]["run_attempt"], "2")
                self.assertEqual(data["collection"]["status"], "partial")
                self.assertTrue(data["collection"]["issues"])
                if invalid:
                    self.assertIsNone(data["jobs"][0]["examined"]["count"])
                else:
                    self.assertEqual(data["presence"]["ts"]["state"], "unknown")
                    fresh_job = next(job for job in data["jobs"] if job["logical_job"] == "typescript")
                    self.assertEqual(fresh_job["outcome"], "failure")
                    self.assertEqual(data["analysis"]["outcome"], "failure")

    def test_missing_manifest_reconciles_fresh_fragment_without_rediscovering_collector_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fragments = root / "fragments"
            fragments.mkdir()
            fresh = fragments / "fresh.json"
            self.assertEqual(run_helper(
                "fragment", "--out", str(fresh), "--workflow", "quality", "--invocation-id", "inv",
                "--run-id", "123", "--run-attempt", "2", "--logical-job", "typescript", "--language", "ts",
                "--leg", "packages/a", "--state", "run", "--outcome", "failure", "--reason", "fresh failed rerun",
            ).returncode, 0)
            out = root / "out.json"
            self.assertEqual(run_helper(
                "collect", "--manifest", str(root / "missing-manifest.json"), "--fragments-dir", str(fragments),
                "--out", str(out), "--root", str(root / "empty-workspace"), "--workflow", "quality",
                "--invocation-id", "inv", "--run-id", "123", "--run-attempt", "2", "--expected-job",
                "typescript|ts|packages/a",
            ).returncode, 0)
            data = json.loads(out.read_text())
            self.assertEqual(data["presence"]["ts"]["state"], "unknown")
            job = next(job for job in data["jobs"] if job["logical_job"] == "typescript")
            self.assertEqual(job["outcome"], "failure")
            self.assertEqual(data["analysis"]["outcome"], "failure")


if __name__ == "__main__":
    unittest.main()
