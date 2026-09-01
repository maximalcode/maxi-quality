"""Exercise the published analysis-coverage manifest seam.

The issue's required fixture is deliberately a language that detection found
but whose job GitHub skipped.  A manifest that only renders detected/absent
would call both that state and an inapplicable language "skipped", hiding the
hole it exists to make visible.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "coverage-manifest.py"
FIXTURE = Path(__file__).parent / "present-but-skipped" / "semgrep.json"
REPO_SHAPE = Path(__file__).parent / "present-but-skipped" / "repo"


def main() -> int:
    # This is a real TypeScript/JavaScript project marker, not an invented
    # boolean: the fixture's premise is that detection found a project before
    # GitHub skipped its downstream job.
    assert (REPO_SHAPE / "package.json").is_file()
    detected = {
        "has_ts": str((REPO_SHAPE / "package.json").is_file()).lower(),
        "has_dotnet": "false",
        "has_python": str((REPO_SHAPE / "pyproject.toml").is_file()).lower(),
        "has_rust": "false",
        "has_java": "false",
    }
    jobs = {
        "typescript": "skipped",
        "dotnet": "skipped",
        "python": "success",
        "rust": "skipped",
        "java": "skipped",
        "layer2": "failure",
    }
    with tempfile.TemporaryDirectory(prefix="coverage-manifest-") as temp:
        temp_path = Path(temp)
        detected_path = temp_path / "detected.json"
        jobs_path = temp_path / "jobs.json"
        log_path = temp_path / "scan.log"
        out_path = temp_path / "manifest.json"
        summary_path = temp_path / "summary.md"
        detected_path.write_text(json.dumps(detected), encoding="utf-8")
        jobs_path.write_text(json.dumps(jobs), encoding="utf-8")
        log_path.write_text("gitleaks scanner error: connection refused\n", encoding="utf-8")

        subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--languages",
                "auto",
                "--detected",
                str(detected_path),
                "--job-results",
                str(jobs_path),
                "--semgrep-json",
                str(FIXTURE),
                "--scan-log",
                str(log_path),
                "--out",
                str(out_path),
                "--summary",
                str(summary_path),
            ],
            check=True,
        )
        manifest = json.loads(out_path.read_text(encoding="utf-8"))
        assert manifest["languages"]["typescript"]["state"] == "skipped"
        assert manifest["languages"]["typescript"]["detected"] is True
        assert manifest["languages"]["dotnet"]["state"] == "not_applicable"
        assert manifest["languages"]["python"]["state"] == "ran"
        assert manifest["tools"]["semgrep"]["examined"] == 2
        assert manifest["tools"]["semgrep"]["unparsed"] == 1
        assert manifest["tools"]["semgrep"]["excluded_by_policy"] == 1
        assert manifest["tools"]["semgrep"]["errors"] == [
            {"message": "Syntax error", "path": "src/Unsupported.cs", "type": "PartialParsing"}
        ]
        assert manifest["tools"]["gitleaks"]["errors"] == [
            "gitleaks scanner error: connection refused"
        ]
        assert manifest["layer2"] == {"job_result": "failure"}
        assert manifest["rust"]["clippy"] == {"state": "not_applicable"}
        summary = summary_path.read_text(encoding="utf-8")
        assert "TypeScript | detected | skipped" in summary
        assert "gitleaks scanner error: connection refused" in summary
    print("OK: present language, skipped job, and scanner evidence are all named")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
