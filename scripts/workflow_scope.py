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


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read(path: pathlib.Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read workflow scope {path}: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema_version") != SCHEMA_VERSION or value.get("kind") not in {"workflow-scope", "workflow-scope-fragment"}:
        raise ValueError(f"unsupported workflow scope contract in {path}")
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
            "outcome": "skipped",
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


def build_document(args: argparse.Namespace) -> dict[str, Any]:
    root = pathlib.Path(args.root).resolve()
    presence = discover(root)
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
        if observed["state"] == "absent":
            expected.append({"logical_job": language, "language": language, "leg": "", "expected_state": "not_applicable", "expected_reason": "language marker absent"})
        elif observed["state"] == "present" and not selected(args.languages, language):
            expected.append({"logical_job": language, "language": language, "leg": "", "expected_state": "skipped", "expected_reason": "language present but deselected", "expected_reason_code": "deselected"})
        elif observed["state"] == "unknown":
            expected.append({"logical_job": language, "language": language, "leg": "", "expected_state": "unknown", "expected_reason": "language discovery incomplete"})
        elif observed["state"] == "present":
            expected.append({"logical_job": language, "language": language, "leg": "", "expected_state": "unknown", "expected_reason": "selected language has no current target list"})
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
    value: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "kind": "workflow-scope-fragment",
        "identity": identity,
        "state": args.state,
        "outcome": args.outcome,
        "reason": args.reason,
        "reason_code": args.reason_code,
        "diagnostics": args.diagnostic or [],
        "measurements": unknown_measurements(),
    }
    write(pathlib.Path(args.out), value)


def fallback_document(args: argparse.Namespace, issue: str) -> dict[str, Any]:
    document = build_document(args)
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


def layer2_records(directory: pathlib.Path, identity: dict[str, Any], invocation_id: str) -> tuple[list[dict[str, Any]], list[str]]:
    records: list[dict[str, Any]] = []
    issues: list[str] = []
    if not directory.exists():
        return records, issues
    for path in sorted(directory.rglob("*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if value.get("kind") != "layer2-scope":
            continue
        value_identity = value.get("identity", {})
        expected_identity = {
            "producer": identity.get("producer", "gate"),
            "run_id": identity.get("run_id"),
            "run_attempt": str(identity.get("run_attempt")),
            "invocation_id": invocation_id,
        }
        if any(str(value_identity.get(key, "")) != str(expected) for key, expected in expected_identity.items()):
            issues.append(f"ignored foreign Layer 2 scope {path.name}")
            continue
        records.append(value)
    return records, issues


def collect(args: argparse.Namespace) -> None:
    manifest_path = pathlib.Path(args.manifest)
    try:
        document = read(manifest_path)
    except ValueError as exc:
        document = fallback_document(args, f"current-attempt manifest unavailable: {exc}")
        records, issues = layer2_records(pathlib.Path(args.layer2_dir), document["identity"], args.layer2_invocation_id)
        document["layer2"] = records
        document["collection"]["issues"].extend(issues)
        document["summary"] = {"artifact": pathlib.Path(args.out).name, "lines": render_lines(document)}
        write(pathlib.Path(args.out), document)
        return
    identity = document["identity"]
    expected = document.get("expected_jobs", [])
    received: dict[str, dict[str, Any]] = {}
    issues: list[str] = []
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
            })
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
        text = text.replace("`", "\\`")
        return text if len(text) <= SUMMARY_LINE_LIMIT else text[: SUMMARY_LINE_LIMIT - 3] + "..."

    lines = [
        f"Evidence artifact: {safe(document.get('summary', {}).get('artifact', 'workflow-scope.json'))}",
        f"Workflow scope: {safe(identity['workflow'])} run {safe(identity['run_id'])} attempt {safe(identity['run_attempt'])}",
        f"Collection: {safe(document['collection']['status'])} ({safe(document['collection']['received'])}/{safe(document['collection']['expected'])} current-attempt fragments)",
    ]
    if identity.get("cancellation"):
        lines.append(f"Cancellation metadata: {safe(identity['cancellation'])}")
    for language, value in document.get("languages", {}).items():
        markers = ", ".join(value.get("markers", [])) if value.get("markers") else document.get("presence", {}).get(language, {}).get("state", "unknown")
        lines.append(f"{LANGUAGE_NAMES[language]}: {safe(value['state'])} ({safe(markers)})")
    for job in document.get("jobs", []):
        leg = f" [{safe(job['leg'])}]" if job.get("leg") else ""
        lines.append(f"Job {safe(job['logical_job'])}{leg}: {safe(job['state'])}/{safe(job['outcome'])} — {safe(job['reason'])}")
    for issue in document["collection"].get("issues", []):
        lines.append(f"Collection issue: {safe(issue)}")
    if document["collection"].get("missing"):
        lines.append("Missing current-attempt records remain unknown: " + safe(", ".join(document["collection"]["missing"])))
    return [line if len(line) <= SUMMARY_LINE_LIMIT else line[: SUMMARY_LINE_LIMIT - 3] + "..." for line in lines]


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
    fragment_parser.set_defaults(func=fragment)
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
