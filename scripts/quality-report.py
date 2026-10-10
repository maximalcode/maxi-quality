#!/usr/bin/env python3
"""Build the Markdown body of a repo's standing quality-report issue.

WHY A GITHUB ISSUE IS THE DATABASE

This baseline has no server and no cloud by design (zero spend is a success
criterion, not a preference). But a gate has no memory: `quality.yml` answers
"is this PR clean?" and nothing answers "what is still wrong from before?".
SonarQube's real advantage over this setup was never detection — it was that
it kept state. See docs/EVAL-vs-sonarqube.md.

GitHub code scanning would be the better store, but on a private repo owned by
a personal account it needs Advanced Security, which is the paid path. So the
store is a single GitHub issue, updated in place: the body holds the current
breakdown, and a history table that grows one row per run. Free, no infra, and
the trend lives where the work already is.

ONE issue, updated forever — never a new issue per run. A weekly bot that opens
issues is noise, and noise gets muted, and a muted report is worse than none.

A SCAN THAT BROKE IS NOT A SCAN THAT FOUND NOTHING

Semgrep reports a run that failed to load a rule, or crashed part-way, as
`results: []` with the reason in `.errors` — so reading only `.results` rendered
`| Semgrep | **0** findings |` and wrote a `0` into the history table, where it
is preserved forever. The reassuring answer was the wrong one, and the table
that exists to show a trend recorded an outage as an achievement. So `.errors`
and `.paths.scanned` are read too, an errored run renders as ERRORED, and the
script exits 2 — after printing the body, so the issue still shows what happened
rather than the workflow dying with the news.

Reads Semgrep JSON, emits Markdown. Deliberately does no network I/O — the
workflow does the GitHub side, so this stays unit-testable with a fixture.

Exit codes: 0 rendered · 2 rendered, but the scan had ERRORED · 3 the results
file could not be read at all (nothing is printed, so nothing overwrites the
standing issue)
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import html
import json
import re
import sys

MARKER = "<!-- maxi-quality:report -->"
HISTORY_HEADING = "## History"
HISTORY_DATA_START = "<!-- maxi-quality:history-v2 -->"
HISTORY_DATA_END = "<!-- /maxi-quality:history-v2 -->"
# Legacy rows look like: | 2026-08-01 | 68 | no-ambient-clock (63) |
LEGACY_HISTORY_ROW = re.compile(r"^\|\s*(\d{4}-\d{2}-\d{2})\s*\|\s*([^|]+)\|\s*([^|]+)\|$", re.M)
# v2 rows are deliberately plain Markdown so a damaged hidden metadata block
# can still be recovered without inventing a fresh history.
HISTORY_ROW = re.compile(
    r"^\|\s*([^|]+)\|\s*([^|]+)\|\s*([^|]+)\|\s*([^|]+)\|\s*([^|]+)\|$",
    re.M,
)
# Keep the table readable rather than unbounded; the issue is a dashboard, not
# an audit log. Old rows fall off the bottom.
MAX_HISTORY = 52
# Same reasoning for the unparsed-file list (#43): a repo whose house style
# semgrep's parser cannot read produces one row per file, and a hundred rows in
# the middle of a dashboard buries everything under it. Truncation is announced
# rather than silent — an unlabelled cut reads as "that was all of them", which
# is the same failure shape as every gate bug here.
MAX_UNPARSED_ROWS = 20
MAX_DIAGNOSTIC_EXCERPT = 220
MAX_HISTORY_REASON = 140
MAX_HISTORY_VOCAB = 128


def load_sbom(path: str | None) -> tuple[int, collections.Counter[str]] | None:
    """Return (component count, license histogram) from a CycloneDX 1.6 SBOM.

    CycloneDX spells a license three different ways and all three are in the
    wild: an SPDX id, a free-text name, or an expression ("MIT OR Apache-2.0").
    A component with none of them is genuinely unknown, which is worth counting
    rather than dropping — an unlicensed dependency is the one you actually
    need to hear about.
    """
    if not path:
        return None
    try:
        with open(path) as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        # The SBOM is an extra, not the point of the report. A missing or
        # malformed one must not cost the repo its Semgrep history.
        return None

    counts: collections.Counter[str] = collections.Counter()
    components = data.get("components", [])
    for comp in components:
        entries = comp.get("licenses") or []
        names = []
        for entry in entries:
            if "expression" in entry:
                names.append(entry["expression"])
            elif isinstance(entry.get("license"), dict):
                lic = entry["license"]
                name = lic.get("id") or lic.get("name")
                if name:
                    names.append(name)
        counts[" / ".join(sorted(set(names))) if names else "UNKNOWN"] += 1
    return len(components), counts


def _first_error(errors: list) -> str:
    """Semgrep's `.errors` entries are objects, but not reliably so across
    versions — and a report that crashes while explaining a crash is useless.

    The result lands inside a Markdown table cell, so a newline or a bare pipe
    from a tool's error text would break the table it is being reported in.
    """
    first = errors[0]
    if isinstance(first, dict):
        text = str(first.get("long_msg") or first.get("message") or first.get("type") or first)
    else:
        text = str(first)
    text = " ".join(text.split()).replace("|", "\\|")
    return text[:197] + "..." if len(text) > 200 else text


def load_findings(path: str) -> tuple[collections.Counter[str], str | None, list[str]]:
    """Return (counts, reason-this-is-not-a-finding-set, unparsed-files).

    The second element is what stops a broken run from rendering as a clean one.
    Two shapes reach here as `results: []`:

      - `.errors` holds something that is not a per-file parse failure — a rule
        failed to load, a target could not be read, semgrep aborted. It scanned
        some or none of the tree and does not know what it missed.
      - `.paths.scanned` is empty — it ran to completion over nothing at all,
        which on a full-repo report means the target was wrong, not that the
        repo is empty. (`.paths` absent entirely is an older/leaner output and
        is NOT treated as an error; only an explicit empty list is.)

    THE THIRD ELEMENT IS A COVERAGE GAP, NOT AN OUTAGE (#43). A file semgrep
    cannot parse had no rule run against it, but the rest of the scan is real.
    Treating that as ERRORED — which this did — blanked the whole standing
    report and wrote ERRORED into the permanent history table because one C# 12
    primary constructor was in the tree. Now the findings still render and the
    unparsed files get their own line, which is the number that was previously
    invisible in both directions.

    The split itself lives in policy.py so the gate and the report cannot
    disagree about what counts as a failed scan. That was worth one import: two
    copies of this rule is exactly how the docker and native semgrep paths came
    to disagree about --changed-only.
    """
    from policy import PER_FILE_ERROR_TYPES, error_type  # noqa: PLC0415 — sibling script

    with open(path) as fh:
        data = json.load(fh)

    unparsed_errs, fatal = [], []
    for err in data.get("errors") or []:
        tag = error_type(err) if isinstance(err, dict) else "?"
        (unparsed_errs if tag in PER_FILE_ERROR_TYPES else fatal).append(err)

    if fatal:
        return (
            collections.Counter(),
            f"semgrep reported {len(fatal)} error(s): {_first_error(fatal)}",
            [],
        )

    # Deduplicated: one file with three unparseable constructs is three errors
    # and still one hole.
    unparsed = sorted({e.get("path", "?") for e in unparsed_errs if isinstance(e, dict)})

    scanned = (data.get("paths") or {}).get("scanned")
    if scanned is not None and len(scanned) == 0:
        return collections.Counter(), "semgrep scanned 0 files", unparsed
    # Same guard the gate applies: if nothing semgrep looked at could be parsed,
    # `results: []` means "nobody looked", and that must not render as clean.
    if scanned and unparsed and len(unparsed) >= len(scanned):
        return (
            collections.Counter(),
            f"all {len(scanned)} file(s) semgrep looked at failed to parse",
            unparsed,
        )

    counts = collections.Counter(
        r["check_id"].split(".")[-1] for r in data.get("results", [])
    )
    return counts, None, unparsed


def _one_line(value: object, limit: int = MAX_HISTORY_REASON) -> str:
    text = " ".join(str(value or "").split()).replace("|", "\\|")
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _parse_time(value: object, fallback: str = "") -> str:
    """Return a sortable UTC timestamp, preserving unknown as an empty value."""
    if not isinstance(value, str) or not value:
        return fallback
    candidate = value.replace("Z", "+00:00")
    try:
        parsed = dt.datetime.fromisoformat(candidate)
    except ValueError:
        return fallback
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _markdown_excerpt(value: object, limit: int = MAX_DIAGNOSTIC_EXCERPT) -> str:
    """Return a bounded diagnostic excerpt that remains literal in Markdown."""
    text = " ".join(str(value or "").split())
    if len(text) > limit:
        text = text[: limit - 3] + "..."
    # HTML escaping keeps comments/tags inert. Backslash escapes keep Markdown
    # emphasis, code spans, links, images, headings and table delimiters
    # literal. Truncate before escaping so the visible limit describes the
    # emitted diagnostic rather than entity-expanded markup.
    text = html.escape(text, quote=False)
    for token in ("\\", "`", "*", "_", "[", "]", "(", ")", "#", ">", "|"):
        text = text.replace(token, "\\" + token)
    return text


def _scope_excerpt(value: object) -> str:
    if isinstance(value, list):
        values = []
        for item in value:
            if isinstance(item, dict):
                values.append(str(item.get("text", "")))
            else:
                values.append(str(item))
        value = " ".join(values)
    return _markdown_excerpt(value)


def _scope_failure_is_finding(name: object, record: dict) -> bool:
    """Recognize only documented native exit-1 finding boundaries."""
    exit_code = record.get("exit_code")
    if not isinstance(exit_code, int) or isinstance(exit_code, bool) or exit_code != 1:
        return False
    if name in {"gitleaks", "osv", "licenses"}:
        return True
    reason = record.get("reason")
    return (
        name == "semgrep"
        and isinstance(reason, str)
        and reason.strip().lower() == "semgrep completed with findings"
    )


def _scope_operational_reason(scope: dict) -> str:
    """Return the first operational failure's diagnostic for report errors."""
    tools = scope.get("tools") if isinstance(scope.get("tools"), dict) else {}
    for name, record in tools.items():
        if not isinstance(record, dict) or record.get("outcome") != "failure":
            continue
        if not _scope_failure_is_finding(name, record):
            reason = record.get("reason")
            if isinstance(reason, str) and reason.strip():
                return reason.strip()
            return f"Layer 2 {name} operation failed"
    return "scope records a failed/incomplete Layer 2 attempt"


def _scope_has_operational_error(scope: dict) -> bool:
    """Distinguish a scanner finding outcome from a broken scanner boundary."""
    analysis = scope.get("analysis") if isinstance(scope.get("analysis"), dict) else {}
    outcome = analysis.get("outcome")
    if not isinstance(outcome, str) or outcome not in {"failure", "cancelled"}:
        return False
    if outcome == "cancelled":
        return True
    tools = scope.get("tools") if isinstance(scope.get("tools"), dict) else {}
    saw_failure = False
    for name, record in tools.items():
        if not isinstance(record, dict) or record.get("outcome") != "failure":
            continue
        saw_failure = True
        if not _scope_failure_is_finding(name, record):
            return True
    return not saw_failure


def _compact_value(value: object, depth: int = 0) -> object:
    """Bound nested scope metadata before copying it into the issue body."""
    if depth > 2:
        return _one_line(value, 90)
    if isinstance(value, dict):
        return {str(key): _compact_value(value[key], depth + 1) for key in list(value)[:10]}
    if isinstance(value, list):
        return [_compact_value(item, depth + 1) for item in value[:10]]
    if isinstance(value, str):
        return _one_line(value, 120)
    return value


def load_scope(path: str | None) -> tuple[dict | None, str | None]:
    """Read the same-run Layer 2 artifact without making scope collection gating."""
    if not path:
        return None, "scope artifact was not handed to the report"
    try:
        with open(path, encoding="utf-8") as fh:
            scope = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"scope artifact unavailable: {exc}"
    if not isinstance(scope, dict) or scope.get("kind") != "layer2-scope" or scope.get("schema_version") != 1:
        return None, "scope artifact has unsupported or malformed contract"
    identity = scope.get("identity")
    tools = scope.get("tools")
    if not isinstance(identity, dict) or not isinstance(tools, dict):
        return None, "scope artifact is missing identity or tools"
    for key in ("analysis", "collection", "summary"):
        if key in scope and not isinstance(scope[key], dict):
            return None, f"scope artifact {key} metadata is malformed"
    return scope, None


def _compact_measurement(measurement: object) -> dict:
    if not isinstance(measurement, dict):
        return {"status": "unknown", "count": None, "unit": "unknown", "method": "unknown", "reason": "measurement unavailable"}
    raw_status = measurement.get("status")
    status = raw_status if isinstance(raw_status, str) and raw_status in {"known", "unknown", "not_applicable"} else "unknown"
    count = measurement.get("count") if status == "known" and isinstance(measurement.get("count"), int) and not isinstance(measurement.get("count"), bool) and measurement.get("count") >= 0 else None
    if status == "known" and count is None:
        status = "unknown"
    result = {
        "status": status,
        "count": count,
        "unit": _one_line(measurement.get("unit", "unknown"), 40),
    }
    if status == "known":
        result["method"] = _one_line(measurement.get("method", "unknown"), 60)
    return result


def _safe_history_scope(scope: object) -> dict:
    """Normalize optional hidden scope metadata before comparison or display."""
    if not isinstance(scope, dict):
        return {"status": "unknown", "reason": "malformed scope metadata"}
    raw_status = scope.get("status")
    status = raw_status if isinstance(raw_status, str) and raw_status in {"available", "unknown"} else "unknown"
    safe = {"status": status}
    if status != "available":
        safe["reason"] = _one_line(scope.get("reason", "scope metadata unavailable"))
    if isinstance(scope.get("operational_error"), bool):
        safe["operational_error"] = scope["operational_error"]
    for key in ("outcome", "collection", "artifact", "artifact_link", "diagnostic"):
        value = scope.get(key)
        if isinstance(value, str):
            safe[key] = _one_line(value, 220)
    raw_tools = scope.get("tools")
    safe_tools = {}
    malformed = status == "available" and (not isinstance(raw_tools, dict) or not raw_tools)

    def recover_measurement(value: object) -> dict:
        nonlocal malformed
        normalized = _compact_measurement(value)
        if not isinstance(value, dict) or (
            value.get("status") != normalized["status"]
            or value.get("count") != normalized["count"]
            or isinstance(value.get("count"), bool)
            or not isinstance(value.get("unit"), str)
            or (normalized["status"] == "known" and not isinstance(value.get("method"), str))
        ):
            malformed = True
        return normalized

    if isinstance(raw_tools, dict):
        for raw_name, raw_tool in raw_tools.items():
            name = _one_line(raw_name, 80)
            if not isinstance(raw_tool, dict):
                malformed = True
                safe_tools[name] = {"state": "unknown", "outcome": "unknown", "reason": "malformed tool metadata"}
                continue
            tool = {}
            for key in ("requested", "state", "outcome", "reason_code"):
                value = raw_tool.get(key)
                if key == "requested" and isinstance(value, bool):
                    tool[key] = value
                elif isinstance(value, str):
                    tool[key] = _one_line(value, 140)
            for key in ("mode", "effective"):
                value = raw_tool.get(key)
                if isinstance(value, dict):
                    tool[key] = _compact_value(value)
                elif key in raw_tool:
                    malformed = True
            measurements = raw_tool.get("measurements")
            if isinstance(measurements, dict):
                tool["measurements"] = {
                    key: recover_measurement(measurements.get(key))
                    for key in ("examined", "unparsed", "policy_excluded")
                    if key in measurements
                }
            elif "measurements" in raw_tool:
                malformed = True
            not_applicable = raw_tool.get("not_applicable")
            if isinstance(not_applicable, list):
                tool["not_applicable"] = [
                    key for key in not_applicable
                    if isinstance(key, str) and key in {"examined", "unparsed", "policy_excluded"}
                ]
                if len(tool["not_applicable"]) != len(not_applicable):
                    malformed = True
            elif "not_applicable" in raw_tool:
                malformed = True
            native = raw_tool.get("native")
            if isinstance(native, dict) and "component_count" in native:
                tool["native"] = {"component_count": recover_measurement(native.get("component_count"))}
            elif "native" in raw_tool and not isinstance(native, dict):
                malformed = True
            safe_tools[name] = tool
    if safe_tools:
        safe["tools"] = safe_tools
    if malformed:
        safe.update(status="unknown", reason="malformed scope metadata; comparison unavailable")
    return safe


def _safe_history_entry(entry: dict) -> dict:
    """Keep recoverable finding identity while degrading malformed scope fields."""
    raw_identity = entry.get("identity") if isinstance(entry.get("identity"), dict) else {}
    identity = {}
    for key in ("run_id", "run_attempt", "commit", "ref", "mode", "baseline_ref", "producer"):
        value = raw_identity.get(key)
        identity[key] = _one_line(value, 140) if isinstance(value, str) else "unknown"
    identity["started_at"] = _parse_time(raw_identity.get("started_at"), "")
    findings = entry.get("findings")
    if not isinstance(findings, int) or isinstance(findings, bool) or findings < 0:
        findings = None
    safe = {
        "id": _one_line(entry.get("id"), 180) if isinstance(entry.get("id"), str) else "malformed-entry",
        "legacy": bool(entry.get("legacy", False)),
        "identity": identity,
        "findings": findings,
        "largest": _one_line(entry.get("largest", "—"), 120),
        "outcome": entry.get("outcome") if isinstance(entry.get("outcome"), str) and entry.get("outcome") in {"success", "failure", "incomplete", "unknown"} else "unknown",
        "scope": _safe_history_scope(entry.get("scope")),
    }
    presentation = entry.get("presentation")
    if isinstance(presentation, dict):
        counts = presentation.get("counts")
        safe_presentation = {
            "counts": {
                str(rule): count for rule, count in counts.items()
                if isinstance(count, int) and not isinstance(count, bool) and count >= 0
            } if isinstance(counts, dict) else {},
        }
        for key in ("gitleaks", "osv", "licenses", "scan_error"):
            if isinstance(presentation.get(key), str):
                safe_presentation[key] = _one_line(presentation[key], 220)
        paths = presentation.get("unparsed")
        if isinstance(paths, list):
            safe_presentation["unparsed"] = [_one_line(path, 180) for path in paths if isinstance(path, str)][:MAX_UNPARSED_ROWS]
        total = presentation.get("unparsed_total")
        if isinstance(total, int) and not isinstance(total, bool) and total >= 0:
            safe_presentation["unparsed_total"] = total
        sbom = presentation.get("sbom")
        if isinstance(sbom, dict) and isinstance(sbom.get("components"), int) and not isinstance(sbom.get("components"), bool) and sbom["components"] >= 0:
            licenses = sbom.get("licenses")
            safe_presentation["sbom"] = {
                "components": sbom["components"],
                "licenses": {
                    str(name): count for name, count in licenses.items()
                    if isinstance(count, int) and not isinstance(count, bool) and count >= 0
                } if isinstance(licenses, dict) else {},
            }
        safe["presentation"] = safe_presentation
    return safe


def _compact_scope(scope: dict | None, scope_error: str | None) -> dict:
    if scope is None:
        return {"status": "unknown", "reason": _one_line(scope_error or "scope unavailable")}
    analysis = scope.get("analysis") if isinstance(scope.get("analysis"), dict) else {}
    collection = scope.get("collection") if isinstance(scope.get("collection"), dict) else {}
    compact = {
        "status": "available",
        "outcome": analysis.get("outcome", "unknown"),
        # A findings-bearing analysis is recorded as failure by the producer,
        # but complete evidence still makes it a valid comparison baseline.
        # Retain the separate operational classification so history does not
        # turn an ordinary finding delta into an incomplete-attempt warning.
        "operational_error": _scope_has_operational_error(scope),
        "exit_code": analysis.get("exit_code"),
        "collection": collection.get("status", "unknown"),
        "tools": {},
        "artifact": (scope.get("summary") if isinstance(scope.get("summary"), dict) else {}).get("artifact", "layer2-scope.json"),
    }
    # Full diagnostics remain in the run artifact, and the current entry gets
    # a bounded excerpt in _display_scope_data. Historical entries only need
    # structured evidence for comparison; retaining repeated excerpts makes a
    # bounded issue body grow with the number of runs.
    for name, record in (scope.get("tools") or {}).items():
        if not isinstance(record, dict):
            compact["tools"][name] = {"state": "unknown", "outcome": "unknown", "reason": "malformed"}
            continue
        effective = record.get("effective") if isinstance(record.get("effective"), dict) else {}
        keep_effective = {}
        for key in ("tool", "version", "diagnostic_mode", "mode", "resolution", "fallback", "license_allowlist", "format", "all_packages", "license_metadata", "comparison", "content_fingerprint", "config_fingerprint", "ignore_sources", "unknown_sources"):
            if key in effective:
                value = effective[key]
                if key in {"ignore_sources", "unknown_sources"} and isinstance(value, list):
                    value = [_one_line(item, 100) for item in value[:12]]
                else:
                    value = _compact_value(value)
                keep_effective[key] = value
        measurements = record.get("measurements") if isinstance(record.get("measurements"), dict) else {}
        tool_compact = {}
        if record.get("requested", False) is False:
            tool_compact["requested"] = False
        if record.get("state", "unknown") != "unknown":
            tool_compact["state"] = record.get("state")
        if record.get("outcome", "unknown") != "unknown":
            tool_compact["outcome"] = record.get("outcome")
        if record.get("reason_code") and record.get("reason_code") != "requested":
            tool_compact["reason_code"] = record["reason_code"]
        mode = _compact_value(record.get("mode")) if isinstance(record.get("mode"), dict) else {}
        if mode:
            tool_compact["mode"] = mode
        if keep_effective:
            tool_compact["effective"] = keep_effective
        compact_measurements = {
            key: _compact_measurement(measurements.get(key))
            for key in ("examined", "unparsed", "policy_excluded")
            if isinstance(measurements.get(key), dict)
            and measurements[key].get("status") == "known"
        }
        if compact_measurements:
            tool_compact["measurements"] = compact_measurements
        not_applicable = [
            key for key in ("examined", "unparsed", "policy_excluded")
            if isinstance(measurements.get(key), dict)
            and measurements[key].get("status") == "not_applicable"
        ]
        if not_applicable:
            tool_compact["not_applicable"] = not_applicable
        native = record.get("native") if isinstance(record.get("native"), dict) else {}
        component_count = native.get("component_count") if isinstance(native.get("component_count"), dict) else None
        if component_count and component_count.get("status") == "known":
            tool_compact["native"] = {
                "component_count": {
                    "status": "known",
                    "count": component_count.get("count"),
                    "unit": _one_line(component_count.get("unit", "dependency_component"), 40),
                    "method": _one_line(component_count.get("method", "native SBOM evidence"), 60),
                }
            }
        compact["tools"][name] = tool_compact
    return compact


def _display_scope_data(scope: dict | None, scope_error: str | None) -> dict:
    """Keep full bounded reasons for the current run while history stays compact."""
    compact = _compact_scope(scope, scope_error)
    if scope is None:
        return compact
    for name, record in (scope.get("tools") or {}).items():
        if not isinstance(record, dict):
            continue
        current = compact["tools"].setdefault(name, {})
        current.update({
            "requested": bool(record.get("requested", False)),
            "state": record.get("state", "unknown"),
            "outcome": record.get("outcome", "unknown"),
            "reason": _one_line(record.get("reason", "tool evidence unavailable")),
            "measurements": {},
        })
        measurements = record.get("measurements") if isinstance(record.get("measurements"), dict) else {}
        for key in ("examined", "unparsed", "policy_excluded"):
            measurement = measurements.get(key, {}) if isinstance(measurements.get(key, {}), dict) else {}
            current["measurements"][key] = _compact_measurement(measurement)
            current["measurements"][key]["reason"] = _one_line(measurement.get("reason", "measurement unavailable"), 150)
        native = record.get("native") if isinstance(record.get("native"), dict) else {}
        component_count = native.get("component_count") if isinstance(native.get("component_count"), dict) else None
        if component_count:
            current["native"] = {"component_count": _compact_measurement(component_count)}
        current["diagnostic"] = _scope_excerpt(record.get("diagnostics"))
    current_analysis = scope.get("analysis") if isinstance(scope.get("analysis"), dict) else {}
    if current_analysis.get("diagnostics"):
        compact["diagnostic"] = _scope_excerpt(current_analysis.get("diagnostics"))
    return compact


def _scope_identity(scope: dict | None, args: argparse.Namespace) -> dict:
    identity = scope.get("identity", {}) if isinstance(scope, dict) else {}
    return {
        "producer": identity.get("producer", "report"),
        "run_id": str(identity.get("run_id", args.run_id or "unknown")),
        "run_attempt": str(identity.get("run_attempt", args.run_attempt or "unknown")),
        "started_at": _parse_time(identity.get("started_at"), _parse_time(args.started_at, "")),
        "commit": _one_line(identity.get("commit", args.commit or "unknown"), 80),
        "ref": _one_line(identity.get("ref", args.ref or "unknown"), 120),
        "mode": _one_line(identity.get("mode", args.mode or "full"), 60),
        "baseline_ref": _one_line(identity.get("baseline_ref", args.baseline_ref or ""), 120),
    }


def _entry_id(identity: dict, date: str) -> str:
    run_id, attempt = identity.get("run_id"), identity.get("run_attempt")
    if run_id and attempt and run_id != "unknown" and attempt != "unknown":
        return f"{run_id}/{attempt}"
    return f"legacy:{date}"


def _legacy_entry(date: str, result: str, largest: str, ordinal: int) -> dict:
    result = result.strip()
    findings = int(result) if result.isdigit() else None
    return {
        "id": f"legacy:{date}:{ordinal}",
        "legacy": True,
        "identity": {"run_id": "legacy", "run_attempt": "unknown", "started_at": f"{date}T00:00:00Z", "mode": "unknown", "commit": "unknown", "ref": "unknown", "producer": "report"},
        "findings": findings,
        "largest": _one_line(largest, 100),
        "outcome": "failure" if findings is None else "success",
        "scope": {"status": "unknown", "reason": "legacy history row has no own-run scope"},
    }


def _parse_history_rows(body: str) -> list[dict]:
    if not body or HISTORY_HEADING not in body:
        raise ValueError("previous report has no history table")
    tail = body.split(HISTORY_HEADING, 1)[1]
    entries = []
    for ordinal, match in enumerate(HISTORY_ROW.finditer(tail)):
        run, attempt, started, outcome, findings = [part.strip() for part in match.groups()]
        if run in {"Run", "---"} or attempt in {"Attempt", "---"}:
            continue
        parsed_findings = int(findings) if findings.isdigit() else None
        entries.append({
            "id": f"{run}/{attempt}", "legacy": False,
            "identity": {"run_id": run, "run_attempt": attempt, "started_at": _parse_time(started, ""), "mode": "unknown", "commit": "unknown", "ref": "unknown", "producer": "report"},
            "findings": parsed_findings, "largest": "—", "outcome": outcome.lower(),
            "scope": {"status": "unknown", "reason": "compact metadata unavailable"},
        })
    if entries:
        return entries
    for ordinal, match in enumerate(LEGACY_HISTORY_ROW.finditer(tail)):
        entries.append(_legacy_entry(match.group(1), match.group(2), match.group(3), ordinal))
    if not entries:
        raise ValueError("previous report history table is malformed")
    return entries


def previous_history(body: str | None) -> list[dict]:
    """Recover compact history, retaining rows when optional scope metadata is bad."""
    if not body:
        return []
    marker_entries = None
    if HISTORY_DATA_START in body:
        start = body.index(HISTORY_DATA_START) + len(HISTORY_DATA_START)
        end = body.find(HISTORY_DATA_END, start)
        if end >= 0:
            raw = body[start:end].strip()
            # Earlier reports put bare JSON between closed marker comments.
            # Keep reading those while the writer hides new metadata itself.
            if raw.startswith("<!--") and raw.endswith("-->"):
                raw = raw[4:-3].strip()
            try:
                value = json.loads(raw)
                if isinstance(value, list):
                    marker_entries = [
                        _safe_history_entry(entry)
                        for entry in value
                        if isinstance(entry, dict) and entry.get("id")
                    ]
                elif (
                    isinstance(value, dict)
                    and isinstance(value.get("version"), int)
                    and not isinstance(value.get("version"), bool)
                    and value.get("version") in {3, 4}
                    and isinstance(value.get("vocab"), list)
                    and isinstance(value.get("entries"), list)
                ):
                    vocab = value["vocab"]
                    key_vocab = value.get("keys") if value.get("version") == 4 else None
                    if key_vocab is not None and (
                        not isinstance(key_vocab, list)
                        or any(not isinstance(key, str) for key in key_vocab)
                    ):
                        key_vocab = None
                    decoded = _decode_history_strings(value["entries"], vocab, key_vocab)
                    marker_entries = [
                        _safe_history_entry(entry)
                        for entry in decoded
                        if isinstance(entry, dict) and entry.get("id")
                    ]
            except json.JSONDecodeError:
                marker_entries = None
    try:
        rows = _parse_history_rows(body)
    except ValueError:
        if marker_entries:
            return marker_entries
        raise
    if not marker_entries:
        return rows
    by_id = {entry.get("id"): entry for entry in marker_entries}
    # The table is the recoverable presentation. If a hidden scope block was
    # truncated, retain its finding row and explicitly degrade scope.
    for row in rows:
        by_id.setdefault(row["id"], row)
    return list(by_id.values())


def _sort_key(entry: dict) -> tuple[str, str]:
    identity = entry.get("identity", {})
    started = _parse_time(identity.get("started_at"), "0000-00-00T00:00:00Z")
    return started, str(entry.get("id", ""))


def _comparison(current: dict, previous: dict | None) -> dict:
    if previous is None:
        return {"status": "unavailable", "reason": "no chronological predecessor"}
    if current.get("findings") is None or previous.get("findings") is None:
        return {"status": "unavailable", "reason": "current or predecessor is incomplete/unknown"}
    reasons = []
    numeric = []
    current_scope = current.get("scope") if isinstance(current.get("scope"), dict) else {}
    previous_scope = previous.get("scope") if isinstance(previous.get("scope"), dict) else {}
    if current_scope.get("status") != "available" or previous_scope.get("status") != "available":
        return {"status": "unavailable", "reason": "current or predecessor scope evidence unavailable"}
    current_operational = current_scope.get("operational_error")
    previous_operational = previous_scope.get("operational_error")
    if (current.get("outcome") != "success" and current_operational is not False) or (
        previous.get("outcome") != "success" and previous_operational is not False
    ):
        reasons.append("incomplete attempt is not a stable baseline")
    if current.get("identity", {}).get("mode") != previous.get("identity", {}).get("mode"):
        reasons.append("scan mode changed")
    current_tools = current_scope.get("tools") if isinstance(current_scope.get("tools"), dict) else {}
    previous_tools = previous_scope.get("tools") if isinstance(previous_scope.get("tools"), dict) else {}
    for name in sorted(set(current_tools) | set(previous_tools)):
        now_tool = current_tools.get(name) if isinstance(current_tools.get(name), dict) else {}
        old_tool = previous_tools.get(name) if isinstance(previous_tools.get(name), dict) else {}
        for label in ("requested", "state", "outcome", "mode", "effective"):
            if now_tool.get(label) != old_tool.get(label):
                reasons.append(f"{name} {label} changed")
        effective = now_tool.get("effective") or {}
        old_effective = old_tool.get("effective") or {}
        if not effective or not old_effective:
            reasons.append(f"{name} comparison metadata unavailable")
        else:
            comparison_meta = effective.get("comparison")
            old_comparison_meta = old_effective.get("comparison")
            if (isinstance(comparison_meta, dict) and comparison_meta.get("status") != "complete") or (
                isinstance(old_comparison_meta, dict) and old_comparison_meta.get("status") != "complete"
            ):
                reasons.append(f"{name} comparison metadata incomplete")
            if not any(key in effective for key in ("config_fingerprint", "content_fingerprint")) or not any(
                key in old_effective for key in ("config_fingerprint", "content_fingerprint")
            ):
                reasons.append(f"{name} configuration fingerprint unavailable")
        for key in ("examined", "unparsed", "policy_excluded"):
            now_measurements = now_tool.get("measurements") if isinstance(now_tool.get("measurements"), dict) else {}
            old_measurements = old_tool.get("measurements") if isinstance(old_tool.get("measurements"), dict) else {}
            now_m = now_measurements.get(key) if isinstance(now_measurements.get(key), dict) else {}
            old_m = old_measurements.get(key) if isinstance(old_measurements.get(key), dict) else {}
            if not now_m and key in now_tool.get("not_applicable", []):
                now_m = {"status": "not_applicable"}
            if not old_m and key in old_tool.get("not_applicable", []):
                old_m = {"status": "not_applicable"}
            if now_m.get("status") == "known" and old_m.get("status") == "known":
                if now_m.get("unit") != old_m.get("unit") or now_m.get("method") != old_m.get("method"):
                    reasons.append(f"{name} {key} units/method changed")
                else:
                    change = now_m.get("count", 0) - old_m.get("count", 0)
                    numeric.append((name, key, change, now_m.get("unit", "unknown")))
                    if key == "examined" and change < 0:
                        reasons.append(f"{name} examined scope smaller")
                    elif key in {"unparsed", "policy_excluded"} and change > 0:
                        label = "analysis gaps" if key == "unparsed" else "observed policy exclusions"
                        reasons.append(f"{name} more {label}")
            elif now_m.get("status") != old_m.get("status"):
                reasons.append(f"{name} {key} availability changed")
        now_native_data = now_tool.get("native") if isinstance(now_tool.get("native"), dict) else {}
        old_native_data = old_tool.get("native") if isinstance(old_tool.get("native"), dict) else {}
        now_native = now_native_data.get("component_count") if isinstance(now_native_data.get("component_count"), dict) else {}
        old_native = old_native_data.get("component_count") if isinstance(old_native_data.get("component_count"), dict) else {}
        if now_native.get("status") == "known" and old_native.get("status") == "known":
            if now_native.get("unit") != old_native.get("unit") or now_native.get("method") != old_native.get("method"):
                reasons.append(f"{name} native component units/method changed")
            else:
                numeric.append((name, "native component_count", now_native.get("count", 0) - old_native.get("count", 0), now_native.get("unit", "unknown")))
        elif now_native.get("status") != old_native.get("status"):
            reasons.append(f"{name} native component count availability changed")
    finding_delta = current["findings"] - previous["findings"]
    return {"status": "qualified" if reasons else "stable", "finding_delta": finding_delta, "scope_deltas": numeric, "reasons": reasons}


def _display_scope(scope: dict, scope_error: str | None) -> list[str]:
    lines = ["### Analysis scope", ""]
    if scope_error or scope.get("status") != "available":
        lines.append(f"Scope evidence unavailable: {_one_line(scope_error or scope.get('reason', 'unknown'))}.")
        return lines + [""]
    tools = scope.get("tools") if isinstance(scope.get("tools"), dict) else {}
    lines += [
        f"Outcome: **{scope.get('outcome', 'unknown')}**; collection: **{scope.get('collection', 'unknown')}**.",
        f"Complete evidence artifact: [{scope.get('artifact', 'layer2-scope.json')}]({scope['artifact_link']})." if scope.get("artifact_link") else f"Complete evidence artifact: `{scope.get('artifact', 'layer2-scope.json')}`.",
        "",
        "| Tool | State | Outcome | Examined | Unparsed | Policy-excluded |",
        "|---|---|---|---:|---:|---:|",
    ]
    for name, record in sorted(tools.items()):
        if not isinstance(record, dict):
            record = {}
        def cell(key: str) -> str:
            measurement = record.get("measurements", {}).get(key, {})
            if measurement.get("status") == "known":
                return f"{measurement.get('count')} `{measurement.get('unit', 'unknown')}`"
            if measurement.get("status") == "not_applicable":
                return "not applicable"
            if key in record.get("not_applicable", []):
                return "not applicable"
            return f"unknown ({_one_line(measurement.get('reason', 'unavailable'), 70)})"
        lines.append(f"| {name} | {record.get('state', 'unknown')} | {record.get('outcome', 'unknown')} | {cell('examined')} | {cell('unparsed')} | {cell('policy_excluded')} |")
        native = record.get("native", {}).get("component_count", {}) if isinstance(record.get("native"), dict) else {}
        if native.get("status") == "known":
            lines.append(f"| ↳ native inventory |  |  | {native.get('count')} `{native.get('unit', 'dependency_component')}` |  |  |")
        diagnostic = record.get("diagnostic")
        if diagnostic:
            lines.append(f"| ↳ diagnostic |  |  | {diagnostic} |  |  |")
    if "semgrep" in tools:
        lines += [
            "",
            "Semgrep `examined` is scanner-reported attempted target scope; `unparsed` is an overlapping analysis-gap count.",
        ]
    if scope.get("diagnostic"):
        lines += ["", f"Analysis diagnostic: {scope['diagnostic']}"]
    return lines + [""]


def _decode_history_strings(value: object, vocab: list[object], key_vocab: list[object] | None = None) -> object:
    if isinstance(value, dict):
        decoded = {}
        for key, item in value.items():
            decoded_key = key
            if key_vocab is not None and isinstance(key, str):
                if key.startswith("@@k") and re.fullmatch(r"@@k\d+", key):
                    decoded_key = key[1:]
                else:
                    match = re.fullmatch(r"@k(\d+)", key)
                    if match and int(match.group(1)) < len(key_vocab) and isinstance(key_vocab[int(match.group(1))], str):
                        decoded_key = key_vocab[int(match.group(1))]
            decoded[decoded_key] = _decode_history_strings(item, vocab, key_vocab)
        return decoded
    if isinstance(value, list):
        return [_decode_history_strings(item, vocab, key_vocab) for item in value]
    if isinstance(value, str):
        if value.startswith("~~"):
            return value[1:]
        match = re.fullmatch(r"~(\d+)", value)
        if match and int(match.group(1)) < len(vocab) and isinstance(vocab[int(match.group(1))], str):
            return vocab[int(match.group(1))]
    return value


def _history_payload(entries: list[dict]) -> str:
    frequencies: collections.Counter[str] = collections.Counter()
    ordered: list[str] = []
    key_frequencies: collections.Counter[str] = collections.Counter()
    key_ordered: list[str] = []

    def collect(value: object) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if isinstance(key, str):
                    key_frequencies[key] += 1
                    if key not in key_ordered:
                        key_ordered.append(key)
                collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)
        elif isinstance(value, str):
            frequencies[value] += 1
            if value not in ordered:
                ordered.append(value)

    collect(entries)
    vocab = [value for value in ordered if frequencies[value] > 1][:MAX_HISTORY_VOCAB]
    tokens = {value: f"~{index}" for index, value in enumerate(vocab)}
    key_vocab = [value for value in key_ordered if key_frequencies[value] > 1]
    key_tokens = {value: f"@k{index}" for index, value in enumerate(key_vocab)}

    def intern(value: object) -> object:
        if isinstance(value, dict):
            compact = {}
            for key, item in value.items():
                compact_key = key_tokens.get(key, key) if isinstance(key, str) else key
                if isinstance(compact_key, str) and re.fullmatch(r"@k\d+", compact_key) and compact_key not in key_tokens.values():
                    compact_key = f"@{compact_key}"
                compact[compact_key] = intern(item)
            return compact
        if isinstance(value, list):
            return [intern(item) for item in value]
        if isinstance(value, str):
            if value in tokens:
                return tokens[value]
            if re.fullmatch(r"~\d+", value):
                return f"~{value}"
        return value

    payload = {"version": 4, "keys": key_vocab, "vocab": vocab, "entries": intern(entries)}
    # HTML comments cannot contain "--". JSON escapes retain the exact value
    # while preventing tool text from closing or nesting the hidden comment.
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).replace("--", "\\u002d\\u002d")


