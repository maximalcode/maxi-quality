#!/usr/bin/env bash
# Exercise whole-workflow scope at the detector and fragment seams.
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
python3 "$ROOT/samples/workflow-scope/test_scope.py"
python3 "$ROOT/samples/workflow-scope/test_language_tools.py"

# The fixture must execute the detector body that ships in quality.yml. Keep
# this check textual and structural: actionlint owns YAML syntax, while the
# Python tests above execute the extracted body against a mixed fixture.
python3 - "$ROOT" <<'PY'
import pathlib
import yaml
import sys

root = pathlib.Path(sys.argv[1])
workflow = yaml.safe_load((root / ".github/workflows/quality.yml").read_text())
ci = yaml.safe_load((root / ".github/workflows/ci.yml").read_text())
jobs = workflow["jobs"]
assert any(step.get("id") == "scan" for step in jobs["detect"]["steps"])
assert any(step.get("id") == "scope-expected" for step in jobs["detect"]["steps"])
assert jobs["workflow-scope"]["if"] == "always()"
assert set(jobs["workflow-scope"]["needs"]) == {
    "detect", "typescript", "dotnet", "python", "rust", "java", "layer2", "coverage"
}
fixture_job = ci["jobs"]["detect-fixtures"]
fixture_run = next(step["run"] for step in fixture_job["steps"] if "every fixture" in step.get("name", "").lower())
assert "bash samples/workflow-scope/run.sh" in fixture_run
print("OK: extracted detector body, all-outcome collector wiring, and direct job needs")
PY
