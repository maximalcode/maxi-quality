#!/usr/bin/env python3
"""Collect whole-workflow scope without changing an analysis verdict.

The helper has two small public boundaries. ``init`` records discovery and the
run identity, while ``fragment`` records an execution on the runner that saw
it. ``collect`` joins only fragments for that exact invocation and attempt.
Missing fragments are represented as unknown evidence; they are never treated
as a skipped job or as a zero measurement.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import pathlib
import re
import sys
from typing import Any


SCHEMA_VERSION = 1
LANGUAGES = ("ts", "dotnet", "python", "rust", "java")
LANGUAGE_NAMES = {
    "ts": "TypeScript",
    "dotnet": ".NET",
    "python": "Python",
    "rust": "Rust",
    "java": "Java",
}
JOB_NAMES = {"ts": "typescript", "dotnet": "dotnet", "python": "python", "rust": "rust", "java": "java"}
MARKERS = {
    "ts": ("package.json",),
    "dotnet": ("*.sln", "*.slnx", "*.csproj"),
    "python": ("uv.lock", "poetry.lock", "pyproject.toml", "requirements.txt", "requirements-dev.txt"),
    "rust": ("Cargo.toml",),
    "java": ("pom.xml", "build.gradle", "build.gradle.kts"),
}
PRUNE = {
    "ts": {"node_modules"},
    "dotnet": {"node_modules"},
    "python": {"node_modules", ".venv", ".git"},
    "rust": {"node_modules", "target", ".git", ".venv"},
    "java": {"node_modules", "target", ".git", ".venv", "build"},
}
SUMMARY_LINE_LIMIT = 240
SUMMARY_MAX_LINES = 200
VALID_STATES = {"run", "skipped", "not_applicable", "unknown"}
VALID_OUTCOMES = {"success", "failure", "cancelled", "unknown"}
VALID_MEASUREMENT_STATES = {"known", "unknown", "not_applicable"}
TOOL_MEASUREMENTS = ("examined", "unparsed", "policy_excluded")


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read(path: pathlib.Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read workflow scope {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"unsupported workflow scope contract in {path}")
    kind = value.get("kind")
    if value.get("schema_version") != SCHEMA_VERSION or not isinstance(kind, str) or kind not in {"workflow-scope", "workflow-scope-fragment"}:
        raise ValueError(f"unsupported workflow scope contract in {path}")
    if not isinstance(value.get("identity"), dict):
        raise ValueError(f"workflow scope identity is not an object in {path}")
    if kind == "workflow-scope" and not isinstance(value.get("expected_jobs", []), list):
        raise ValueError(f"workflow scope expected_jobs is not a list in {path}")
    if kind == "workflow-scope":
        if any(not isinstance(item, dict) or not isinstance(item.get("logical_job"), str) or not isinstance(item.get("leg", ""), str) for item in value.get("expected_jobs", [])):
            raise ValueError(f"workflow scope expected_jobs contains a malformed job in {path}")
    if kind == "workflow-scope-fragment":
        identity = value["identity"]
        required = ("producer", "workflow", "invocation_id", "run_id", "run_attempt", "logical_job", "leg")
        if any(field not in identity for field in required):
            raise ValueError(f"workflow scope fragment identity is incomplete in {path}")
        if any(not isinstance(identity[field], str) for field in required):
            raise ValueError(f"workflow scope fragment identity contains a non-string field in {path}")
        if not isinstance(value.get("state"), str) or value.get("state") not in VALID_STATES:
            raise ValueError(f"workflow scope fragment state is invalid in {path}")
        if not isinstance(value.get("outcome"), str) or value.get("outcome") not in VALID_OUTCOMES:
            raise ValueError(f"workflow scope fragment outcome is invalid in {path}")
        normalize_fragment_containers(value, path)
    return value


def write(path: pathlib.Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def discover(root: pathlib.Path) -> dict[str, dict[str, Any]]:
    """Observe supported project markers, independent of selection."""
    if not root.is_dir():
        reason = f"discovery root is not a directory: {root}"
        return {language: {"state": "unknown", "markers": [], "reason": reason} for language in LANGUAGES}
    observed: dict[str, dict[str, Any]] = {}
    for language, patterns in MARKERS.items():
        paths: list[str] = []
        errors: list[str] = []

        def onerror(error: OSError) -> None:
            errors.append(str(error))

        for directory, dirs, files in os.walk(root, onerror=onerror):
            dirs[:] = sorted(name for name in dirs if name not in PRUNE[language])
            relative = pathlib.Path(directory).relative_to(root)
            for pattern in patterns:
                for filename in files:
                    if pathlib.PurePath(filename).match(pattern):
                        path = (relative / filename).as_posix()
                        if path == ".":
                            path = filename
                        paths.append(path)
        entry: dict[str, Any] = {"state": "present" if paths else "absent", "markers": sorted(set(paths))}
        if errors:
            entry["discovery_errors"] = errors
            if not paths:
                entry["state"] = "unknown"
        observed[language] = entry
    return observed


def selected(value: str, language: str) -> bool:
    if value == "none":
        return False
    return value == "auto" or language in {part for part in value.split(",") if part}


def measurement(status: str = "unknown", reason: str = "job scope is not instrumented") -> dict[str, Any]:
    return {"status": status, "count": None, "unit": "source_path", "method": "not available at workflow boundary", "reason": reason}


def unknown_measurements(reason: str = "job scope is not instrumented") -> dict[str, Any]:
    return {name: measurement(reason=reason) for name in ("examined", "unparsed", "policy_excluded")}


def validate_tool_record(record: dict[str, Any]) -> list[str]:
    """Return semantic contract violations for one JSON tool record."""
    issues: list[str] = []
    required = ("name", "command", "working_directory", "state", "outcome", "reason", "reason_code", "exit_code", "diagnostics", "measurements")
    issues.extend(f"missing {field}" for field in required if field not in record)
    if "name" in record and (not isinstance(record["name"], str) or not record["name"]):
        issues.append("name must be a non-empty string")
    if "command" in record and (not isinstance(record["command"], list) or not all(isinstance(value, str) for value in record["command"])):
        issues.append("command must be a list of strings")
    if "working_directory" in record and record["working_directory"] is not None and not isinstance(record["working_directory"], str):
        issues.append("working_directory must be a string or null")
    if "state" in record and (not isinstance(record["state"], str) or record["state"] not in VALID_STATES):
        issues.append(f"state must be one of {sorted(VALID_STATES)}")
    if "outcome" in record and (not isinstance(record["outcome"], str) or record["outcome"] not in VALID_OUTCOMES):
        issues.append(f"outcome must be one of {sorted(VALID_OUTCOMES)}")
    if "reason" in record and not isinstance(record["reason"], str):
        issues.append("reason must be a string")
    if "reason_code" in record and record["reason_code"] is not None and not isinstance(record["reason_code"], str):
        issues.append("reason_code must be a string or null")
    exit_code = record.get("exit_code")
    if exit_code is not None and (isinstance(exit_code, bool) or not isinstance(exit_code, int) or not 0 <= exit_code <= 255):
        issues.append("exit_code must be an integer from 0 through 255 or null")
    if "diagnostics" in record and (not isinstance(record["diagnostics"], list) or not all(isinstance(value, str) for value in record["diagnostics"])):
        issues.append("diagnostics must be a list of strings")
    measurements = record.get("measurements")
    if not isinstance(measurements, dict):
        issues.append("measurements must be an object")
    else:
        for name in TOOL_MEASUREMENTS:
            value = measurements.get(name)
            if not isinstance(value, dict):
                issues.append(f"measurement {name} must be an object")
                continue
            for field in ("status", "count", "unit", "method", "reason"):
                if field not in value:
                    issues.append(f"measurement {name} is missing {field}")
            status = value.get("status")
            if not isinstance(status, str) or status not in VALID_MEASUREMENT_STATES:
                issues.append(f"measurement {name} status is invalid")
            count = value.get("count")
            if count is not None and (isinstance(count, bool) or not isinstance(count, int) or count < 0):
                issues.append(f"measurement {name} count must be a non-negative integer or null")
            if status == "known" and count is None:
                issues.append(f"measurement {name} known status requires a numeric count")
            if isinstance(status, str) and status in {"unknown", "not_applicable"} and count is not None:
                issues.append(f"measurement {name} {status} status requires a null count")
            for field in ("unit", "method", "reason"):
                if field in value and not isinstance(value[field], str):
                    issues.append(f"measurement {name} {field} must be a string")
    collection = record.get("collection")
    if collection is not None:
        if not isinstance(collection, dict):
            issues.append("collection must be an object")
        else:
            collection_status = collection.get("status")
            if not isinstance(collection_status, str) or collection_status not in {"complete", "partial", "unknown"}:
                issues.append("collection status is invalid")
            if not isinstance(collection.get("issues"), list) or not all(isinstance(value, str) for value in collection["issues"]):
                issues.append("collection issues must be a list of strings")
    return issues


def _unknown_tool_record(name: str, issue: str) -> dict[str, Any]:
    return {
        "name": name,
        "command": [],
        "working_directory": None,
        "state": "unknown",
        "outcome": "unknown",
        "reason": "execution is unknown because the tool record is invalid",
        "reason_code": "invalid_tool_record",
        "exit_code": None,
        "diagnostics": [],
        "measurements": unknown_measurements("tool record was semantically invalid"),
        "collection": {"status": "partial", "issues": [issue]},
    }


def _normalize_rust_scope(value: object, tool_name: str) -> tuple[dict[str, Any] | None, list[str]]:
    if not isinstance(value, dict):
        return None, [f"invalid Rust scope for {tool_name}: expected an object"]
    result = dict(value)
    issues: list[str] = []
    requested = result.get("requested")
    if not isinstance(requested, dict):
        result["requested"] = {}
        issues.append(f"invalid Rust requested scope for {tool_name}")
    observed = result.get("observed")
    if not isinstance(observed, dict):
        result["observed"] = {"artifacts": []}
        issues.append(f"invalid Rust observed scope for {tool_name}")
        rust_collection = result.get("collection")
        if isinstance(rust_collection, dict):
            collection_issues = rust_collection.get("issues", [])
            if not isinstance(collection_issues, list) or not all(isinstance(item, str) for item in collection_issues):
                result["collection"] = {"status": "partial", "issues": []}
                issues.append(f"invalid Rust collection issues for {tool_name}")
        elif rust_collection is not None:
            result["collection"] = {"status": "partial", "issues": [f"invalid Rust collection for {tool_name}"]}
            issues.append(f"invalid Rust collection for {tool_name}")
        return result, issues
    observed_result = dict(observed)
    artifacts = observed_result.get("artifacts", [])
    if not isinstance(artifacts, list):
        observed_result["artifacts"] = []
        issues.append(f"invalid Rust artifacts for {tool_name}")
    else:
        safe_artifacts: list[dict[str, Any]] = []
        for index, artifact in enumerate(artifacts):
            if not isinstance(artifact, dict):
                issues.append(f"invalid Rust artifact {index} for {tool_name}")
                continue
            safe_artifact = dict(artifact)
            if not isinstance(safe_artifact.get("target", {}), dict):
                safe_artifact["target"] = {}
                issues.append(f"invalid Rust target for artifact {index} of {tool_name}")
            safe_artifacts.append(safe_artifact)
        observed_result["artifacts"] = safe_artifacts
    platform = observed_result.get("platform", {})
    if not isinstance(platform, dict):
        observed_result["platform"] = {}
        issues.append(f"invalid Rust platform for {tool_name}")
    compiler_messages = observed_result.get("compiler_messages", [])
    if not isinstance(compiler_messages, list):
        observed_result["compiler_messages"] = []
        issues.append(f"invalid Rust compiler messages for {tool_name}")
    finished = observed_result.get("build_finished")
    if finished is not None and not isinstance(finished, dict):
        observed_result["build_finished"] = None
        issues.append(f"invalid Rust completion for {tool_name}")
    rust_collection = result.get("collection")
    if rust_collection is not None:
        if not isinstance(rust_collection, dict):
            result["collection"] = {"status": "partial", "issues": [f"invalid Rust collection for {tool_name}"]}
            issues.append(f"invalid Rust collection for {tool_name}")
        else:
            safe_collection = dict(rust_collection)
            collection_issues = safe_collection.get("issues", [])
            collection_status = safe_collection.get("status", "partial")
            if not isinstance(collection_status, str) or collection_status not in {"complete", "partial", "unknown"} or not isinstance(collection_issues, list) or not all(isinstance(item, str) for item in collection_issues):
                safe_collection["status"] = "partial"
                safe_collection["issues"] = []
                result["collection"] = safe_collection
                issues.append(f"invalid Rust collection issues for {tool_name}")
    result["observed"] = observed_result
    return result, issues


def _normalize_tool_records(value: object) -> tuple[list[dict[str, Any]], str | None]:
    records: list[dict[str, Any]] = []
    issues: list[str] = []
    if not isinstance(value, list):
        return [], "tools container is not a list"
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            issue = f"invalid tool record {index}: expected an object"
            issues.append(issue)
            records.append(_unknown_tool_record(f"unknown-tool-{index}", issue))
            continue
        violations = validate_tool_record(item)
        if not violations:
            normalized = dict(item)
            rust_issues: list[str] = []
            if "rust" in normalized:
                normalized["rust"], rust_issues = _normalize_rust_scope(normalized["rust"], str(normalized.get("name", "unknown")))
            if rust_issues:
                issue = "; ".join(rust_issues)
                issues.append(issue)
                collection = normalized.get("collection")
                if not isinstance(collection, dict):
                    collection = {"status": "partial", "issues": []}
                collection["status"] = "partial"
                collection["issues"] = [item for item in collection.get("issues", []) if isinstance(item, str)] + rust_issues
                normalized["collection"] = collection
            records.append(normalized)
            continue
        name = item.get("name") if isinstance(item.get("name"), str) and item.get("name") else f"unknown-tool-{index}"
        issue = f"invalid tool record {name}: {'; '.join(violations)}"
        issues.append(issue)
        records.append(_unknown_tool_record(name, issue))
    return records, "; ".join(issues) if issues else None


def normalize_fragment_containers(value: dict[str, Any], path: pathlib.Path) -> None:
    """Degrade malformed optional fragment fields without losing the leg."""
    issues: list[str] = []
    diagnostics = value.get("diagnostics")
    if "diagnostics" in value and (not isinstance(diagnostics, list) or not all(isinstance(item, str) for item in diagnostics)):
        value["diagnostics"] = []
        issues.append("fragment diagnostics container is malformed")
    if "tools" in value:
        tools, tools_issue = _normalize_tool_records(value["tools"])
        value["tools"] = tools
        if tools_issue:
            issues.append(tools_issue)
    else:
        value["tools"] = []
    tool_collection = value.get("tool_collection")
    if "tool_collection" not in value:
        tool_collection = {"status": "unknown", "issues": []}
    elif not isinstance(tool_collection, dict):
        tool_collection = {"status": "partial", "issues": ["fragment tool_collection container is malformed"]}
    else:
        tool_collection = dict(tool_collection)
        status = tool_collection.get("status")
        collection_issues = tool_collection.get("issues")
        if not isinstance(status, str) or status not in {"complete", "partial", "unknown"}:
            tool_collection["status"] = "partial"
            issues.append("fragment tool_collection status is malformed")
        if not isinstance(collection_issues, list) or not all(isinstance(item, str) for item in collection_issues):
            tool_collection["issues"] = []
            issues.append("fragment tool_collection issues are malformed")
    if issues:
        tool_collection["status"] = "partial"
        tool_collection["issues"] = [item for item in tool_collection.get("issues", []) if isinstance(item, str)] + issues
    value["tool_collection"] = tool_collection


def read_tools(path: pathlib.Path) -> tuple[list[dict[str, Any]], str | None]:
    """Read command records and preserve missing/malformed evidence as an issue."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        return [], f"tool record file unavailable: {path}: {exc}"
    except json.JSONDecodeError as exc:
        return [], f"malformed tool record file {path}: {exc}"
    if not isinstance(value, list):
        return [], f"malformed tool record file {path}: expected a list of objects"
    return _normalize_tool_records(value)


