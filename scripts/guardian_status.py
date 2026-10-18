#!/usr/bin/env python3
"""Compose read-only Guardian installation and saved-check status."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import guardian_lifecycle
import guardian_update


def status(root: str, host: str | None = None, *, git, check,
           clear_git_environment, runtime: Path) -> dict:
    """Read installation diagnosis and the latest saved gate observation."""
    canonical_root = str(Path(root).resolve())
    clear_git_environment()
    requested_host = host
    state_error = None
    if host is None:
        try:
            host = guardian_lifecycle.selected_host(Path(canonical_root))
        except ValueError as exc:
            state_error = str(exc)
            host = "claude"
    diagnosis_proc = subprocess.run(
        [sys.executable, str(runtime), "diagnose", "--root", canonical_root,
         "--host", host, "--json"], cwd=canonical_root, capture_output=True,
        text=True, check=False)
    try:
        diagnosis = json.loads(diagnosis_proc.stdout)
    except (json.JSONDecodeError, TypeError):
        diagnosis = {"status": "unavailable", "healthy": False,
                     "installation_profile": "unknown", "release": None,
                     "configured_gate": None, "checks": [],
                     "live_enforcement": "unverified", "host_settings": "unverified",
                     "diagnosis_error": diagnosis_proc.stderr.strip() or
                     "runtime diagnosis returned no JSON"}
    try:
        diagnosis = guardian_lifecycle.status_overlay(
            Path(canonical_root), diagnosis, requested_host or host)
    except ValueError as exc:
        state_error = str(exc)

    metadata = Path(git("rev-parse", "--absolute-git-dir", cwd=canonical_root).strip())
    reports: list[tuple[dict, Path]] = []
    for path in metadata.glob("guardian-*/result.json"):
        try:
            candidate = json.loads(path.read_text(encoding="utf-8"))
            if candidate.get("project_root") == canonical_root:
                reports.append((candidate, path))
        except (OSError, ValueError, AttributeError):
            continue
    latest_pair = max(reports, key=lambda item: item[0].get("created_at", ""), default=None)
    if latest_pair is None:
        verification = {"outcome": "not_run", "freshness": "unknown",
                        "execution": {"outcome": "not_run", "exit_code": None},
                        "command": None, "observed_at": None, "report_path": None}
    else:
        latest, report_path = latest_pair
        freshness, _ = check(str(report_path))
        execution = latest.get("execution", {})
        outcome = latest.get("outcome", "incomplete")
        if outcome == "incomplete" and execution.get("outcome") == "not_run":
            outcome = "not_executable"
        verification = {
            "outcome": outcome,
            "freshness": freshness.get("freshness", "unknown"),
            "execution": execution,
            "command": latest.get("command"),
            "observed_at": latest.get("created_at"),
            "report_path": latest.get("report_path"),
        }
    pending_update = guardian_update.read_pending(metadata)
    if pending_update:
        version = pending_update.get("requested_version") or {}
        verification = {
            **verification,
            "outcome": "incomplete",
            "freshness": "unknown",
            "pending_update": {
                "status": "recovery_conflict" if pending_update.get("recovery_conflicts") else "incomplete",
                "current_version": (pending_update.get("current_version") or {}).get("version"),
                "requested_version": version.get("version"),
                "host": pending_update.get("host"),
                "conflicts": pending_update.get("recovery_conflicts", []),
            },
        }
        diagnosis = {**diagnosis, "status": "update_pending", "healthy": False,
                     "lifecycle": "update_pending", "live_enforcement": "unverified"}
    return {
        "schema_version": 1,
        "project_root": canonical_root,
        "host": {"name": host, "trust": "unverified",
                 "observed_enforcement": diagnosis.get("live_enforcement", "unverified")},
        "selection": {"host": host, "source": "explicit" if requested_host else
                       guardian_lifecycle.selection_source(Path(canonical_root)),
                       "error": state_error},
        "installation": {"status": diagnosis.get("status", "unavailable"),
                         "profile": diagnosis.get("installation_profile", "unknown"),
                         "lifecycle": diagnosis.get("lifecycle", "unknown"),
                         "selected_lifecycle": diagnosis.get("selected_lifecycle"),
                         "selected_host": diagnosis.get("selected_host"),
                         "release": diagnosis.get("release"),
                         "configured_gate": diagnosis.get("configured_gate"),
                         "checks": diagnosis.get("checks", []),
                         "error": diagnosis.get("diagnosis_error")},
        "verification": verification,
        "pending_update": (verification.get("pending_update") if pending_update else None),
    }