def _artifact_link(repository: str, identity: dict, artifact: str) -> str | None:
    run_id = str(identity.get("run_id", ""))
    if "/" not in repository or not run_id or run_id == "unknown":
        return None
    return f"https://github.com/{repository}/actions/runs/{run_id}/artifacts"


def _presentation(
    counts: collections.Counter,
    gitleaks: str,
    osv: str,
    licenses: str,
    sbom: tuple[int, collections.Counter[str]] | None,
    unparsed: list[str] | None,
    scan_error: str | None,
) -> dict:
    """Retain the newest report view so an older completion cannot mix runs."""
    result = {
        "counts": {str(rule): int(count) for rule, count in counts.items()},
        "gitleaks": _one_line(gitleaks, 180),
        "osv": _one_line(osv, 180),
        "licenses": _one_line(licenses, 180),
        "unparsed": [_one_line(path, 180) for path in (unparsed or [])[:MAX_UNPARSED_ROWS]],
        "unparsed_total": len(unparsed or []),
        "scan_error": _one_line(scan_error, MAX_DIAGNOSTIC_EXCERPT) if scan_error else "",
    }
    if sbom:
        components, license_counts = sbom
        result["sbom"] = {
            "components": int(components),
            "licenses": {str(name): int(count) for name, count in license_counts.items()},
        }
    return result