def _rust_target_from_config(working_directory: str | None) -> tuple[str | None, str | None]:
    """Read Cargo's effective target declaration when the command exposed it."""
    if not working_directory:
        return None, None
    directory = pathlib.Path(working_directory)
    if not directory.is_dir():
        return None, None
    for base in (directory, *directory.parents):
        for filename in ("config.toml", "config"):
            path = base / ".cargo" / filename
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            in_build = False
            for line in text.splitlines():
                section = re.match(r"\s*\[([^]]+)\]\s*$", line)
                if section:
                    in_build = section.group(1).strip() == "build"
                    continue
                if in_build:
                    match = re.match(r"\s*target\s*=\s*[\"']([^\"']+)[\"']", line)
                    if match:
                        return match.group(1), str(path)
    return None, None


def _rust_requested(argv: list[str], working_directory: str | None) -> dict[str, Any]:
    """Describe requested Cargo configuration without claiming it executed."""
    try:
        cargo_index = argv.index("cargo")
    except ValueError:
        cargo_index = 0
    cargo_args = argv[cargo_index + 1 :]
    cli_target = None
    for index, value in enumerate(cargo_args):
        if value == "--target" and index + 1 < len(cargo_args):
            cli_target = cargo_args[index + 1]
        elif value.startswith("--target="):
            cli_target = value.split("=", 1)[1]
    features: list[str] = []
    for index, value in enumerate(cargo_args):
        if value == "--features" and index + 1 < len(cargo_args):
            features.extend(part for part in cargo_args[index + 1].split(",") if part)
        elif value.startswith("--features="):
            features.extend(part for part in value.split("=", 1)[1].split(",") if part)
    config_target, config_path = _rust_target_from_config(working_directory)
    env_target = os.environ.get("CARGO_BUILD_TARGET") or None
    platform_target = cli_target or env_target or config_target
    platform_source = "cli" if cli_target else "environment" if env_target else "cargo-config" if config_target else "unavailable"
    platform_reason = (
        "effective target requested by the cargo command"
        if cli_target
        else "effective target requested by CARGO_BUILD_TARGET"
        if env_target
        else f"effective target declared by {config_path}"
        if config_path
        else "Cargo compiler-artifact messages do not include a platform triple and no target override was observed"
    )
    return {
        "workspace": "--workspace" in cargo_args,
        "all_targets": "--all-targets" in cargo_args,
        "locked": "--locked" in cargo_args,
        "warnings": next((value.split("=", 1)[1] for value in argv[:cargo_index] if value.startswith("RUSTFLAGS=")), None),
        "features": features,
        "feature_selection": "explicit" if features or "--all-features" in cargo_args else "default",
        "target": {"cli": cli_target, "env": env_target, "config": config_target},
        "platform": {
            "status": "known" if platform_target else "unknown",
            "target": platform_target,
            "source": platform_source,
            "reason": platform_reason,
        },
    }


