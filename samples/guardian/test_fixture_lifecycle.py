"""Temporary Git fixtures must not leave automatic writers racing cleanup."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from test_setup_hosts import BASELINE, project as host_project

spec = importlib.util.spec_from_file_location("guardian_checks", BASELINE / "scripts/check-guardian.py")
checks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checks)


class FixtureLifecycleTests(unittest.TestCase):
    def test_fixture_commits_do_not_launch_automatic_maintenance(self):
        for name, create in (("runner", checks.project), ("host", host_project)):
            with self.subTest(helper=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                trace = root / "git-trace.json"
                with patch.dict(os.environ, {"GIT_TRACE2_EVENT": str(trace)}):
                    fixture = create(root / "fixture")
                    (fixture / "source.txt").write_text("second commit\n")
                    subprocess.run(["git", "add", "."], cwd=fixture, check=True)
                    subprocess.run([
                        "git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                        "-c", "core.hooksPath=/dev/null", "commit", "-qm", "second fixture commit",
                    ], cwd=fixture, check=True)
                children = [entry["argv"] for line in trace.read_text().splitlines()
                            if (entry := json.loads(line)).get("event") == "child_start"]
                maintenance = [argv for argv in children
                               if "maintenance" in argv and "--auto" in argv]
                self.assertEqual(maintenance, [], "automatic Git writers can outlive fixture cleanup")
