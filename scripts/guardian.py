#!/usr/bin/env python3
"""Run a declared local gate with versioned evidence, or check its freshness."""

from __future__ import annotations

import argparse
import datetime
import importlib.util
import json
import importlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import guardian_status
import guardian_update

sys.dont_write_bytecode = True
GUARD_DIR = Path(__file__).resolve().parent / "agent-guard"
RECOVERY_GUIDE = (str(Path(__file__).resolve().parent.parent / "docs/GUARDIAN-SETUP.md")
                  + "#recover-an-unavailable-prerequisite")
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
        "next_step": None,
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
    if report["outcome"] in ("failed", "incomplete"):
        report["next_step"] = (
            "Cause unknown: inspect error and the retained stdout/stderr, then the selected "
            "gate and project setup instructions. Establish a prerequisite with explicit "
            "inspection before proposing a PATH or installation change. "
            f"Recovery steps: {RECOVERY_GUIDE}")
    elif report["outcome"] == "stale":
        report["next_step"] = "Checked content changed; rerun the whole declared gate on the final content."
    if directory is not None:
        try:
            Path(report["report_path"]).write_text(json.dumps(report, indent=2) + "\n")
        except OSError as exc:
            report["outcome"] = "incomplete"
            report["error"] = f"could not save report: {exc}"
            report["report_path"] = None
            report["next_step"] = "Resolve the report storage error, then rerun the whole declared gate."
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
    if "installation" in report:
        installation = report["installation"]
        print("Automatic completion: " + json.dumps(report.get("automatic_completion")))
        verification = report["verification"]
        print(f"Guardian status for {report['project_root']} ({report['host']['name']})")
        print(f"Installation: {installation['status']} ({installation['profile']})")
        release = installation.get("release")
        if release:
            print(f"Version: {release['version']} @ {release['commit']}")
        print(f"Host trust: {report['host']['trust']}; observed enforcement: "
              f"{report['host']['observed_enforcement']}")
        print(f"Last regular project check: {verification['outcome']} "
              f"(freshness: {verification['freshness']})")
        if verification.get("command"):
            print(f"Executed command: {verification['command']}")
        for check_result in installation.get("checks", []):
            print(f"{check_result['status']}: {check_result['id']}: {check_result['detail']}")
        return
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
    if report.get("next_step"):
        print(f"Next step: {report['next_step']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    execute = commands.add_parser("run", help="run the project's existing declared gate")
    execute.add_argument("root")
    execute.add_argument("--base", required=True)
    execute.add_argument("--task", help="named task/issue/spec reference; not an assessment")
    inspect = commands.add_parser("check", help="check saved evidence against current content")
    inspect.add_argument("report")
    inspect_status = commands.add_parser("status", help="read installation and saved check status")
    inspect_status.add_argument("root")
    inspect_status.add_argument("--host", choices=("claude", "codex"),
                                help="inspect a host explicitly; otherwise use the selected host")
    inspect_status.add_argument("--json", action="store_true", help="print machine-readable status")
    for command in (execute, inspect):
        command.add_argument("--json", action="store_true", help="print machine-readable evidence")
    setup = commands.add_parser("setup", help="preview local setup or an explicit pinned update")
    setup.add_argument("root")
    setup.add_argument("--apply", action="store_true", help="apply the displayed selection")
    setup.add_argument("--gate", help="explicitly select or replace the whole gate command")
    automatic = setup.add_mutually_exclusive_group()
    automatic.add_argument("--automatic-check", type=int, metavar="SECONDS",
                           help="approve the exact whole gate as check-only for automatic Stop execution (1–40s)")
    automatic.add_argument("--no-automatic-check", action="store_true",
                           help="disable automatic execution, retaining the gate")
    setup.add_argument("--guardian", choices=("claude", "codex"),
                       help="enable the selected host's native Guardian integration")
    setup.add_argument("--version", help="requested immutable release tag")
    setup.add_argument("--commit", help="full commit matching the requested release tag")
    setup.add_argument("--source", default=str(Path(__file__).resolve().parent.parent),
                       help="local baseline checkout containing the requested release; never downloaded")
    setup.add_argument("--base", default="HEAD", help="comparison base for post-update checks")
    setup.add_argument("--task", help="task reference for post-update evidence")
    setup.add_argument("--json", action="store_true")
    lifecycle_commands = {}
    for action in ("pause", "resume", "remove"):
        operation = commands.add_parser(action, help=f"preview or apply selected-host {action}")
        operation.add_argument("root")
        operation.add_argument("--host", choices=("claude", "codex"),
                                help="defaults to the recorded selected host")
        operation.add_argument("--apply", action="store_true",
                               help="apply the displayed changes; default is read-only preview")
        operation.add_argument("--json", action="store_true")
        lifecycle_commands[action] = operation
    switch = commands.add_parser("switch", help="preview or apply an explicit selected-host change")
    switch.add_argument("root")
    switch.add_argument("--host", choices=("claude", "codex"), required=True,
                        help="explicit destination host")
    switch.add_argument("--apply", action="store_true",
                        help="apply the displayed changes; default is read-only preview")
    switch.add_argument("--json", action="store_true")
    lifecycle_commands["switch"] = switch
    handoff = commands.add_parser("handoff", help="end with an explicit unresolved human decision")
    handoff.add_argument("root")
    handoff.add_argument("--reason", required=True, help="open checks, attempts and decision needed")
    handoff.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.action == "handoff":
        try:
            clear_git_environment()
            root = str(Path(args.root).resolve())
            if repo_root(root) != root:
                raise ValueError("target must be a Git working tree root")
            report = recorder.request_handoff(root, args.reason)
        except (OSError, ValueError, InspectionError) as exc:
            print(json.dumps({"outcome": "incomplete", "error": str(exc)}))
            return 3
        print(json.dumps(report, indent=2))
        return 0
    if args.action == "setup":
        report, rc = importlib.import_module("guardian_setup").setup(args, sys.modules[__name__])
        print(json.dumps(report, indent=2))
        return rc if rc >= 0 else 128 - rc
    if args.action == "status":
        report = guardian_status.status(
            args.root, args.host, git=git, check=check,
            clear_git_environment=clear_git_environment,
            runtime=Path(__file__).with_name("quality-runtime.py"))
        try:
            report["automatic_completion"] = recorder.completion_status(str(Path(args.root).resolve()))
        except (OSError, ValueError, InspectionError) as exc:
            report["automatic_completion"] = {"verification": "unverified", "error": str(exc)}
        rc = 0
    elif args.action in lifecycle_commands:
        module_name, function_name = {
            "pause": ("guardian_pause", "pause"),
            "resume": ("guardian_pause", "resume"),
            "remove": ("guardian_remove", "remove"),
            "switch": ("guardian_switch", "switch"),
        }[args.action]
        try:
            clear_git_environment()
            root = str(Path(args.root).resolve())
            if repo_root(root) != root:
                raise ValueError("target must be a Git working tree root")
            metadata = Path(git("rev-parse", "--absolute-git-dir", cwd=root).strip())
            pending = guardian_update.read_pending(metadata)
            if pending:
                raise guardian_update.PendingUpdateError(
                    "a Guardian update is incomplete; run setup --apply to recover before "
                    f"using {args.action}")
            operation = getattr(importlib.import_module(module_name), function_name)
        except (ImportError, AttributeError):
            report, rc = ({"outcome": "unavailable",
                           "error": f"{args.action} is not available in this Guardian release"}, 3)
        except (OSError, ValueError, subprocess.CalledProcessError) as exc:
            report, rc = ({"outcome": "refused", "error": str(exc)}, 3)
        else:
            report, rc = operation(args, sys.modules[__name__])
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            print(json.dumps(report, indent=2))
        return rc if rc >= 0 else 128 - rc
    else:
        report, rc = run(args) if args.action == "run" else check(args.report)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        display(report)
    return rc if rc >= 0 else 128 - rc


if __name__ == "__main__":
    sys.exit(main())