def _rust_artifact(value: dict[str, Any]) -> dict[str, Any]:
    target = value.get("target") if isinstance(value.get("target"), dict) else {}
    profile = value.get("profile") if isinstance(value.get("profile"), dict) else {}
    fresh = value.get("fresh") if isinstance(value.get("fresh"), bool) else None
    return {
        "package_id": value.get("package_id") if isinstance(value.get("package_id"), str) else None,
        "manifest_path": value.get("manifest_path") if isinstance(value.get("manifest_path"), str) else None,
        "target": {
            "kind": target.get("kind") if isinstance(target.get("kind"), list) else [],
            "name": target.get("name") if isinstance(target.get("name"), str) else None,
            "required_features": target.get("required-features") if isinstance(target.get("required-features"), list) else None,
            "crate_types": target.get("crate_types") if isinstance(target.get("crate_types"), list) else [],
            "src_path": target.get("src_path") if isinstance(target.get("src_path"), str) else None,
        },
        "features": value.get("features") if isinstance(value.get("features"), list) else [],
        "profile": {
            "test": profile.get("test") if isinstance(profile.get("test"), bool) else None,
            "opt_level": profile.get("opt_level") if isinstance(profile.get("opt_level"), str) else None,
            "debuginfo": profile.get("debuginfo"),
            "debug_assertions": profile.get("debug_assertions") if isinstance(profile.get("debug_assertions"), bool) else None,
            "overflow_checks": profile.get("overflow_checks") if isinstance(profile.get("overflow_checks"), bool) else None,
        },
        "filenames": value.get("filenames") if isinstance(value.get("filenames"), list) else [],
        "fresh": fresh,
        "freshness": "fresh" if fresh is True else "processed" if fresh is False else "unknown",
    }


def _rust_platform_from_artifacts(
    artifacts: list[dict[str, Any]], working_directory: str | None, requested: dict[str, Any]
) -> dict[str, Any] | None:
    """Use an explicit target-directory path as platform evidence when available."""
    requested_target = requested.get("target") if isinstance(requested.get("target"), str) else None
    if requested.get("status") != "known" or not requested_target or not working_directory:
        return None
    target_root = pathlib.Path(os.environ.get("CARGO_TARGET_DIR", pathlib.Path(working_directory) / "target"))
    if not target_root.is_absolute():
        target_root = pathlib.Path(working_directory) / target_root
    try:
        target_root = target_root.resolve()
    except OSError:
        return None
    candidates: list[str] = []
    for artifact in artifacts:
        for filename in artifact.get("filenames", []):
            if not isinstance(filename, str):
                continue
            try:
                relative = pathlib.Path(filename).resolve().relative_to(target_root)
            except (OSError, ValueError):
                continue
            parts = relative.parts
            if len(parts) >= 3 and parts[0] not in {"debug", "release"} and parts[1] in {"debug", "release"}:
                candidates.append(parts[0])
            else:
                return None
    if candidates and all(candidate == requested_target for candidate in candidates):
        return {
            "status": "known",
            "target": requested_target,
            "source": "artifact-path",
            "reason": "Cargo compiler-artifact filenames contain the requested platform component under the default target root",
        }
    return None


def rust_evidence(path: pathlib.Path, argv: list[str], working_directory: str | None) -> tuple[dict[str, Any], list[str]]:
    """Extract Cargo JSON evidence from the completed Clippy capture."""
    requested = _rust_requested(argv, working_directory)
    evidence: dict[str, Any] = {
        "format": "cargo-json",
        "requested": requested,
        "observed": {
            "artifacts": [],
            "compiler_messages": [],
            "build_finished": None,
            "platform": {
                "status": "unknown",
                "target": None,
                "source": "unavailable",
                "reason": "no completed compiler artifact has established an effective platform target",
            },
            "unparsed_lines": 0,
        },
        "collection": {"status": "complete", "issues": []},
    }
    issues: list[str] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        reason = f"Rust structured output unavailable: {path}: {exc}"
        evidence["collection"] = {"status": "partial", "issues": [reason]}
        evidence["observed"]["reason"] = reason
        return evidence, [reason]
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            evidence["observed"]["unparsed_lines"] += 1
            continue
        if not isinstance(value, dict):
            evidence["observed"]["unparsed_lines"] += 1
            continue
        reason = value.get("reason")
        if reason == "compiler-artifact":
            evidence["observed"]["artifacts"].append(_rust_artifact(value))
        elif reason == "compiler-message":
            message = value.get("message") if isinstance(value.get("message"), dict) else {}
            target = value.get("target") if isinstance(value.get("target"), dict) else message.get("target") if isinstance(message.get("target"), dict) else {}
            evidence["observed"]["compiler_messages"].append({
                "package_id": value.get("package_id") if isinstance(value.get("package_id"), str) else None,
                "manifest_path": value.get("manifest_path") if isinstance(value.get("manifest_path"), str) else None,
                "target": {
                    "kind": target.get("kind") if isinstance(target.get("kind"), list) else [],
                    "name": target.get("name") if isinstance(target.get("name"), str) else None,
                },
                "level": message.get("level") if isinstance(message.get("level"), str) else None,
                "message": message.get("message") if isinstance(message.get("message"), str) else None,
                "rendered": message.get("rendered") if isinstance(message.get("rendered"), str) else None,
            })
        elif reason == "build-finished":
            success = value.get("success")
            if isinstance(success, bool):
                evidence["observed"]["build_finished"] = {"success": success}
            else:
                issues.append(f"invalid Cargo build-finished success at line {line_number}")
    if not evidence["observed"]["artifacts"] and evidence["observed"]["build_finished"] is None:
        issues.append("Cargo JSON contained no compiler-artifact or build-finished evidence")
    platform = _rust_platform_from_artifacts(evidence["observed"]["artifacts"], working_directory, requested["platform"])
    if platform:
        evidence["observed"]["platform"] = platform
    if issues:
        evidence["collection"] = {"status": "partial", "issues": issues}
    return evidence, issues


