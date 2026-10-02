#!/usr/bin/env python3
"""Run a declared local gate with versioned evidence, or check its freshness."""

from __future__ import annotations

import argparse
import datetime
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
GUARD_DIR = Path(__file__).resolve().parent / "agent-guard"
sys.path.insert(0, str(GUARD_DIR))
from guard import (  # noqa: E402
    CONFIG, RECEIPT, InspectionError, fingerprint, gate_argv, gate_command, git,
    repo_root,
)

spec = importlib.util.spec_from_file_location("recorder", GUARD_DIR / "record-gate.py")
recorder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recorder)


def clear_git_environment() -> None:
    # Git exports checkout routing variables when invoking hooks. The explicit
    # project root must win over a caller's Git environment.
    for name in git("rev-parse", "--local-env-vars").splitlines():
        os.environ.pop(name, None)


def code_state(root: str) -> dict:
    """HEAD plus the recorder's content fingerprint, without a second authority."""
    return {"head": git("rev-parse", "--verify", "HEAD", cwd=root).strip(),
            "fingerprint": fingerprint(root)}


def fresh(report: dict) -> bool:
    root = report["project_root"]
    return (repo_root(root) == root
            and code_state(root) == report["checked_state"]
            and gate_command(root) == report["command"])


def run(args) -> tuple[dict, int]:
    root = str(Path(args.root).resolve())
    report = {
        "schema_version": 1,
        # nosemgrep: no-ambient-clock-python — observation timestamp only; freshness uses content, never time.
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "project_root": root, "working_directory": root,
        "comparison": {"requested_base": args.base, "base_commit": None,
                       "merge_base": None},
        "command": None, "argv": None, "checked_state": None,
        "execution": {"outcome": "not_run", "exit_code": None},
        "outcome": "incomplete", "freshness": "unknown",
        "analysis_scope": "unknown", "finding_attribution": "unknown",
        "requirements": {"reference": args.task, "assessment": "not_assessed"},
        "receipt": None, "stdout": None, "stderr": None, "report_path": None,
        "error": None,
    }
    directory = None
    try:
        clear_git_environment()
        if repo_root(root) != root:
            raise ValueError("project root must be the root of a Git working tree")
        # Per-worktree metadata is outside the checked source, even in linked
        # worktrees. No ignore entry or host installation is needed.
        metadata = Path(git("rev-parse", "--absolute-git-dir", cwd=root).strip())
        directory = Path(tempfile.mkdtemp(prefix="guardian-", dir=metadata))
        report["report_path"] = str(directory / "result.json")
        report["command"] = gate_command(root)
        if report["command"] is None:
            raise ValueError(f"missing or invalid gate_command in {CONFIG}")
        report["argv"] = list(gate_argv(report["command"]))
        base = git("rev-parse", "--verify", "--end-of-options",
                   args.base + "^{commit}", cwd=root).strip()
        report["comparison"]["base_commit"] = base
        report["comparison"]["merge_base"] = git(
            "merge-base", base, "HEAD", cwd=root).strip()
        report["checked_state"] = code_state(root)
        report["stdout"] = str(directory / "stdout.log")
        report["stderr"] = str(directory / "stderr.log")
        with open(report["stdout"], "wb") as stdout, open(report["stderr"], "wb") as stderr:
            try:
                receipt = recorder.execute_and_record(
                    root, report["argv"], report["command"], cwd=root,
                    stdout=stdout, stderr=stderr)
            except recorder.RecordingError as exc:
                record_execution(report, exc.receipt)
                raise
        report["receipt"] = str(Path(root) / RECEIPT)
        # Use the actual recorder snapshot, not a separately inferred one.
        record_execution(report, receipt)
        rc = receipt["exit_code"]
        report["freshness"] = "current" if fresh(report) else "stale"
        report["outcome"] = ("failed" if rc != 0 else
                             "succeeded" if report["freshness"] == "current" else "stale")
    except (OSError, ValueError, InspectionError, subprocess.CalledProcessError) as exc:
        report["error"] = str(exc)
        report["outcome"] = "incomplete"
    if directory is not None:
        try:
            Path(report["report_path"]).write_text(json.dumps(report, indent=2) + "\n")
        except OSError as exc:
            report["outcome"] = "incomplete"
            report["error"] = f"could not save report: {exc}"
            report["report_path"] = None
    child = report["execution"]["exit_code"]
    return report, child if child else (0 if report["outcome"] == "succeeded" else 3)


def record_execution(report: dict, receipt: dict) -> None:
    report["checked_state"]["fingerprint"] = receipt["fingerprint"]
    rc = receipt["exit_code"]
    report["execution"] = {"outcome": "succeeded" if rc == 0 else "failed",
                           "exit_code": rc}


def check(path: str) -> tuple[dict, int]:
    """Reassess a saved observation; never write or refresh a gate receipt."""
    try:
        clear_git_environment()
        report = json.loads(Path(path).read_text())
        if report["schema_version"] != 1:
            raise ValueError("unsupported result schema version")
        current = fresh(report)
        return {"schema_version": 1, "report_path": path,
                "outcome": report["outcome"],
                "freshness": "current" if current else "stale"}, (
                    0 if current and report["outcome"] == "succeeded" else 3)
    except (OSError, ValueError, KeyError, TypeError, InspectionError,
            subprocess.CalledProcessError) as exc:
        return {"schema_version": 1, "outcome": "incomplete",
                "freshness": "unknown", "error": str(exc)}, 3


def display(report: dict) -> None:
    print(f"Guardian: {report['outcome']} (freshness: {report['freshness']})")
    if "project_root" in report:
        print(f"Project / working directory: {report['project_root']}")
        print(f"Command: {report['command']}")
        print(f"Comparison: {json.dumps(report['comparison'])}")
        print(f"Checked state: {json.dumps(report['checked_state'])}")
        print(f"Execution: {json.dumps(report['execution'])}")
        print("Analysis scope: unknown; finding age: unknown")
        print(f"Requirements: not assessed (reference: {report['requirements']['reference']})")
        print(f"Output: {report['stdout']}\nErrors: {report['stderr']}")
    print(f"Report: {report.get('report_path')}")
    if report.get("error"):
        print(f"Error: {report['error']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    execute = commands.add_parser("run", help="run the project's existing declared gate")
    execute.add_argument("root")
    execute.add_argument("--base", required=True)
    execute.add_argument("--task", help="named task/issue/spec reference; not an assessment")
    inspect = commands.add_parser("check", help="check saved evidence against current content")
    inspect.add_argument("report")
    for command in (execute, inspect):
        command.add_argument("--json", action="store_true", help="print machine-readable evidence")
    args = parser.parse_args()
    report, rc = run(args) if args.action == "run" else check(args.report)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        display(report)
    return rc if rc >= 0 else 128 - rc


if __name__ == "__main__":
    sys.exit(main())
