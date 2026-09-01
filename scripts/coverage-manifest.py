#!/usr/bin/env python3
"""Render the analysis-coverage evidence for one quality workflow run.

The gate's result says whether a tool found a problem.  This companion report
states what it actually reached, so an excluded path, a parser hole, or a
skipped language job cannot look like a clean run.  It is deliberately a file
transformer: the workflow supplies GitHub's job results and uploads the JSON it
writes, which keeps the behaviour testable without an Actions runner.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from policy import PER_FILE_ERROR_TYPES, error_type


LANGUAGES = {
    "typescript": ("ts", "has_ts"),
    "dotnet": ("dotnet", "has_dotnet"),
    "python": ("python", "has_python"),
    "rust": ("rust", "has_rust"),
    "java": ("java", "has_java"),
}
DISPLAY_NAMES = {"typescript": "TypeScript", "dotnet": ".NET", "python": "Python", "rust": "Rust", "java": "Java"}


def read_json(path: str | None, default: Any) -> Any:
    if not path:
        return default
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"_read_error": f"{path}: {exc}"}


def is_selected(languages: str, short_name: str) -> bool:
    return languages == "auto" or short_name in {part.strip() for part in languages.split(",")}


def language_states(languages: str, detected: dict[str, Any], jobs: dict[str, Any]) -> dict[str, Any]:
    states: dict[str, Any] = {}
    for language, (short_name, detection_key) in LANGUAGES.items():
        selected = is_selected(languages, short_name)
        was_detected = str(detected.get(detection_key, "")).lower() == "true"
        outcome = str(jobs.get(language, "skipped"))
        if not selected or not was_detected:
            state = "not_applicable"
        elif outcome == "skipped":
            state = "skipped"
        else:
            state = "ran"
        states[language] = {
            "state": state,
            "detected": was_detected,
            "job_result": outcome,
        }
    return states


def policy_skip_count(value: Any) -> int:
    """Count only skips caused by the consumer's ``--exclude`` policy."""
    if isinstance(value, dict):
        return sum(policy_skip_count(v) for v in value.values())
    if isinstance(value, list):
        if len(value) >= 2 and isinstance(value[1], str):
            return int("cli_include_excludes" in value[1] or "--exclude" in value[1])
        return sum(policy_skip_count(item) for item in value)
    return 0


def semgrep_coverage(data: dict[str, Any]) -> dict[str, Any]:
    paths = data.get("paths") if isinstance(data.get("paths"), dict) else {}
    scanned = paths.get("scanned") if isinstance(paths.get("scanned"), list) else []
    errors = data.get("errors") if isinstance(data.get("errors"), list) else []
    unparsed = {
        err.get("path", "?")
        for err in errors
        if isinstance(err, dict) and error_type(err) in PER_FILE_ERROR_TYPES
    }
    read_error = data.get("_read_error")
    return {
        "examined": len(scanned),
        "unparsed": len(unparsed),
        "excluded_by_policy": policy_skip_count(paths.get("skipped", [])),
        # Copy the scanner's objects unchanged. A count loses the one detail a
        # person needs to fix a broken scan.
        "errors": [*errors, *([read_error] if read_error else [])],
    }


def log_errors(log: str) -> dict[str, list[str]]:
    """Keep scanner error lines verbatim and attach them to the named tool."""
    result = {"semgrep": [], "gitleaks": [], "osv": []}
    current: str | None = None
    for line in log.splitlines():
        lowered = line.lower()
        if "semgrep" in lowered:
            current = "semgrep"
        elif "gitleaks" in lowered:
            current = "gitleaks"
        elif "osv" in lowered:
            current = "osv"
        if "error" in lowered and current:
            result[current].append(line)
    return result


def tool_coverage(semgrep: dict[str, Any], scan_log: str) -> dict[str, Any]:
    errors = log_errors(scan_log)
    semgrep["errors"] = [*semgrep["errors"], *errors["semgrep"]]
    # Gitleaks and OSV do not expose an exact file list or count in their stable
    # CLI output.  Null is intentional: inventing a count from a git walk would
    # make the manifest look more complete than the scanner says it is.
    unavailable_count = {
        "examined": None,
        "unparsed": None,
        "excluded_by_policy": None,
        "count_status": "not reported by this scanner",
    }
    return {
        "semgrep": semgrep,
        "gitleaks": {**unavailable_count, "errors": errors["gitleaks"]},
        "osv": {**unavailable_count, "errors": errors["osv"]},
    }


def rust_coverage(language: dict[str, Any], scope: dict[str, Any]) -> dict[str, Any]:
    if language["state"] == "not_applicable":
        return {"clippy": {"state": "not_applicable"}}
    if language["state"] == "skipped":
        return {"clippy": {"state": "skipped"}}
    if not scope:
        return {"clippy": {"state": "did_not_complete", "job_result": language["job_result"]}}
    return {
        "clippy": {
            "state": "completed",
            "job_result": language["job_result"],
            "targets": scope.get("targets", []),
            "features": scope.get("features", []),
        }
    }


def render_summary(manifest: dict[str, Any]) -> str:
    lines = [
        "### Analysis coverage",
        "",
        f"Layer 2 job: **{manifest['layer2']['job_result']}**",
        "",
        "| Language | Detection | Layer 1 |",
        "|---|---|---|",
    ]
    for name, value in manifest["languages"].items():
        detected = "detected" if value["detected"] else "not detected"
        lines.append(f"| {DISPLAY_NAMES[name]} | {detected} | {value['state']} |")
    lines += ["", "| Tool | Examined | Unparsed | Excluded by policy |", "|---|---:|---:|---:|"]
    for name, value in manifest["tools"].items():
        lines.append(
            f"| {name} | {value['examined'] if value['examined'] is not None else 'not reported'} "
            f"| {value['unparsed'] if value['unparsed'] is not None else 'not reported'} "
            f"| {value['excluded_by_policy'] if value['excluded_by_policy'] is not None else 'not reported'} |"
        )
    all_errors = [error for tool in manifest["tools"].values() for error in tool["errors"]]
    if all_errors:
        lines += ["", "#### Scanner errors (verbatim)", "", "```"]
        lines.extend(str(error) for error in all_errors)
        lines.append("```")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--languages", required=True)
    parser.add_argument("--detected", required=True)
    parser.add_argument("--job-results", required=True)
    parser.add_argument("--semgrep-json")
    parser.add_argument("--scan-log")
    parser.add_argument("--rust-scope")
    parser.add_argument("--out", required=True)
    parser.add_argument("--summary", required=True)
    args = parser.parse_args()

    detected = read_json(args.detected, {})
    jobs = read_json(args.job_results, {})
    semgrep_json = read_json(args.semgrep_json, {})
    rust_scope = read_json(args.rust_scope, {})
    scan_log = Path(args.scan_log).read_text(encoding="utf-8") if args.scan_log and Path(args.scan_log).is_file() else ""
    languages = language_states(args.languages, detected, jobs)
    manifest = {
        "schema_version": 1,
        "languages": languages,
        "tools": tool_coverage(semgrep_coverage(semgrep_json), scan_log),
        "layer2": {"job_result": jobs.get("layer2", "skipped")},
        "scanner_log": scan_log,
        "rust": rust_coverage(languages["rust"], rust_scope),
    }
    Path(args.out).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    Path(args.summary).write_text(render_summary(manifest), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