def tool_record(args: argparse.Namespace) -> None:
    """Append one command-boundary record without owning the command verdict."""
    path = pathlib.Path(args.file)
    existing_issue = None
    if path.exists():
        records, existing_issue = read_tools(path)
    else:
        records = []
    diagnostics = list(args.diagnostic or [])
    if args.diagnostic_file:
        try:
            diagnostics.append(pathlib.Path(args.diagnostic_file).read_text(encoding="utf-8", errors="replace"))
        except OSError as exc:
            diagnostics.append(f"cannot read diagnostic file {args.diagnostic_file}: {exc}")
    try:
        exit_code = int(args.exit_code) if args.exit_code != "" else None
    except ValueError:
        exit_code = None
    record: dict[str, Any] = {
        "name": args.name,
        "command": list(args.argv or []),
        "working_directory": args.working_directory or None,
        "state": args.state,
        "outcome": args.outcome,
        "reason": args.reason,
        "reason_code": args.reason_code or None,
        "exit_code": exit_code,
        "diagnostics": diagnostics,
        "measurements": unknown_measurements("measurement is not available at this command boundary"),
    }
    collection_issues = [issue for issue in (existing_issue, args.collection_issue) if issue]
    if args.rust_evidence_file:
        rust, rust_issues = rust_evidence(pathlib.Path(args.rust_evidence_file), list(args.argv or []), args.working_directory or None)
        record["rust"] = rust
        collection_issues.extend(rust_issues)
        if args.rust_render_diagnostics:
            for message in rust["observed"]["compiler_messages"]:
                rendered = message.get("rendered")
                if isinstance(rendered, str) and rendered:
                    print(rendered, file=sys.stderr, end="" if rendered.endswith("\n") else "\n")
    if collection_issues:
        record["collection"] = {"status": "partial", "issues": collection_issues}
    records.append(record)
    write(path, records)


def parse_step_outcomes(raw: str) -> dict[str, str]:
    if not raw:
        return {}
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(decoded, dict):
        return {}
    result: dict[str, str] = {}
    for name, value in decoded.items():
        if isinstance(value, dict) and isinstance(value.get("outcome"), str):
            result[str(name)] = value["outcome"]
        elif isinstance(value, str):
            result[str(name)] = value
    return result


def expected_tool_record(
    spec: str,
    dead_code_mode: str,
    blocked: bool = False,
    step_outcomes: dict[str, str] | None = None,
) -> dict[str, Any]:
    bits = spec.split("|", 6)
    name = bits[0]
    state = bits[1] if len(bits) > 1 and bits[1] else "unknown"
    outcome = bits[2] if len(bits) > 2 and bits[2] else "unknown"
    reason_code = bits[3] if len(bits) > 3 and bits[3] else "missing_tool_record"
    reason = bits[4] if len(bits) > 4 and bits[4] else "command execution is unknown because no boundary record was received"
    owner_steps = [value for value in bits[5].split(",") if value] if len(bits) > 5 else []
    prerequisite_steps = [value for value in bits[6].split(",") if value] if len(bits) > 6 else []
    observed_steps = step_outcomes or {}
    analysis_skipped = bool(owner_steps) and all(observed_steps.get(step) == "skipped" for step in owner_steps)
    failed_prerequisites = [step for step in prerequisite_steps if observed_steps.get(step) == "failure"]
    if blocked:
        state, outcome, reason_code, reason = "skipped", "unknown", "blocked", "command was prevented by an earlier recorded failure"
    elif analysis_skipped and failed_prerequisites:
        state, outcome, reason_code = "skipped", "unknown", "prerequisite_failure"
        reason = f"{reason}; prerequisite step {', '.join(failed_prerequisites)} failed"
    elif reason_code == "opaque":
        # Known nested analyzers stay readable without pretending that the
        # enclosing build proved their execution. Their identity and opaque
        # boundary reason are part of the expected-tool contract.
        state = state or "unknown"
        outcome = outcome or "unknown"
        reason_code = "opaque"
        reason = reason or "execution is nested inside an opaque build command"
    else:
        state, outcome, reason_code, reason = "unknown", "unknown", "missing_tool_record", "command execution is unknown because no boundary record was received"
    if dead_code_mode == "off" and name in {"knip", "deptry"}:
        state, outcome, reason_code, reason = "skipped", "success", "disabled", "dead-code check is disabled"
    return {
        "name": name,
        "command": [],
        "working_directory": None,
        "state": state,
        "outcome": outcome,
        "reason": reason,
        "reason_code": reason_code,
        "exit_code": None,
        "diagnostics": [],
        "measurements": unknown_measurements("command boundary was not reached"),
    }


def expected_jobs(args: argparse.Namespace) -> list[dict[str, str]]:
    values = list(args.expected_job or [])
    if args.expected_jobs_json:
        try:
            decoded = json.loads(args.expected_jobs_json)
        except json.JSONDecodeError as exc:
            raise ValueError(f"expected jobs are not JSON: {exc}") from exc
        if not isinstance(decoded, list):
            raise ValueError("expected jobs JSON must be a list")
        values.extend(str(item) if isinstance(item, str) else f"{item['logical_job']}|{item.get('language', '')}|{item.get('leg', '')}" for item in decoded)
    result = []
    seen: set[str] = set()
    for value in values:
        bits = value.split("|", 2)
        if len(bits) != 3 or not bits[0]:
            raise ValueError(f"expected job must be logical_job|language|leg: {value!r}")
        key = f"{bits[0]}|{bits[2]}"
        if key in seen:
            continue
        seen.add(key)
        result.append({"logical_job": bits[0], "language": bits[1], "leg": bits[2]})
    return result


def needs_outcomes(args: argparse.Namespace) -> dict[str, str]:
    if not args.job_outcomes_json:
        return {}
    try:
        decoded = json.loads(args.job_outcomes_json)
    except json.JSONDecodeError:
        return {}
    if not isinstance(decoded, dict):
        return {}
    return {
        str(name): str(value.get("result", ""))
        for name, value in decoded.items()
        if isinstance(value, dict) and value.get("result")
    }


def missing_job(args: argparse.Namespace, item: dict[str, Any], reason: str = "no fragment for this current attempt; execution is unknown") -> dict[str, Any]:
    outcome = needs_outcomes(args).get(item["logical_job"], "")
    if outcome == "skipped":
        return {
            **item,
            "state": "skipped",
            "outcome": "unknown",
            "reason": "needs result proves this job was skipped",
            "reason_code": "dependency_skipped",
            "measurements": unknown_measurements("job was skipped; no analysis was attempted"),
            "examined": measurement(reason="job was skipped; no analysis was attempted"),
        }
    return {
        **item,
        "state": item.get("expected_state", "unknown"),
        "outcome": "unknown",
        "reason": item.get("expected_reason", reason),
        "reason_code": item.get("expected_reason_code", "missing_fragment"),
        "measurements": unknown_measurements("missing current-attempt fragment; no zero inferred"),
        "examined": measurement(reason="missing current-attempt fragment; no zero inferred"),
    }