def build(counts, date, gitleaks, osv, previous, target, licenses="not run",
          sbom=None, scan_error=None, unparsed=None, *, scope=None, scope_error=None,
          args=None) -> str:
    total = sum(counts.values())
    top = counts.most_common(1)[0] if counts else None
    top_txt = f"{top[0]} ({top[1]})" if top else "—"
    args = args or argparse.Namespace(run_id="unknown", run_attempt="unknown", started_at="", commit="unknown", ref="unknown", mode="full", baseline_ref="")
    identity = _scope_identity(scope, args)
    if not identity.get("started_at"):
        identity["started_at"] = _parse_time(args.started_at, f"{date}T00:00:00Z")
    scope_analysis = scope.get("analysis", {}) if isinstance(scope, dict) and isinstance(scope.get("analysis", {}), dict) else {}
    analysis_outcome = scope_analysis.get("outcome") if isinstance(scope_analysis.get("outcome"), str) else "unknown"
    entry_outcome = "failure" if scan_error or analysis_outcome in {"failure", "cancelled"} else (
        "incomplete" if scope is not None and analysis_outcome not in {"success", "failure", "cancelled"} else "success"
    )
    entry = {
        "id": _entry_id(identity, date), "legacy": False, "identity": identity,
        "findings": None if scan_error else total, "largest": top_txt,
        "outcome": entry_outcome,
        "scope": _compact_scope(scope, scope_error),
        "presentation": _presentation(counts, gitleaks, osv, licenses, sbom, unparsed, scan_error),
    }
    link = _artifact_link(target, identity, entry["scope"].get("artifact", "layer2-scope.json"))
    if link:
        entry["scope"]["artifact_link"] = link

    retained = [old for old in (previous or []) if old.get("id") != entry.get("id")]
    retained.append(entry)
    retained.sort(key=_sort_key)
    retained = retained[-MAX_HISTORY:]
    current = retained[-1]
    # One rich presentation is enough: it is only needed for the current entry.
    # Keeping it on every row would let a realistic 52-entry body grow without
    # bound, while dropping it from the newest row would mix an older completion
    # with the current run's tool statuses and parse-gap paths.
    for item in retained:
        if item.get("id") != current.get("id"):
            item.pop("presentation", None)
    predecessor = retained[-2] if len(retained) > 1 else None
    comparison = _comparison(current, predecessor)
    rendering_current = current.get("id") == entry.get("id")
    display_identity = current.get("identity", identity)
    current_presentation = current.get("presentation", {})
    display_error = current_presentation.get("scan_error") or (
        "previous attempt failed/incomplete" if current.get("findings") is None else None
    )
    display_total = current.get("findings") or 0
    display_gitleaks = current_presentation.get("gitleaks", "unknown")
    display_osv = current_presentation.get("osv", "unknown")
    display_licenses = current_presentation.get("licenses", "unknown")
    display_counts = collections.Counter(current_presentation.get("counts", {}))
    display_unparsed = current_presentation.get("unparsed", [])
    display_sbom = current_presentation.get("sbom")
    if not current_presentation and rendering_current:
        display_gitleaks, display_osv, display_licenses = gitleaks, osv, licenses
        display_counts = counts
        display_unparsed = unparsed or []
        display_sbom = (
            {"components": sbom[0], "licenses": dict(sbom[1])} if sbom else None
        )
    display_scope = _display_scope_data(scope, scope_error) if rendering_current else current.get("scope", {"status": "unknown", "reason": "scope unavailable"})
    if rendering_current and link:
        display_scope["artifact_link"] = link

    lines = [
        MARKER,
        f"# Quality backlog — `{target}`",
        "",
        "Standing report from the [maxi-quality]"
        "(https://github.com/maximalcode/maxi-quality) baseline. "
        "**Updated in place — do not close.**",
        "",
        "PRs are gated on *new* findings only (the ratchet). This report shows "
        "the current full Layer 2 run and its scope beside the findings.",
        "",
    ]

    if display_error:
        lines += [
            f"> ⚠️ **The Semgrep scan for {display_identity.get('started_at', date)} ERRORED and produced no usable "
            f"result: {_one_line(display_error)}**",
            ">",
            "> This attempt is retained as failed/incomplete. It is not a zero-finding baseline.",
            "",
        ]

    semgrep_cell = f"**ERRORED** — {_one_line(display_error)}" if display_error else f"**{display_total}** findings"
    lines += [
        f"## Current — {display_identity.get('started_at', date)} ({display_identity.get('run_id', 'unknown')}/{display_identity.get('run_attempt', 'unknown')})",
        "",
        "| Tool | Result |",
        "|---|---|",
        f"| Semgrep | {semgrep_cell} |",
        f"| Gitleaks | {display_gitleaks} |",
        f"| OSV-Scanner | {display_osv} |",
        f"| Licenses | {display_licenses} |",
        "",
    ]

    if display_error:
        # NOT "No Semgrep findings." — that sentence is the bug in prose form.
        lines.append("No Semgrep breakdown: the scan did not complete.")
    elif display_counts:
        lines += ["### Semgrep by rule", "", "| Rule | Count |", "|---|---:|"]
        lines += [f"| `{rule}` | {n} |" for rule, n in display_counts.most_common()]
    elif display_total:
        lines.append(f"Semgrep findings retained from the current run: **{display_total}**.")
    else:
        lines.append("No Semgrep findings.")
    lines.append("")

    # #43 — the number that used to be invisible in both directions. Before
    # this, an unparseable file blanked the report as ERRORED; the fix must not
    # swing to the other extreme and simply not mention it, because a file
    # nothing ran against is not a file with no findings.
    if display_unparsed:
        lines += [
            "### Not scanned",
            "",
            f"{current_presentation.get('unparsed_total', len(display_unparsed))} file(s) Semgrep reported with analysis gaps. "
            "These paths overlap the scanner-reported attempted target scope; "
            "the gap evidence is not a claim that no rule ran against every path.",
            "",
            "| File |",
            "|---|",
        ]
        lines += [f"| `{p}` |" for p in display_unparsed[:MAX_UNPARSED_ROWS]]
        if current_presentation.get("unparsed_total", len(display_unparsed)) > MAX_UNPARSED_ROWS:
            # Said out loud, because a truncated list that does not say it was
            # truncated reads as the whole list.
            lines.append(f"| …and {current_presentation['unparsed_total'] - MAX_UNPARSED_ROWS} more |")
        lines.append("")

    if display_sbom:
        n_components, license_counts = display_sbom["components"], collections.Counter(display_sbom["licenses"])
        unknown = license_counts.get("UNKNOWN", 0)
        lines += [
            "## Dependencies",
            "",
            f"{n_components} resolved components (CycloneDX 1.6 SBOM attached to "
            "the run that produced this report).",
            "",
            "| License | Components |",
            "|---|---:|",
        ]
        lines += [f"| `{lic}` | {n} |" for lic, n in license_counts.most_common()]
        if unknown:
            lines += [
                "",
                f"{unknown} component(s) declare no license. That is the row "
                "worth reading — first-party workspace packages land here too, "
                "so check which before treating it as a risk.",
            ]
        lines.append("")

    lines += _display_scope(display_scope, None if rendering_current else display_scope.get("reason"))
    lines += ["### Comparison with previous run", ""]
    if comparison.get("status") == "unavailable":
        lines.append(f"Comparison unavailable: {comparison['reason']}.")
    else:
        finding_text = f"{comparison.get('finding_delta', 0):+d} findings"
        if comparison.get("status") == "qualified":
            finding_text += " — qualified because checking conditions or scope changed"
        lines.append(f"Findings: {finding_text}.")
        for name, key, change, unit in comparison.get("scope_deltas", []):
            if change:
                lines.append(f"{name} {key}: {change:+d} `{unit}`.")
        if comparison.get("reasons"):
            lines.append("Conditions: " + "; ".join(comparison["reasons"]) + ".")
    lines.append("")

    lines += [
        HISTORY_DATA_START,
        "<!--\n" + _history_payload(retained) + "\n-->",
        HISTORY_DATA_END,
        HISTORY_HEADING,
        "",
        "Retention is the latest 52 execution entries, not 52 calendar days.",
        "",
        "| Run | Attempt | Started | Outcome | Findings |",
        "|---|---|---|---|---:|",
    ]
    for item in reversed(retained):
        item_identity = item.get("identity", {})
        findings = item.get("findings")
        lines.append(f"| {item_identity.get('run_id', 'legacy')} | {item_identity.get('run_attempt', 'unknown')} | {item_identity.get('started_at') or 'unknown'} | {_one_line(item.get('outcome', 'unknown'), 30)} | {findings if findings is not None else 'ERRORED'} |")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", required=True, help="Semgrep --json-out file")
    ap.add_argument("--date", required=True)
    ap.add_argument("--scope", help="same-run layer2-scope.json artifact")
    ap.add_argument("--run-id", default="")
    ap.add_argument("--run-attempt", default="")
    ap.add_argument("--invocation-id", default="")
    ap.add_argument("--started-at", default="")
    ap.add_argument("--commit", default="")
    ap.add_argument("--ref", default="")
    ap.add_argument("--mode", default="full")
    ap.add_argument("--baseline-ref", default="")
    ap.add_argument("--target", default="repository")
    ap.add_argument("--gitleaks", default="not run")
    ap.add_argument("--osv", default="not run")
    ap.add_argument("--licenses", default="not run")
    ap.add_argument("--sbom", help="CycloneDX 1.6 SBOM (optional)")
    ap.add_argument("--previous-body", help="File holding the current issue body")
    args = ap.parse_args()

    body = None
    if args.previous_body:
        try:
            with open(args.previous_body) as fh:
                body = fh.read()
        except OSError as exc:
            # An explicitly supplied previous body is the standing issue's
            # durable history. Treating a read failure as a fresh issue would
            # allow the action to erase it; a genuinely new issue omits this
            # option entirely.
            print(f"error: cannot read previous report body: {exc}", file=sys.stderr)
            return 3

    scope, scope_error = load_scope(args.scope)
    if scope is not None:
        scope_identity = scope.get("identity", {})
        expected_run = args.run_id or ""
        expected_attempt = args.run_attempt or ""
        expected_invocation = args.invocation_id or ""
        expected_commit = args.commit or ""
        invalid_scope = (
            scope_identity.get("producer") != "report"
            or scope_identity.get("mode") != "full"
            or (expected_run and str(scope_identity.get("run_id")) != str(expected_run))
            or (expected_attempt and str(scope_identity.get("run_attempt")) != str(expected_attempt))
            or (expected_invocation and str(scope_identity.get("invocation_id")) != str(expected_invocation))
            or (expected_commit and str(scope_identity.get("commit")) != str(expected_commit))
        )
        if invalid_scope:
            scope = None
            scope_error = "scope identity does not match this report run/attempt/producer/mode/commit"
    try:
        counts, scan_error, unparsed = load_findings(args.json)
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        # A valid own-run scope can prove that the scanner/setup failed before
        # its normal JSON handoff. Keep that attempt in history as failed,
        # while an absent or malformed scope retains the old refusal boundary.
        scope_outcome = (
            scope.get("analysis", {}).get("outcome")
            if scope is not None and isinstance(scope.get("analysis"), dict)
            else "unknown"
        )
        if isinstance(scope_outcome, str) and scope_outcome in {"failure", "cancelled"}:
            counts, scan_error, unparsed = collections.Counter(), "scanner result unavailable; scope records a failed/incomplete attempt", []
        else:
            print(f"error: cannot read Semgrep results from {args.json}: {exc}", file=sys.stderr)
            return 3
    if scope is not None:
        if scan_error is None and _scope_has_operational_error(scope):
            scan_error = _scope_operational_reason(scope)
    try:
        prior = previous_history(body)
    except ValueError as exc:
        # Nothing is printed on this path, deliberately: the caller writes
        # stdout over the standing issue, and an empty body would erase the
        # history this script exists to keep.
        print(f"error: cannot read previous report history: {exc}", file=sys.stderr)
        return 3

    print(
        build(
            counts,
            args.date,
            args.gitleaks,
            args.osv,
            prior,
            args.target,
            args.licenses,
            load_sbom(args.sbom),
            scan_error,
            unparsed,
            scope=scope,
            scope_error=scope_error,
            args=args,
        )
    )
    if scan_error:
        # Body first, THEN the failure. The issue has to show the outage; the
        # exit code is what makes the run red so somebody looks.
        print(f"error: {scan_error} — reported as ERRORED, not as a clean scan", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
