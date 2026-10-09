#!/usr/bin/env python3
"""Observable contract checks for the Layer 2 scope artifact."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]
SCOPE = ROOT / "scripts" / "layer2_scope.py"


class Layer2ScopeContractTests(unittest.TestCase):
    def run_scope(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCOPE), *args],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_initialization_has_identity_and_unknown_measurements(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "layer2-scope.json"
            result = self.run_scope(
                "init",
                "--out",
                str(out),
                "--producer",
                "gate",
                "--workflow",
                "quality",
                "--invocation-id",
                "run-7",
                "--run-id",
                "7",
                "--run-attempt",
                "2",
                "--job",
                "layer2",
                "--commit",
                "abc",
                "--ref",
                "refs/heads/main",
                "--mode",
                "full",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(out.read_text())
            self.assertEqual(data["schema_version"], 1)
            self.assertEqual(data["kind"], "layer2-scope")
            self.assertEqual(data["identity"]["producer"], "gate")
            self.assertEqual(data["identity"]["run_attempt"], "2")
            for name in ("semgrep", "gitleaks", "osv", "licenses", "sbom"):
                self.assertIn(name, data["tools"])
                expected_state = "unknown" if name in {"semgrep", "gitleaks", "osv"} else "not_applicable"
                self.assertEqual(data["tools"][name]["state"], expected_state)
                self.assertIn("effective", data["tools"][name])
                for measurement in data["tools"][name]["measurements"].values():
                    expected_status = "unknown" if expected_state == "unknown" else "not_applicable"
                    self.assertEqual(measurement["status"], expected_status)
                    self.assertIsNone(measurement["count"])
                    self.assertTrue(measurement["unit"])
                    self.assertTrue(measurement["method"])
                    self.assertTrue(measurement["reason"])

    def test_finalize_keeps_diagnostics_and_separates_outcome_from_collection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "layer2-scope.json"
            log = Path(tmp) / "semgrep.log"
            log.write_text("first <error> `quoted` & second line\n" + "x" * 260)
            init = self.run_scope(
                "init",
                "--out",
                str(out),
                "--producer",
                "report",
                "--workflow",
                "quality-report",
                "--invocation-id",
                "run-8",
                "--run-id",
                "8",
                "--run-attempt",
                "1",
                "--job",
                "report",
                "--commit",
                "def",
                "--ref",
                "refs/heads/main",
                "--mode",
                "full",
            )
            self.assertEqual(init.returncode, 0, init.stderr)
            record = self.run_scope(
                "record",
                "--out",
                str(out),
                "--tool",
                "semgrep",
                "--state",
                "run",
                "--outcome",
                "failure",
                "--exit-code",
                "1",
                "--reason",
                "scanner exited",
                "--log",
                str(log),
            )
            self.assertEqual(record.returncode, 0, record.stderr)
            final = self.run_scope(
                "finalize",
                "--out",
                str(out),
                "--analysis-outcome",
                "failure",
                "--analysis-exit-code",
                "1",
                "--collection-status",
                "complete",
            )
            self.assertEqual(final.returncode, 0, final.stderr)
            data = json.loads(out.read_text())
            self.assertEqual(data["analysis"]["outcome"], "failure")
            self.assertEqual(data["collection"]["status"], "complete")
            self.assertEqual(data["tools"]["semgrep"]["outcome"], "failure")
            self.assertEqual(data["tools"]["semgrep"]["diagnostics"][0]["text"], log.read_text())
            summary = "\n".join(data["summary"]["lines"])
            self.assertIn("&lt;error&gt;", summary)
            self.assertIn("...", summary)

    def test_init_does_not_reuse_another_run_in_the_same_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "layer2-scope.json"
            common = [
                "init", "--out", str(out), "--producer", "gate", "--workflow", "quality",
                "--run-attempt", "1", "--job", "layer2", "--commit", "abc",
                "--ref", "refs/heads/main", "--mode", "full", "--fragment-id", "leg-a",
            ]
            first = self.run_scope(*common, "--invocation-id", "run-a", "--run-id", "a")
            self.assertEqual(first.returncode, 0, first.stderr)
            second = self.run_scope(*common, "--invocation-id", "run-b", "--run-id", "b")
            self.assertEqual(second.returncode, 0, second.stderr)
            data = json.loads(out.read_text())
            self.assertEqual(data["identity"]["run_id"], "b")

    def test_semgrep_measurements_normalize_deduplicate_and_keep_units(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "target"
            root.mkdir()
            (root / "src").mkdir()
            (root / "src" / "a.ts").write_text("export const a = 1;\n")
            result = Path(tmp) / "semgrep.json"
            result.write_text(json.dumps({
                "version": "1.172.0",
                "results": [],
                "errors": [
                    {"type": ["PartialParsing", {}], "path": "src/a.ts"},
                    {"type": "Timeout", "path": "/repo/src/a.ts"},
                ],
                "paths": {
                    "scanned": ["src/../src/a.ts", "/repo/src/a.ts"],
                    "skipped": [
                        {"path": "legacy", "reason": "cli_exclude_flags_match"},
                        {"path": "/repo/legacy", "reason": "cli_exclude_flags_match"},
                        {"path": "ignored.ts", "reason": "semgrepignore_patterns_match"},
                    ],
                },
            }))
            out = Path(tmp) / "scope.json"
            init = self.run_scope(
                "init", "--out", str(out), "--producer", "gate", "--workflow", "quality",
                "--invocation-id", "measure", "--run-id", "measure", "--run-attempt", "1",
                "--job", "layer2", "--commit", "abc", "--ref", "main", "--mode", "full",
            )
            self.assertEqual(init.returncode, 0, init.stderr)
            measured = self.run_scope(
                "measure-semgrep", "--out", str(out), "--results", str(result),
                "--scan-root", str(root), "--scanner-root", "/repo", "--mode", "full",
            )
            self.assertEqual(measured.returncode, 0, measured.stderr)
            data = json.loads(out.read_text())
            measurements = data["tools"]["semgrep"]["measurements"]
            self.assertEqual(measurements["examined"]["count"], 1)
            self.assertEqual(measurements["unparsed"]["count"], 1)
            self.assertEqual(measurements["policy_excluded"]["count"], 1)
            self.assertTrue(all(item["unit"] == "target_path" for item in measurements.values()))

    def test_semgrep_measurements_unknown_when_skip_evidence_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "target"
            root.mkdir()
            result = Path(tmp) / "semgrep.json"
            result.write_text(json.dumps({
                "version": "1.172.0", "results": [], "errors": [],
                "paths": {"scanned": []},
            }))
            out = Path(tmp) / "scope.json"
            init = self.run_scope(
                "init", "--out", str(out), "--producer", "gate", "--workflow", "quality",
                "--invocation-id", "missing", "--run-id", "missing", "--run-attempt", "1",
                "--job", "layer2", "--commit", "abc", "--ref", "main", "--mode", "full",
            )
            self.assertEqual(init.returncode, 0, init.stderr)
            measured = self.run_scope(
                "measure-semgrep", "--out", str(out), "--results", str(result),
                "--scan-root", str(root), "--mode", "full",
            )
            self.assertEqual(measured.returncode, 0, measured.stderr)
            data = json.loads(out.read_text())
            policy = data["tools"]["semgrep"]["measurements"]["policy_excluded"]
            self.assertIsNone(policy["count"])
            self.assertEqual(policy["status"], "unknown")
            self.assertIn("verbose skip metadata", policy["reason"])

    def test_action_wires_independent_all_outcome_publication(self) -> None:
        action = yaml.safe_load((ROOT / "actions" / "layer2" / "action.yml").read_text())
        steps = action["runs"]["steps"]
        by_name = {step["name"]: step for step in steps}
        for name in (
            "Initialize Layer 2 scope evidence",
            "Retain setup diagnostics in scope evidence",
            "Publish Layer 2 scope artifact",
            "Publish Layer 2 scope summary",
        ):
            self.assertEqual(by_name[name]["if"], "always()")
        self.assertTrue(by_name["Publish Layer 2 scope artifact"]["continue-on-error"])
        self.assertTrue(by_name["Publish Layer 2 scope summary"]["continue-on-error"])
        self.assertIn("steps.install.outcome == 'success'", by_name["Layer 2 scan"]["if"])
        self.assertEqual(
            by_name["Finalize scope after tool setup failure"]["if"],
            "always() && steps.install.outcome != 'success'",
        )
        quality = (ROOT / ".github" / "workflows" / "quality.yml").read_text()
        report = (ROOT / ".github" / "workflows" / "quality-report.yml").read_text()
        self.assertIn("producer: gate", quality)
        self.assertIn("producer: report", report)
        self.assertIn(
            'LAYER2_INVOCATION_ID:-${GITHUB_RUN_ID:-local}',
            (ROOT / "actions" / "layer2" / "action.yml").read_text(),
        )
        self.assertIn(
            'LAYER2_INVOCATION_ID:-${GITHUB_RUN_ID:-local}',
            (ROOT / "scripts" / "scan.sh").read_text(),
        )


if __name__ == "__main__":
    unittest.main()