def build_document(args: argparse.Namespace, observe_presence: bool = True) -> dict[str, Any]:
    root = pathlib.Path(args.root).resolve()
    if observe_presence:
        presence = discover(root)
    else:
        presence = {language: {"state": "unknown", "markers": [], "reason": "current-attempt manifest unavailable; presence was not observed"} for language in LANGUAGES}
    languages: dict[str, Any] = {}
    for language in LANGUAGES:
        observed = presence[language]
        if observed["state"] == "unknown":
            languages[language] = {"state": "unknown", "selected": selected(args.languages, language), "reason_code": "discovery_failed"}
        elif observed["state"] == "absent":
            languages[language] = {"state": "not_applicable", "selected": selected(args.languages, language), "reason_code": "absent"}
        elif selected(args.languages, language):
            languages[language] = {"state": "selected", "selected": True, "reason_code": "selected"}
        else:
            languages[language] = {"state": "skipped", "selected": False, "reason_code": "deselected"}
    expected = expected_jobs(args)
    expected_keys = {f"{item['logical_job']}|{item.get('leg', '')}" for item in expected}
    for language in LANGUAGES:
        observed = presence[language]
        key = f"{language}|"
        if key in expected_keys or any(item.get("language") == language for item in expected):
            continue
        logical_job = JOB_NAMES[language]
        if observed["state"] == "absent":
            expected.append({"logical_job": logical_job, "language": language, "leg": "", "expected_state": "not_applicable", "expected_reason": "language marker absent"})
        elif observed["state"] == "present" and not selected(args.languages, language):
            expected.append({"logical_job": logical_job, "language": language, "leg": "", "expected_state": "skipped", "expected_reason": "language present but deselected", "expected_reason_code": "deselected"})
        elif observed["state"] == "unknown":
            expected.append({"logical_job": logical_job, "language": language, "leg": "", "expected_state": "unknown", "expected_reason": "language discovery incomplete"})
        elif observed["state"] == "present":
            expected.append({"logical_job": logical_job, "language": language, "leg": "", "expected_state": "unknown", "expected_reason": "selected language has no current target list"})
    if args.coverage_state in {"not_applicable", "selected"} and not any(item["logical_job"] == "coverage" for item in expected):
        expected.append({
            "logical_job": "coverage", "language": "", "leg": "",
            "expected_state": "not_applicable" if args.coverage_state == "not_applicable" else "unknown",
            "expected_reason": "coverage is disabled" if args.coverage_state == "not_applicable" else "coverage state was not provided",
        })
    document = {
        "schema_version": SCHEMA_VERSION,
        "kind": "workflow-scope",
        "identity": {
            "producer": args.producer,
            "workflow": args.workflow,
            "invocation_id": args.invocation_id,
            "run_id": args.run_id,
            "run_attempt": str(args.run_attempt),
            "commit": args.commit,
            "ref": args.ref,
            "mode": args.mode,
            "started_at": now(),
        },
        "selection": {"input": args.languages, "selected": [language for language in LANGUAGES if selected(args.languages, language)]},
        "presence": presence,
        "languages": languages,
        "detection": {"state": "unknown", "outcome": "unknown", "diagnostics": [], "reason": "detector result is collected from its current-attempt fragment"},
        "analysis": {"state": "unknown", "outcome": "unknown", "reason": "analysis outcome is collected from current-attempt job fragments"},
        "expected_jobs": expected,
        "jobs": [],
        "coverage": {"state": args.coverage_state, "reason": "coverage is represented as workflow state, not analysis scope"},
        "collection": {"status": "initialized", "expected": len(expected), "received": 0, "missing": [], "issues": [], "finalized_at": None},
        "summary": {"artifact": pathlib.Path(args.out).name, "lines": []},
    }
    if args.baseline_ref:
        document["identity"]["baseline_ref"] = args.baseline_ref
    if args.cancellation:
        document["identity"]["cancellation"] = args.cancellation
    return document


def init(args: argparse.Namespace) -> None:
    document = build_document(args)
    write(pathlib.Path(args.out), document)


def fragment(args: argparse.Namespace) -> None:
    identity = {
        "producer": args.producer,
        "workflow": args.workflow,
        "invocation_id": args.invocation_id,
        "run_id": args.run_id,
        "run_attempt": str(args.run_attempt),
        "logical_job": args.logical_job,
        "language": args.language,
        "leg": args.leg,
    }
    diagnostics = list(args.diagnostic or [])
    if args.diagnostic_file:
        try:
            diagnostics.append(pathlib.Path(args.diagnostic_file).read_text(encoding="utf-8", errors="replace"))
        except OSError as exc:
            diagnostics.append(f"cannot read diagnostic file {args.diagnostic_file}: {exc}")
    tools, tools_issue = read_tools(pathlib.Path(args.tools_file)) if args.tools_file else ([], None)
    value: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "kind": "workflow-scope-fragment",
        "identity": identity,
        "state": args.state,
        "outcome": args.outcome,
        "reason": args.reason,
        "reason_code": args.reason_code,
        "diagnostics": diagnostics,
        "measurements": unknown_measurements(),
        "tools": tools,
        "tool_collection": {
            "status": "partial" if tools_issue else "complete",
            "issues": [tools_issue] if tools_issue else [],
        },
    }
    observed = {str(item.get("name")) for item in value["tools"] if item.get("name")}
    step_outcomes = parse_step_outcomes(args.step_outcomes)
    failure_seen = False
    previous_names: set[str] = set()
    missing_records: list[str] = []
    for spec in args.expected_tool or []:
        spec_bits = spec.split("|", 4)
        expected_name = spec_bits[0]
        opaque = len(spec_bits) > 3 and spec_bits[3] == "opaque"
        matching = [item for item in value["tools"] if str(item.get("name")) == expected_name or str(item.get("name", "")).startswith(expected_name + ":")]
        prior = [item for item in value["tools"] if str(item.get("name")) in previous_names or any(str(item.get("name", "")).startswith(name + ":") for name in previous_names)]
        if any(item.get("outcome") == "failure" for item in matching + prior):
            failure_seen = True
        expected = expected_tool_record(
            spec,
            args.dead_code_mode,
            blocked=failure_seen and not opaque,
            step_outcomes=step_outcomes,
        )
        seen = expected["name"] in observed or any(name.startswith(expected["name"] + ":") for name in observed)
        if not seen:
            value["tools"].append(expected)
            if expected["reason_code"] == "missing_tool_record":
                missing_records.append(expected_name)
        previous_names.add(expected_name)
    if missing_records:
        value["tool_collection"]["status"] = "partial"
        value["tool_collection"]["issues"].extend(
            f"missing command boundary record for {name}" for name in missing_records
        )
    write(pathlib.Path(args.out), value)


def fallback_document(args: argparse.Namespace, issue: str) -> dict[str, Any]:
    document = build_document(args, observe_presence=False)
    document["layer2"] = []
    document["jobs"] = [missing_job(args, item, "current-attempt manifest unavailable; execution is unknown") for item in document.get("expected_jobs", [])]
    document["collection"] = {
        "status": "partial",
        "expected": len(document.get("expected_jobs", [])),
        "received": 0,
        "missing": [f"{item['logical_job']}|{item.get('leg', '')}" for item in document.get("expected_jobs", [])],
        "issues": [issue],
        "finalized_at": now(),
    }
    document["summary"] = {"artifact": pathlib.Path(args.out).name, "lines": render_lines(document)}
    return document


