#!/usr/bin/env python3
"""Exercise the coverage CLI and action through their public inputs and outputs."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "samples/coverage/patch"


class CoverageTests(unittest.TestCase):
    def test_nonfinite_threshold_cannot_pass_an_uncovered_patch(self):
        result = subprocess.run(
            [
                "python3", str(ROOT / "scripts/coverage.py"),
                "--report", str(FIXTURE / "lcov.info"),
                "--floor-file", str(FIXTURE / "floor.json"),
                "--diff-file", str(FIXTURE / "changed.diff"),
                "--patch-threshold", "nan",
            ],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
        self.assertIn("--patch-threshold must be finite", result.stderr)
        self.assertNotIn("patch_status=ok", result.stdout)

    def test_disabled_action_retains_patch_measurement(self):
        shell = subprocess.check_output(
            ["ruby", "-ryaml", "-e",
             "puts YAML.load_file(ARGV[0])['runs']['steps'][0]['run']",
             str(ROOT / "actions/coverage/action.yml")], text=True,
        )
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            source = repo / "samples/coverage/patch/src/rollup.ts"
            source.parent.mkdir(parents=True)
            source.write_bytes((FIXTURE / "src/rollup.ts").read_bytes())

            def git(*args):
                subprocess.run(["git", *args], cwd=repo, check=True,
                               capture_output=True)

            git("init", "-q")
            git("config", "user.name", "maximalcode")
            git("config", "user.email", "213183497+maximalcode@users.noreply.github.com")
            git("apply", "-R", str(FIXTURE / "changed.diff"))
            git("add", ".")
            git("commit", "-qm", "fixture base")
            git("branch", "base")
            git("apply", str(FIXTURE / "changed.diff"))
            git("add", ".")
            git("commit", "-qm", "fixture patch")
            output = repo / "output"
            result = subprocess.run(
                ["bash", "-c", shell], cwd=repo, capture_output=True, text=True,
                env=os.environ | {
                    "REPORTS": str(FIXTURE / "lcov.info"),
                    "FLOOR_FILE": str(FIXTURE / "floor.json"),
                    "TOLERANCE": "0.1", "RAISE": "false",
                    "PATCH_THRESHOLD": "0", "BASE_REF": "base", "GH_BASE_REF": "",
                    "GITHUB_ACTION_PATH": str(ROOT / "actions/coverage"),
                    "RUNNER_TEMP": directory, "GITHUB_OUTPUT": str(output),
                    "GITHUB_STEP_SUMMARY": str(repo / "summary"),
                }, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            values = dict(line.split("=", 1) for line in output.read_text().splitlines())
            self.assertEqual(values["patch_coverage"], "0.00")
            self.assertEqual(values["patch_status"], "off")
            self.assertEqual(values["status"], "ok")


if __name__ == "__main__":
    unittest.main()
