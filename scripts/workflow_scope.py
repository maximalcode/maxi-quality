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
PRUNE = {".git", "node_modules", ".venv", "target", "build"}


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read(path: pathlib.Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read workflow scope {path}: {exc}") from exc
    if value.get("schema_version") != SCHEMA_VERSION or value.get("kind") not in {"workflow-scope", "workflow-scope-fragment"}:
        raise ValueError(f"unsupported workflow scope contract in {path}")
    return value


def write(path: pathlib.Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def discover(root: pathlib.Path) -> dict[str, dict[str, Any]]:
    """Observe supported project markers, independent of selection."""
    found: dict[str, list[str]] = {language: [] for language in LANGUAGES}
    if not root.is_dir():
        reason = f"discovery root is not a directory: {root}"
        return {language: {"state": "unknown", "markers": [], "reason": reason} for language in LANGUAGES}
    try:
        for directory, dirs, files in os.walk(root):
            dirs[:] = sorted(name for name in dirs if name not in PRUNE)
            relative = pathlib.Path(directory).relative_to(root)
            for language, patterns in MARKERS.items():
                for pattern in patterns:
                    for filename in files:
                        if pathlib.PurePath(filename).match(pattern):
                            path = (relative / filename).as_posix()
                            if path == ".":
                                path = filename
                            found[language].append(path)
    except OSError as exc:
        return {language: {"state": "unknown", "markers": [], "reason": str(exc)} for language in LANGUAGES}
    return {
        language: {"state": "present" if paths else "absent", "markers": sorted(set(paths))}
        for language, paths in found.items()
    }


def selected(value: str, language: str) -> bool:
    if value == "none":
        return False
    return value == "auto" or language in {part.strip() for part in value.split(",") if part.strip()}


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


def init(args: argparse.Namespace) -> None:
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
    document: dict[str, Any] = {
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


def collect(args: argparse.Namespace) -> None:
    manifest_path = pathlib.Path(args.manifest)
    document = read(manifest_path)
    identity = document["identity"]
    expected = document.get("expected_jobs", [])
    received: dict[str, dict[str, Any]] = {}
    issues: list[str] = []
    directory = pathlib.Path(args.fragments_dir)
    for path in sorted(directory.glob("*.json")) if directory.exists() else []:
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
            jobs.append({
                **item,
                "state": "unknown",
                "outcome": "unknown",
                "reason": "no fragment for this current attempt; execution is unknown",
                "reason_code": "missing_fragment",
                "measurements": unknown_measurements("missing current-attempt fragment; no zero inferred"),
                "examined": measurement(reason="missing current-attempt fragment; no zero inferred"),
            })
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
    document["collection"] = {
        "status": "complete" if not missing and not issues else "partial",
        "expected": len(expected),
        "received": len(received),
        "missing": missing,
        "issues": issues,
        "finalized_at": now(),
    }
    detect = next((job for job in jobs if job["logical_job"] == "detect" and not job.get("leg")), None)
    if detect:
        document["detection"] = {
            "state": detect["state"],
            "outcome": detect["outcome"],
            "reason": detect["reason"],
            "reason_code": detect.get("reason_code"),
            "diagnostics": detect.get("diagnostics", []),
        }
    document["summary"] = {"artifact": pathlib.Path(args.out).name, "lines": render_lines(document)}
    write(pathlib.Path(args.out), document)


def render_lines(document: dict[str, Any]) -> list[str]:
    identity = document["identity"]
    lines = [
        f"Workflow scope: {identity['workflow']} run {identity['run_id']} attempt {identity['run_attempt']}",
        f"Collection: {document['collection']['status']} ({document['collection']['received']}/{document['collection']['expected']} current-attempt fragments)",
    ]
    if identity.get("cancellation"):
        lines.append(f"Cancellation metadata: {identity['cancellation']}")
    for language, value in document.get("languages", {}).items():
        markers = ", ".join(value.get("markers", [])) if value.get("markers") else document.get("presence", {}).get(language, {}).get("state", "unknown")
        lines.append(f"{LANGUAGE_NAMES[language]}: {value['state']} ({markers})")
    for job in document.get("jobs", []):
        leg = f" [{job['leg']}]" if job.get("leg") else ""
        lines.append(f"Job {job['logical_job']}{leg}: {job['state']}/{job['outcome']} — {job['reason']}")
    for issue in document["collection"].get("issues", []):
        lines.append(f"Collection issue: {issue}")
    if document["collection"].get("missing"):
        lines.append("Missing current-attempt records remain unknown: " + ", ".join(document["collection"]["missing"]))
    return lines


def summary(args: argparse.Namespace) -> None:
    document = read(pathlib.Path(args.out))
    document.setdefault("summary", {})["lines"] = render_lines(document)
    write(pathlib.Path(args.out), document)
    if args.summary_file:
        pathlib.Path(args.summary_file).write_text("\n".join(document["summary"]["lines"]) + "\n", encoding="utf-8")
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