def _normalize_layer2_scope(value: dict[str, Any], path: pathlib.Path) -> tuple[dict[str, Any], list[str]]:
    """Keep a Layer 2 producer leg renderable while surfacing nested loss."""
    normalized = dict(value)
    issues: list[str] = []

    def diagnostics(value: object, label: str) -> tuple[list[dict[str, Any]], list[str]]:
        if not isinstance(value, list):
            return [], [f"{label} diagnostics container is malformed"]
        valid: list[dict[str, Any]] = []
        invalid = False
        for item in value:
            if not isinstance(item, dict) or not all(isinstance(item.get(field), str) for field in ("stream", "source", "text")):
                invalid = True
                continue
            valid.append(dict(item))
        return valid, [f"{label} diagnostics contain malformed entries"] if invalid else []

    analysis = normalized.get("analysis")
    if not isinstance(analysis, dict):
        normalized["analysis"] = {"outcome": "unknown", "exit_code": None, "findings": None, "diagnostics": []}
        issues.append("analysis container is malformed")
    else:
        safe_analysis = dict(analysis)
        outcome = safe_analysis.get("outcome", "unknown")
        if not isinstance(outcome, str) or outcome not in VALID_OUTCOMES:
            safe_analysis["outcome"] = "unknown"
            issues.append("analysis outcome is invalid")
        safe_analysis["diagnostics"], diagnostic_issues = diagnostics(safe_analysis.get("diagnostics", []), "analysis")
        issues.extend(diagnostic_issues)
        normalized["analysis"] = safe_analysis

    raw_tools = normalized.get("tools")
    if "tools" not in normalized:
        tools: dict[str, dict[str, Any]] = {}
        issues.append("tools container is missing")
    elif not isinstance(raw_tools, dict):
        tools = {}
        issues.append("tools container is not an object")
    else:
        tools = {}
        for name, item in raw_tools.items():
            if not isinstance(name, str) or not isinstance(item, dict):
                issue = f"invalid tool record {name}: expected an object"
                issues.append(issue)
                continue
            candidate = dict(item)
            candidate.setdefault("command", [])
            candidate.setdefault("working_directory", None)
            tool_diagnostics, diagnostic_issues = diagnostics(candidate.get("diagnostics", []), f"tool {name}")
            candidate["diagnostics"] = []
            violations = validate_tool_record(candidate)
            issues.extend(diagnostic_issues)
            measurement_violation = all(
                issue.startswith("measurement ")
                or issue in {"missing measurements", "measurements must be an object"}
                for issue in violations
            )
            if violations and measurement_violation:
                normalized_tool = dict(item)
                normalized_tool.setdefault("command", [])
                normalized_tool.setdefault("working_directory", None)
                normalized_tool["diagnostics"] = tool_diagnostics
                raw_measurements = item.get("measurements")
                measurements = dict(raw_measurements) if isinstance(raw_measurements, dict) else {}
                for measurement_name in TOOL_MEASUREMENTS:
                    measurement_value = measurements.get(measurement_name)
                    if isinstance(measurement_value, dict) and not any(
                        violation.startswith(f"measurement {measurement_name} ") for violation in violations
                    ):
                        continue
                    original = dict(measurement_value) if isinstance(measurement_value, dict) else {}
                    unit = original.get("unit") if isinstance(original.get("unit"), str) else "unknown"
                    method = original.get("method") if isinstance(original.get("method"), str) else "Layer 2 measurement evidence"
                    measurements[measurement_name] = {
                        **original,
                        "status": "unknown",
                        "count": None,
                        "unit": unit,
                        "method": method,
                        "reason": "measurement evidence is malformed",
                    }
                normalized_tool["measurements"] = measurements
                issue = f"invalid measurement in tool record {name}: {'; '.join(violations)}"
                issues.append(issue)
                collection = normalized_tool.get("collection")
                if not isinstance(collection, dict):
                    collection = {"status": "partial", "issues": []}
                collection["status"] = "partial"
                collection["issues"] = [item for item in collection.get("issues", []) if isinstance(item, str)] + [issue]
                normalized_tool["collection"] = collection
                tools[name] = normalized_tool
                continue
            if violations:
                issue = f"invalid tool record {name}: {'; '.join(violations)}"
                issues.append(issue)
                unknown = _unknown_tool_record(name, issue)
                unknown["diagnostics"] = tool_diagnostics
                tools[name] = unknown
                continue
            normalized_tool = dict(item)
            normalized_tool["diagnostics"] = tool_diagnostics
            if "rust" in normalized_tool:
                normalized_tool["rust"], rust_issues = _normalize_rust_scope(normalized_tool["rust"], name)
                if rust_issues:
                    issues.extend(rust_issues)
                    collection = normalized_tool.get("collection")
                    if not isinstance(collection, dict):
                        collection = {"status": "partial", "issues": []}
                    collection["status"] = "partial"
                    collection["issues"] = [item for item in collection.get("issues", []) if isinstance(item, str)] + rust_issues
                    normalized_tool["collection"] = collection
            tools[name] = normalized_tool
    normalized["tools"] = tools
    for tool in tools.values():
        collection = tool.get("collection")
        if collection is None:
            continue
        if not isinstance(collection, dict):
            issues.append(f"invalid tool collection for {tool.get('name', 'unknown')}")
            tool["collection"] = {
                "status": "partial",
                "issues": [f"invalid tool collection for {tool.get('name', 'unknown')}"],
            }
            continue
        status = collection.get("status")
        collection_issues = collection.get("issues")
        if not isinstance(collection_issues, list):
            issue = f"tool collection issues are malformed for {tool.get('name', 'unknown')}"
            issues.append(issue)
            tool["collection"] = {"status": "partial", "issues": [issue]}
            continue
        if not all(isinstance(item, str) for item in collection_issues):
            issue = f"tool collection issues contain malformed entries for {tool.get('name', 'unknown')}"
            issues.append(issue)
            collection_issues = [item for item in collection_issues if isinstance(item, str)]
            collection["status"] = "partial"
            collection["issues"] = [*collection_issues, issue]
            tool["collection"] = collection
            continue
        if not isinstance(status, str) or status not in {"complete", "partial", "unknown", "failed", "in_progress"}:
            issue = f"tool collection status is invalid for {tool.get('name', 'unknown')}"
            issues.append(issue)
            tool["collection"] = {"status": "partial", "issues": [*collection_issues, issue]}
            continue
        if status != "complete":
            issues.extend(collection_issues)
            if not collection_issues:
                issues.append(f"tool collection is {status} for {tool.get('name', 'unknown')}")

    raw_collection = normalized.get("collection")
    if not isinstance(raw_collection, dict):
        collection = {"status": "partial", "issues": ["Layer 2 collection metadata is unavailable"]}
        issues.append("Layer 2 collection metadata is unavailable")
    else:
        collection = dict(raw_collection)
        status = collection.get("status")
        collection_issues = collection.get("issues")
        if not isinstance(status, str) or status not in {"complete", "partial", "unknown", "failed", "in_progress"}:
            status = "partial"
            issues.append("Layer 2 collection status is invalid")
        if not isinstance(collection_issues, list):
            collection_issues = []
            status = "partial"
            issues.append("Layer 2 collection issues are malformed")
        elif not all(isinstance(item, str) for item in collection_issues):
            collection_issues = [item for item in collection_issues if isinstance(item, str)]
            status = "partial"
            issues.append("Layer 2 collection issues contain malformed entries")
        if status in {"partial", "unknown", "failed", "in_progress"}:
            if collection_issues:
                issues.extend(collection_issues)
            else:
                collection_issues = ["Layer 2 producer reported incomplete collection"]
                issues.append(collection_issues[0])
        elif collection_issues:
            status = "partial"
            issues.extend(collection_issues)
        collection["status"] = status
        collection["issues"] = list(collection_issues)
    if issues:
        collection["status"] = "partial"
        collection["issues"] = collection.get("issues", []) + [item for item in issues if item not in collection.get("issues", [])]
    normalized["collection"] = collection
    return normalized, list(dict.fromkeys(issues))


def layer2_records(directory: pathlib.Path, identity: dict[str, Any], invocation_id: str) -> tuple[list[dict[str, Any]], list[str]]:
    records: list[dict[str, Any]] = []
    issues: list[str] = []
    if not directory.exists():
        return records, issues
    for path in sorted(directory.rglob("*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            issues.append(f"malformed Layer 2 scope {path.name}")
            continue
        if not isinstance(value, dict):
            issues.append(f"malformed Layer 2 scope {path.name}: root is not an object")
            continue
        if value.get("kind") != "layer2-scope":
            continue
        if value.get("schema_version") != SCHEMA_VERSION:
            issues.append(f"malformed Layer 2 scope {path.name}: unsupported schema")
            continue
        value_identity = value.get("identity", {})
        if not isinstance(value_identity, dict):
            issues.append(f"malformed Layer 2 scope {path.name}: identity is not an object")
            continue
        expected_identity = {
            "producer": identity.get("producer", "gate"),
            "run_id": identity.get("run_id"),
            "run_attempt": str(identity.get("run_attempt")),
            "invocation_id": invocation_id,
        }
        if any(str(value_identity.get(key, "")) != str(expected) for key, expected in expected_identity.items()):
            issues.append(f"ignored foreign Layer 2 scope {path.name}")
            continue
        normalized, nested_issues = _normalize_layer2_scope(value, path)
        records.append(normalized)
        issues.extend(f"Layer 2 scope {path.name}: {issue}" for issue in nested_issues)
    return records, issues


def collect(args: argparse.Namespace) -> None:
    manifest_path = pathlib.Path(args.manifest)
    manifest_issue = ""
    try:
        document = read(manifest_path)
    except ValueError as exc:
        document = build_document(args, observe_presence=False)
        manifest_issue = f"current-attempt manifest unavailable: {exc}"
    else:
        if args.invocation_id != "unknown" or args.run_id != "unknown":
            expected_identity = {
                "producer": args.producer,
                "workflow": args.workflow,
                "invocation_id": args.invocation_id,
                "run_id": args.run_id,
                "run_attempt": str(args.run_attempt),
            }
            if any(str(document["identity"].get(field, "")) != str(value) for field, value in expected_identity.items()):
                document = build_document(args, observe_presence=False)
                manifest_issue = "current-attempt manifest identity does not match collector identity"
    identity = document["identity"]
    if args.cancellation:
        identity["cancellation"] = args.cancellation
    expected = document.get("expected_jobs", [])
    received: dict[str, dict[str, Any]] = {}
    issues: list[str] = [manifest_issue] if manifest_issue else []
    directory = pathlib.Path(args.fragments_dir)
    for path in sorted(directory.rglob("*.json")) if directory.exists() else []:
        try:
            fragment_value = read(path)
        except ValueError as exc:
            issues.append(str(exc))
            continue
        fragment_identity = fragment_value.get("identity", {})
        for field in ("producer", "workflow", "invocation_id", "run_id", "run_attempt"):
            if str(fragment_identity.get(field, "")) != str(identity.get(field, "")):
                issues.append(f"ignored foreign fragment {path.name}: {field} does not match current invocation")
                break
        else:
            key = f"{fragment_identity.get('logical_job', '')}|{fragment_identity.get('leg', '')}"
            if key in received:
                issues.append(f"duplicate fragment for {key}")
            else:
                received[key] = fragment_value
    jobs: list[dict[str, Any]] = []
    missing: list[str] = []
    for item in expected:
        key = f"{item['logical_job']}|{item.get('leg', '')}"
        fragment_value = received.get(key)
        if fragment_value is None:
            if item.get("expected_state") not in {"not_applicable", "skipped"} and needs_outcomes(args).get(item["logical_job"]) != "skipped":
                missing.append(key)
            state = item.get("expected_state", "unknown")
            reason = item.get("expected_reason", "no fragment for this current attempt; execution is unknown")
            reason_code = item.get("expected_reason_code", "missing_fragment")
            jobs.append(missing_job(args, item, reason))
        else:
            jobs.append({
                **item,
                "state": fragment_value.get("state", "unknown"),
                "outcome": fragment_value.get("outcome", "unknown"),
                "reason": fragment_value.get("reason", ""),
                "reason_code": fragment_value.get("reason_code"),
                "diagnostics": fragment_value.get("diagnostics", []),
                "measurements": fragment_value.get("measurements", unknown_measurements()),
                "tools": fragment_value.get("tools", []),
                "tool_collection": fragment_value.get("tool_collection", {"status": "unknown", "issues": []}),
            })
            for issue in jobs[-1].get("tool_collection", {}).get("issues", []):
                issues.append(f"{key}: {issue}")
            for tool in jobs[-1].get("tools", []):
                for issue in tool.get("collection", {}).get("issues", []) if isinstance(tool.get("collection"), dict) else []:
                    issues.append(f"{key}/{tool.get('name', 'unknown')}: {issue}")
    document["jobs"] = jobs
    detect = next((job for job in jobs if job["logical_job"] == "detect" and not job.get("leg")), None)
    if detect:
        document["detection"] = {
            "state": detect["state"],
            "outcome": detect["outcome"],
            "reason": detect["reason"],
            "reason_code": detect.get("reason_code"),
            "diagnostics": detect.get("diagnostics", []),
        }
        if detect["outcome"] == "failure":
            for job in jobs:
                if job["state"] == "unknown" and job.get("language") and document.get("languages", {}).get(job["language"], {}).get("state") == "selected":
                    job["state"] = "skipped"
                    job["reason"] = "detector failed before this dependent job could run"
                    job["reason_code"] = "detector_failure"
    layer2, layer2_issues = layer2_records(pathlib.Path(args.layer2_dir), identity, args.layer2_invocation_id)
    document["layer2"] = layer2
    issues.extend(layer2_issues)
    layer2_job = next((job for job in jobs if job["logical_job"] == "layer2" and not job.get("leg")), None)
    if layer2_job is not None:
        if layer2:
            layer2_job["scope"] = layer2
        else:
            layer2_job["state"] = "unknown" if layer2_job["state"] == "run" else layer2_job["state"]
            layer2_job["reason"] = "Layer 2 scope artifact is unavailable for this invocation and attempt"
            layer2_job["reason_code"] = "missing_layer2_scope"
            layer2_key = f"{layer2_job['logical_job']}|{layer2_job.get('leg', '')}"
            if layer2_key not in missing:
                missing.append(layer2_key)
            issues.append("missing Layer 2 scope artifact for this invocation and attempt")
    outcomes = [
        str(job.get("outcome", "unknown"))
        for job in jobs
        if job.get("logical_job") != "coverage" and job.get("expected_state") not in {"not_applicable", "skipped"}
    ]
    if "failure" in outcomes:
        document["analysis"] = {"state": "complete", "outcome": "failure", "reason": "one or more analysis boundaries failed"}
    elif "cancelled" in outcomes:
        document["analysis"] = {"state": "complete", "outcome": "cancelled", "reason": "analysis was cancelled"}
    elif any(outcome == "unknown" for outcome in outcomes):
        document["analysis"] = {"state": "unknown", "outcome": "unknown", "reason": "one or more current-attempt analysis boundaries are unknown"}
    else:
        document["analysis"] = {"state": "complete", "outcome": "success", "reason": "all observed analysis boundaries completed or were explicitly skipped"}
    document["collection"] = {
        "status": "complete" if not missing and not issues else "partial",
        "expected": len(expected),
        "received": len(received),
        "missing": missing,
        "issues": issues,
        "finalized_at": now(),
    }
    document["summary"] = {"artifact": pathlib.Path(args.out).name, "lines": render_lines(document)}
    write(pathlib.Path(args.out), document)


def render_lines(document: dict[str, Any]) -> list[str]:
    identity = document["identity"]
    def safe(value: Any) -> str:
        text = html.escape(str(value), quote=False).replace("\r", "\\r").replace("\n", "\\n")
        text = text.replace("\\", "\\\\")
        for token in ("`", "[", "]", "(", ")", "|", "#"):
            text = text.replace(token, "\\" + token)
        return text if len(text) <= SUMMARY_LINE_LIMIT else text[: SUMMARY_LINE_LIMIT - 3] + "..."

    lines = [
        f"Evidence artifact: {safe(document.get('summary', {}).get('artifact', 'workflow-scope.json'))}",
        f"Workflow scope: {safe(identity['workflow'])} run {safe(identity['run_id'])} attempt {safe(identity['run_attempt'])}",
        f"Collection: {safe(document['collection']['status'])} ({safe(document['collection']['received'])}/{safe(document['collection']['expected'])} current-attempt fragments)",
        f"Analysis: {safe(document.get('analysis', {}).get('outcome', 'unknown'))}",
    ]
    if identity.get("cancellation"):
        lines.append(f"Cancellation metadata: {safe(identity['cancellation'])}")
    for language, value in document.get("languages", {}).items():
        markers = ", ".join(value.get("markers", [])) if value.get("markers") else document.get("presence", {}).get(language, {}).get("state", "unknown")
        lines.append(f"{LANGUAGE_NAMES[language]}: {safe(value['state'])} ({safe(markers)})")
    for job in document.get("jobs", []):
        leg = f" [{safe(job['leg'])}]" if job.get("leg") else ""
        lines.append(f"Job {safe(job['logical_job'])}{leg}: {safe(job['state'])}/{safe(job['outcome'])} — {safe(job['reason'])}")
        for diagnostic in job.get("diagnostics", []):
            lines.append(f"Diagnostic {safe(job['logical_job'])}{leg}: {safe(diagnostic)}")
        for issue in job.get("tool_collection", {}).get("issues", []) if isinstance(job.get("tool_collection"), dict) else []:
            lines.append(f"Tool collection issue {safe(job['logical_job'])}{leg}: {safe(issue)}")
        for tool in job.get("tools", []):
            tool_leg = f"{safe(tool.get('name', 'unknown'))}{leg}"
            lines.append(
                f"Tool {tool_leg}: {safe(tool.get('state', 'unknown'))}/{safe(tool.get('outcome', 'unknown'))}"
                f" rc={safe(tool.get('exit_code'))} — {safe(tool.get('reason', ''))}"
            )
            for diagnostic in tool.get("diagnostics", []):
                lines.append(f"Tool diagnostic {tool_leg}: {safe(diagnostic)}")
            rust = tool.get("rust")
            if tool.get("name") == "clippy" and isinstance(rust, dict):
                requested = rust.get("requested", {})
                observed = rust.get("observed", {})
                platform = observed.get("platform", {}) if isinstance(observed, dict) else {}
                lines.append(
                    f"Rust scope {tool_leg}: {safe(len(observed.get('artifacts', [])))} observed artifacts, "
                    f"features={safe(requested.get('features', []))}, "
                    f"platform={safe(platform.get('target', 'unknown'))}"
                )
                for artifact in observed.get("artifacts", []):
                    target = artifact.get("target", {})
                    lines.append(
                        f"Rust artifact {tool_leg}: {safe(artifact.get('package_id'))} / "
                        f"{safe(target.get('name'))} ({safe(target.get('kind'))}) "
                        f"features={safe(artifact.get('features'))} fresh={safe(artifact.get('fresh'))}"
                    )
                finished = observed.get("build_finished")
                if isinstance(finished, dict):
                    lines.append(f"Rust completion {tool_leg}: success={safe(finished.get('success'))}")
                for issue in rust.get("collection", {}).get("issues", []) if isinstance(rust.get("collection"), dict) else []:
                    lines.append(f"Rust collection issue {tool_leg}: {safe(issue)}")
            for issue in tool.get("collection", {}).get("issues", []) if isinstance(tool.get("collection"), dict) else []:
                lines.append(f"Tool collection issue {tool_leg}: {safe(issue)}")
    for issue in document["collection"].get("issues", []):
        lines.append(f"Collection issue: {safe(issue)}")
    if document["collection"].get("missing"):
        lines.append("Missing current-attempt records remain unknown: " + safe(", ".join(document["collection"]["missing"])))
    lines = [line if len(line) <= SUMMARY_LINE_LIMIT else line[: SUMMARY_LINE_LIMIT - 3] + "..." for line in lines]
    if len(lines) > SUMMARY_MAX_LINES:
        omitted = len(lines) - SUMMARY_MAX_LINES + 1
        lines = lines[: SUMMARY_MAX_LINES - 1] + [f"... {omitted} additional summary lines omitted; see the evidence artifact"]
    return lines


def summary(args: argparse.Namespace) -> None:
    document = read(pathlib.Path(args.out))
    document.setdefault("summary", {})["lines"] = render_lines(document)
    write(pathlib.Path(args.out), document)
    if args.summary_file:
        with pathlib.Path(args.summary_file).open("a", encoding="utf-8") as output:
            output.write("\n".join(document["summary"]["lines"]) + "\n")
    print("\n".join(document["summary"]["lines"]))


def parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--out", required=True)
    command = argparse.ArgumentParser(description=__doc__)
    sub = command.add_subparsers(dest="command", required=True)
    init_parser = sub.add_parser("init", parents=[common])
    init_parser.add_argument("--root", default=".")
    init_parser.add_argument("--producer", default="gate")
    init_parser.add_argument("--workflow", default="quality")
    init_parser.add_argument("--invocation-id", default="local")
    init_parser.add_argument("--run-id", default="local")
    init_parser.add_argument("--run-attempt", default="1")
    init_parser.add_argument("--commit", default="unknown")
    init_parser.add_argument("--ref", default="unknown")
    init_parser.add_argument("--mode", default="full")
    init_parser.add_argument("--languages", default="auto")
    init_parser.add_argument("--baseline-ref", default="")
    init_parser.add_argument("--expected-job", action="append")
    init_parser.add_argument("--expected-jobs-json", default="")
    init_parser.add_argument("--coverage-state", default="unknown")
    init_parser.add_argument("--cancellation", default="")
    init_parser.set_defaults(func=init)
    fragment_parser = sub.add_parser("fragment", parents=[common])
    for name, default in (("producer", "gate"), ("workflow", "quality"), ("invocation-id", "local"), ("run-id", "local"), ("run-attempt", "1"), ("logical-job", "unknown"), ("language", ""), ("leg", ""), ("state", "unknown"), ("outcome", "unknown"), ("reason", ""), ("reason-code", "")):
        fragment_parser.add_argument("--" + name, default=default)
    fragment_parser.add_argument("--diagnostic", action="append")
    fragment_parser.add_argument("--diagnostic-file", default="")
    fragment_parser.add_argument("--tools-file", default="")
    fragment_parser.add_argument("--expected-tool", action="append")
    fragment_parser.add_argument("--dead-code-mode", default="auto")
    fragment_parser.add_argument("--job-outcome", default="unknown")
    fragment_parser.add_argument("--step-outcomes", default="{}")
    fragment_parser.set_defaults(func=fragment)
    tool_parser = sub.add_parser("tool")
    tool_parser.add_argument("--file", required=True)
    tool_parser.add_argument("--name", required=True)
    tool_parser.add_argument("--state", default="run", choices=sorted(VALID_STATES))
    tool_parser.add_argument("--outcome", default="unknown", choices=sorted(VALID_OUTCOMES))
    tool_parser.add_argument("--reason", default="command boundary executed")
    tool_parser.add_argument("--reason-code", default="command")
    tool_parser.add_argument("--exit-code", default="")
    tool_parser.add_argument("--diagnostic", action="append")
    tool_parser.add_argument("--diagnostic-file", default="")
    tool_parser.add_argument("--working-directory", default="")
    tool_parser.add_argument("--collection-issue", default="")
    tool_parser.add_argument("--rust-evidence-file", default="")
    tool_parser.add_argument("--rust-render-diagnostics", action="store_true")
    tool_parser.add_argument("--argv", nargs=argparse.REMAINDER, default=[])
    tool_parser.set_defaults(func=tool_record)
    collect_parser = sub.add_parser("collect")
    collect_parser.add_argument("--manifest", required=True)
    collect_parser.add_argument("--fragments-dir", required=True)
    collect_parser.add_argument("--out", required=True)
    collect_parser.add_argument("--root", default="/path/that/does/not/exist")
    collect_parser.add_argument("--producer", default="gate")
    collect_parser.add_argument("--workflow", default="quality")
    collect_parser.add_argument("--invocation-id", default="unknown")
    collect_parser.add_argument("--run-id", default="unknown")
    collect_parser.add_argument("--run-attempt", default="1")
    collect_parser.add_argument("--commit", default="unknown")
    collect_parser.add_argument("--ref", default="unknown")
    collect_parser.add_argument("--mode", default="full")
    collect_parser.add_argument("--languages", default="auto")
    collect_parser.add_argument("--baseline-ref", default="")
    collect_parser.add_argument("--expected-job", action="append")
    collect_parser.add_argument("--expected-jobs-json", default="")
    collect_parser.add_argument("--coverage-state", default="unknown")
    collect_parser.add_argument("--cancellation", default="")
    collect_parser.add_argument("--layer2-dir", default="/path/that/does/not/exist")
    collect_parser.add_argument("--layer2-invocation-id", default="unknown")
    collect_parser.add_argument("--job-outcomes", dest="job_outcomes_json", default="{}")
    collect_parser.set_defaults(func=collect)
    summary_parser = sub.add_parser("summary")
    summary_parser.add_argument("--out", required=True)
    summary_parser.add_argument("--summary-file", default="")
    summary_parser.set_defaults(func=summary)
    return command


def main(argv: list[str] | None = None) -> int:
    try:
        args = parser().parse_args(argv)
        args.func(args)
    except (OSError, ValueError, KeyError) as exc:
        print(f"workflow scope: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
