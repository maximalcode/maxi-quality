#!/usr/bin/env python3
"""Write and render the versioned Layer 2 scope evidence contract.

The scanner is a shell program because its tool invocations must remain
transparent. This small standard-library boundary owns the JSON shape and
diagnostic preservation so shell quoting cannot turn an error into a fake
clean result.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import posixpath
import re
import sys
import tempfile
from typing import Any

try:
    from policy import PER_FILE_ERROR_TYPES, error_type
except ImportError:  # pragma: no cover - only useful when imported elsewhere
    PER_FILE_ERROR_TYPES = frozenset()

    def error_type(error: dict[str, Any]) -> str:
        raw = error.get("type")
        return str(raw[0]) if isinstance(raw, list) and raw else str(raw)


TOOLS = ("semgrep", "gitleaks", "osv", "licenses", "sbom")
MEASUREMENTS = ("examined", "unparsed", "policy_excluded")
UNIT = {
    "examined": "target_path",
    "unparsed": "target_path",
    "policy_excluded": "target_path",
}


def now() -> str:
    return (
        dt.datetime.now(dt.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def unknown_measurement(
    reason: str = "measurement unavailable",
    *,
    unit: str = "source_file",
) -> dict[str, Any]:
    return {
        "status": "unknown",
        "count": None,
        "unit": unit,
        "method": "scanner-native evidence",
        "reason": reason,
    }


def known_measurement(
    count: int,
    *,
    unit: str,
    method: str,
    reason: str,
) -> dict[str, Any]:
    return {
        "status": "known",
        "count": count,
        "unit": unit,
        "method": method,
        "reason": reason,
    }


def tool_record(name: str, *, requested: bool, reason: str) -> dict[str, Any]:
    state = "unknown" if requested else "not_applicable"
    # Applicability belongs to state. Outcome is reserved for what happened
    # when an invocation was considered: success, failure, cancellation, or
    # unknown when it did not run or its result cannot be established.
    outcome = "unknown"
    unit = "target_path" if name == "semgrep" else "source_file"
    measurements = {
        key: unknown_measurement(
            f"unsupported native {key} count for {name}; this unit is not exposed",
            unit=unit,
        )
        for key in MEASUREMENTS
    }
    if not requested:
        for measurement in measurements.values():
            measurement["status"] = "not_applicable"
            measurement["reason"] = "optional invocation disabled"
    return {
        "name": name,
        "requested": requested,
        "state": state,
        "outcome": outcome,
        "reason": reason,
        "reason_code": "requested" if requested else "disabled",
        "mode": {},
        "effective": {},
        "exit_code": None,
        "measurements": measurements,
        "diagnostics": [],
    }


def base_document(args: argparse.Namespace) -> dict[str, Any]:
    identity = {
        "producer": args.producer,
        "workflow": args.workflow,
        "invocation_id": args.invocation_id,
        "run_id": args.run_id,
        "run_attempt": args.run_attempt,
        "job": args.job,
        "fragment_id": args.fragment_id
        or f"{args.producer}:{args.run_id}:{args.run_attempt}:{args.job}",
        "commit": args.commit,
        "ref": args.ref,
        "mode": args.mode,
        "started_at": now(),
    }
    if args.baseline_ref:
        identity["baseline_ref"] = args.baseline_ref
    licenses = args.licenses_requested == "true"
    sbom = args.sbom_requested == "true"
    return {
        "schema_version": 1,
        "kind": "layer2-scope",
        "identity": identity,
        "analysis": {
            "outcome": "unknown",
            "exit_code": None,
            "findings": None,
            "diagnostics": [],
        },
        "collection": {"status": "in_progress", "issues": [], "finalized_at": None},
        "tools": {
            "semgrep": tool_record(
                "semgrep", requested=True, reason="scanner invocation requested"
            ),
            "gitleaks": tool_record(
                "gitleaks", requested=True, reason="scanner invocation requested"
            ),
            "osv": tool_record("osv", requested=True, reason="scanner invocation requested"),
            "licenses": tool_record(
                "licenses", requested=licenses,
                reason=(
                    "optional license invocation requested"
                    if licenses
                    else "optional license invocation disabled"
                ),
            ),
            "sbom": tool_record(
                "sbom", requested=sbom,
                reason=(
                    "optional SBOM invocation requested"
                    if sbom
                    else "optional SBOM invocation disabled"
                ),
            ),
        },
        "summary": {"artifact": str(pathlib.Path(args.out).name), "lines": []},
    }


def read_doc(path: str) -> dict[str, Any]:
    try:
        with open(path, encoding="utf-8") as fh:
            value = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read scope artifact {path}: {exc}") from exc
    if value.get("kind") != "layer2-scope" or value.get("schema_version") != 1:
        raise ValueError(f"unsupported scope artifact contract in {path}")
    return value


def write_doc(path: str, doc: dict[str, Any]) -> None:
    destination = pathlib.Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", dir=str(destination.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(temporary, destination)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def cmd_init(args: argparse.Namespace) -> int:
    destination = pathlib.Path(args.out)
    candidate = base_document(args)
    if destination.exists():
        try:
            existing = read_doc(args.out)
        except ValueError:
            existing = None
        if existing is not None and all(
            existing.get("identity", {}).get(key) == candidate["identity"].get(key)
            for key in (
                "producer",
                "workflow",
                "invocation_id",
                "run_id",
                "run_attempt",
                "job",
                "fragment_id",
                "commit",
                "ref",
                "mode",
                "baseline_ref",
            )
        ):
            # The action initializes before setup, while scan.sh initializes
            # again after setup. Keep the same own-run identity and evidence.
            return 0
    write_doc(args.out, candidate)
    return 0


def cmd_record(args: argparse.Namespace) -> int:
    doc = read_doc(args.out)
    if args.tool not in doc["tools"]:
        raise ValueError(f"unknown Layer 2 tool {args.tool!r}")
    record = doc["tools"][args.tool]
    record["state"] = args.state
    record["outcome"] = args.outcome
    record["reason"] = args.reason
    if args.reason_code:
        record["reason_code"] = args.reason_code
    record["exit_code"] = args.exit_code
    mode = {}
    if args.mode:
        mode["scope"] = args.mode
    if args.baseline_ref:
        mode["baseline_ref"] = args.baseline_ref
    if args.fallback:
        mode["fallback"] = args.fallback
    if args.resolution:
        mode["resolution"] = args.resolution
    record["mode"].update(mode)
    if args.effective_json:
        try:
            effective = json.loads(pathlib.Path(args.effective_json).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            doc["collection"]["issues"].append(
                f"effective metadata unavailable for {args.tool}: {exc}"
            )
        else:
            if isinstance(effective, dict):
                record["effective"].update(effective)
            else:
                doc["collection"]["issues"].append(
                    f"effective metadata malformed for {args.tool}: expected object"
                )
    for log in args.log:
        log_path = pathlib.Path(log)
        try:
            text = log_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            doc["collection"]["issues"].append(f"diagnostic unavailable for {args.tool}: {exc}")
            continue
        if text:
            record["diagnostics"].append(
                {"stream": args.stream, "source": str(log_path), "text": text}
            )
    if args.diagnostic:
        record["diagnostics"].append(
            {"stream": args.stream, "source": "scanner", "text": args.diagnostic}
        )
    for issue in args.collection_issue:
        doc["collection"]["issues"].append(issue)
    write_doc(args.out, doc)
    return 0


def normalized_target_path(
    raw: Any,
    scan_root: pathlib.Path,
    scanner_root: pathlib.Path,
) -> str | None:
    """Normalize Semgrep's relative/native/container path to target-relative form."""
    if not isinstance(raw, str) or not raw:
        return None
    scan_root = scan_root.resolve()
    scanner_root = scanner_root.resolve()
    candidate = pathlib.PurePosixPath(raw)
    if candidate.is_absolute():
        absolute = pathlib.Path(raw).resolve()
        try:
            relative = absolute.relative_to(scanner_root)
        except ValueError:
            try:
                relative = absolute.relative_to(scan_root)
            except ValueError:
                # A path outside the known target cannot be compared safely.
                return None
    else:
        # Semgrep emits paths relative to the scan working directory. Normalize
        # lexical ``.``/``..`` segments before comparing them with native or
        # container absolute paths from the same target.
        relative = pathlib.Path(posixpath.normpath(raw))
    normalized = pathlib.Path(relative).as_posix()
    if normalized in ("", ".") or normalized == ".." or normalized.startswith("../"):
        return None
    return normalized


def _path_measurement(
    paths: Any,
    *,
    scan_root: pathlib.Path,
    scanner_root: pathlib.Path,
    reason: str,
) -> dict[str, Any]:
    if not isinstance(paths, list):
        return unknown_measurement(
            f"{reason}: Semgrep paths list is missing or malformed",
            unit="target_path",
        )
    normalized = set()
    for raw in paths:
        path = normalized_target_path(raw, scan_root, scanner_root)
        if path is None:
            return unknown_measurement(
                f"{reason}: Semgrep emitted an invalid target path",
                unit="target_path",
            )
        normalized.add(path)
    return known_measurement(
        len(normalized),
        unit="target_path",
        method="unique normalized paths from Semgrep JSON",
        reason=reason,
    )


def semgrep_measurements(
    data: Any,
    *,
    scan_root: pathlib.Path,
    scanner_root: pathlib.Path,
) -> dict[str, dict[str, Any]]:
    """Extract only evidence Semgrep 1.172.0 actually emitted."""
    if not isinstance(data, dict):
        return {
            key: unknown_measurement(
                "Semgrep JSON root is not an object", unit="target_path"
            )
            for key in MEASUREMENTS
        }
    paths = data.get("paths")
    if not isinstance(paths, dict):
        return {
            key: unknown_measurement(
                "Semgrep JSON paths object is missing or malformed",
                unit="target_path",
            )
            for key in MEASUREMENTS
        }

    examined = _path_measurement(
        paths.get("scanned"),
        scan_root=scan_root,
        scanner_root=scanner_root,
        reason="scanner-reported attempted target paths",
    )

    errors = data.get("errors")
    if not isinstance(errors, list):
        unparsed = unknown_measurement(
            "Semgrep JSON errors list is missing or malformed",
            unit="target_path",
        )
    else:
        unparsed_paths = []
        malformed = False
        for error in errors:
            if not isinstance(error, dict):
                malformed = True
                break
            if error_type(error) in PER_FILE_ERROR_TYPES:
                path = normalized_target_path(
                    error.get("path"), scan_root, scanner_root
                )
                if path is None:
                    malformed = True
                    break
                unparsed_paths.append(path)
        if malformed:
            unparsed = unknown_measurement(
                "Semgrep per-file error evidence is malformed",
                unit="target_path",
            )
        else:
            unparsed = known_measurement(
                len(set(unparsed_paths)),
                unit="target_path",
                method="unique normalized paths in policy.py per-file errors",
                reason="Semgrep per-file parse, timeout, or memory error paths",
            )

    skipped = paths.get("skipped")
    if not isinstance(skipped, list):
        excluded = unknown_measurement(
            "Semgrep verbose skip metadata is absent or malformed; exclusions unknown",
            unit="target_path",
        )
    else:
        excluded_paths = []
        malformed = False
        for item in skipped:
            if not isinstance(item, dict):
                malformed = True
                break
            if item.get("reason") != "cli_exclude_flags_match":
                continue
            path = normalized_target_path(item.get("path"), scan_root, scanner_root)
            if path is None:
                malformed = True
                break
            excluded_paths.append(path)
        if malformed:
            excluded = unknown_measurement(
                "Semgrep CLI-exclusion skip evidence is malformed",
                unit="target_path",
            )
        else:
            excluded = known_measurement(
                len(set(excluded_paths)),
                unit="target_path",
                method="unique normalized whole-target paths in Semgrep paths.skipped",
                reason="Semgrep explicitly attributed these paths to CLI exclusions",
            )
    return {
        "examined": examined,
        "unparsed": unparsed,
        "policy_excluded": excluded,
    }


def _content_record(path: pathlib.Path, label: str) -> dict[str, str]:
    return {
        "path": label,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def effective_config_metadata(
    policy: Any,
    *,
    scan_root: pathlib.Path,
    baseline_root: pathlib.Path,
) -> dict[str, Any]:
    """Fingerprint active rule/config content without embedding checkout paths."""
    if not isinstance(policy, dict):
        return {
            "status": "incomplete",
            "reason": "effective policy evidence is not an object",
        }
    files: list[dict[str, str]] = []
    missing: list[str] = []
    groups = policy.get("groups")
    if not isinstance(groups, list) or not all(isinstance(group, str) for group in groups):
        missing.append("selected Semgrep rule groups")
    else:
        for group in groups:
            directory = baseline_root / "semgrep" / group
            if not directory.is_dir():
                missing.append(f"semgrep/{group}")
                continue
            for path in sorted(p for p in directory.rglob("*") if p.is_file()):
                try:
                    files.append(_content_record(path, path.relative_to(baseline_root).as_posix()))
                except OSError:
                    missing.append(path.relative_to(baseline_root).as_posix())
    extends = policy.get("extends")
    if extends:
        if not isinstance(extends, str):
            missing.append("consumer extends path")
        else:
            directory = scan_root / extends
            if not directory.is_dir():
                missing.append(f"consumer/{extends}")
            else:
                for path in sorted(p for p in directory.rglob("*") if p.is_file()):
                    try:
                        label = pathlib.Path("consumer") / path.relative_to(directory)
                        files.append(_content_record(path, label.as_posix()))
                    except OSError:
                        missing.append(f"consumer/{extends}")

    ignores: list[dict[str, str]] = []
    for name in (".semgrepignore", ".gitignore"):
        for path in sorted(scan_root.rglob(name)):
            try:
                ignores.append(_content_record(path, path.relative_to(scan_root).as_posix()))
            except OSError:
                missing.append(path.relative_to(scan_root).as_posix())
    # Semgrep's built-in ignore set is active even when no local file exists;
    # retain that fact as metadata rather than presenting a missing local file
    # as evidence that no ignore policy was applied.
    portable_policy = dict(policy)
    rule_args = portable_policy.get("exclude_rule_args")
    if isinstance(rule_args, list):
        portable_policy["exclude_rule_args"] = [
            re.sub(r"^.*?\.semgrep\.", "BASELINE.semgrep.", value)
            if isinstance(value, str)
            else value
            for value in rule_args
        ]
    payload = {
        "policy": portable_policy,
        "rules": files,
        "ignores": ignores,
        "default_ignores": "semgrep-1.172.0-defaults",
    }
    normalized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    content_fingerprint = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    # Git's global excludes and environment-level ignore configuration are
    # outside the scanner target and are not exposed by this invocation. Keep
    # that limitation explicit so two absent values cannot produce a stable
    # comparison identity.
    missing.append("global Git ignore configuration")
    if missing:
        return {
            "status": "incomplete",
            "reason": "effective Semgrep configuration evidence unavailable: "
            + ", ".join(sorted(set(missing))),
            "ignore_sources": ignores,
            "unknown_sources": ["global Git ignore configuration"],
            "content_fingerprint": content_fingerprint,
        }
    return {
        "status": "complete",
        "config_fingerprint": content_fingerprint,
        "ignore_sources": ignores,
    }


def cmd_measure_semgrep(args: argparse.Namespace) -> int:
    doc = read_doc(args.out)
    record = doc["tools"]["semgrep"]
    try:
        data = json.loads(pathlib.Path(args.results).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        measurements = {
            key: unknown_measurement(
                f"Semgrep result evidence unavailable: {exc}", unit="target_path"
            )
            for key in MEASUREMENTS
        }
        data = None
    else:
        measurements = semgrep_measurements(
            data,
            scan_root=pathlib.Path(args.scan_root),
            scanner_root=pathlib.Path(args.scanner_root or args.scan_root),
        )
    record["measurements"].update(measurements)
    effective = record.setdefault("effective", {})
    effective["tool"] = "semgrep"
    version = data.get("version") if isinstance(data, dict) else None
    effective["version"] = version if isinstance(version, str) and version else None
    effective["diagnostic_mode"] = "verbose"
    if args.policy:
        try:
            policy = json.loads(pathlib.Path(args.policy).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            doc["collection"]["issues"].append(f"Semgrep policy metadata unavailable: {exc}")
        else:
            if isinstance(policy, dict):
                portable_policy = dict(policy)
                rule_args = portable_policy.get("exclude_rule_args")
                if isinstance(rule_args, list):
                    portable_policy["exclude_rule_args"] = [
                        re.sub(r"^.*?\.semgrep\.", "BASELINE.semgrep.", value)
                        if isinstance(value, str)
                        else value
                        for value in rule_args
                    ]
                effective["policy"] = portable_policy
                effective["comparison"] = effective_config_metadata(
                    policy,
                    scan_root=pathlib.Path(args.scan_root),
                    baseline_root=pathlib.Path(args.baseline_root or args.scan_root),
                )
                comparison = effective["comparison"]
                fingerprint = comparison.get("content_fingerprint") or comparison.get(
                    "config_fingerprint"
                )
                if fingerprint:
                    effective["config_fingerprint"] = fingerprint
                else:
                    effective.pop("config_fingerprint", None)
            else:
                doc["collection"]["issues"].append(
                    "Semgrep policy metadata malformed: expected object"
                )
    record["mode"]["scope"] = args.mode
    if args.baseline_ref:
        record["mode"]["baseline_ref"] = args.baseline_ref
    doc["summary"]["lines"] = render_lines(doc)
    write_doc(args.out, doc)
    return 0


def cmd_finalize(args: argparse.Namespace) -> int:
    doc = read_doc(args.out)
    doc["analysis"].update({"outcome": args.analysis_outcome, "exit_code": args.analysis_exit_code})
    if args.diagnostic:
        doc["analysis"]["diagnostics"].append(
            {"stream": args.stream, "source": "scan", "text": args.diagnostic}
        )
    if args.log:
        try:
            text = pathlib.Path(args.log).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            doc["collection"]["issues"].append(f"scan diagnostics unavailable: {exc}")
        else:
            if text:
                doc["analysis"]["diagnostics"].append(
                    {"stream": args.stream, "source": args.log, "text": text}
                )
    status = args.collection_status
    if doc["collection"]["issues"] and status == "complete":
        status = "partial"
    doc["collection"].update({"status": status, "finalized_at": now()})
    doc["summary"]["lines"] = render_lines(doc)
    write_doc(args.out, doc)
    return 0


def cmd_diagnostic(args: argparse.Namespace) -> int:
    doc = read_doc(args.out)
    if args.section not in ("analysis", "collection"):
        raise ValueError(f"unsupported diagnostic section {args.section!r}")
    try:
        text = pathlib.Path(args.log).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        doc["collection"]["issues"].append(f"diagnostic unavailable for {args.source}: {exc}")
    else:
        if text:
            if args.section == "analysis":
                doc["analysis"]["diagnostics"].append(
                    {"stream": args.stream, "source": args.source, "text": text}
                )
            else:
                doc["collection"]["issues"].append(f"{args.source}: {clip(text)}")
    doc["summary"]["lines"] = render_lines(doc)
    write_doc(args.out, doc)
    return 0


def clip(value: str, limit: int = 220) -> str:
    one_line = " ".join(value.split()).replace("|", "\\|")
    replacements = (
        ("&", "&amp;"),
        ("<", "&lt;"),
        (">", "&gt;"),
        ("`", "\\`"),
        ("*", "\\*"),
        ("_", "\\_"),
        ("[", "\\["),
        ("]", "\\]"),
    )
    for source, escaped in replacements:
        one_line = one_line.replace(source, escaped)
    return one_line if len(one_line) <= limit else one_line[: limit - 3] + "..."


def render_lines(doc: dict[str, Any]) -> list[str]:
    lines = [
        f"Layer 2 scope: {doc['analysis']['outcome']} (collection {doc['collection']['status']})",
        f"Evidence artifact: {doc['summary'].get('artifact', 'layer2-scope.json')}",
    ]
    for name in TOOLS:
        record = doc["tools"][name]
        detail = record["reason"]
        if record["diagnostics"]:
            detail += "; diagnostic: " + record["diagnostics"][0].get("text", "")
        lines.append(f"{name}: {record['state']} / {record['outcome']} — {clip(detail)}")
        if name == "semgrep":
            measurements = record.get("measurements", {})
            parts = []
            for key, label in (
                ("examined", "attempted"),
                ("unparsed", "unparsed (overlapping)"),
                ("policy_excluded", "policy-excluded"),
            ):
                measurement = measurements.get(key, {})
                value = (
                    str(measurement.get("count"))
                    if measurement.get("status") == "known"
                    else "unknown"
                )
                parts.append(f"{label}={value} {measurement.get('unit', 'target_path')}")
            lines.append("semgrep measurements: " + "; ".join(parts))
    if doc["analysis"]["diagnostics"]:
        lines.append(
            "analysis diagnostic: "
            + clip(doc["analysis"]["diagnostics"][0].get("text", ""))
        )
    if doc["collection"]["issues"]:
        lines.append("collection: " + clip("; ".join(doc["collection"]["issues"])))
    return lines


def cmd_summary(args: argparse.Namespace) -> int:
    doc = read_doc(args.out)
    for line in doc.get("summary", {}).get("lines") or render_lines(doc):
        print(line)  # noqa: T201 — CLI summary output
    return 0


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    init.add_argument("--out", required=True)
    for name in (
        "producer",
        "workflow",
        "invocation-id",
        "run-id",
        "run-attempt",
        "job",
        "commit",
        "ref",
        "mode",
    ):
        init.add_argument(f"--{name}", required=True)
    init.add_argument("--fragment-id", default="")
    init.add_argument("--baseline-ref", default="")
    init.add_argument("--licenses-requested", choices=("true", "false"), default="false")
    init.add_argument("--sbom-requested", choices=("true", "false"), default="false")
    init.set_defaults(func=cmd_init)

    record = sub.add_parser("record")
    record.add_argument("--out", required=True)
    record.add_argument("--tool", choices=TOOLS, required=True)
    record.add_argument(
        "--state",
        choices=("run", "skipped", "not_applicable", "unknown"),
        required=True,
    )
    record.add_argument(
        "--outcome",
        choices=("success", "failure", "cancelled", "unknown"),
        required=True,
    )
    record.add_argument("--exit-code", type=int)
    record.add_argument("--reason", required=True)
    record.add_argument("--reason-code", default="")
    record.add_argument("--mode", default="")
    record.add_argument("--baseline-ref", default="")
    record.add_argument("--fallback", default="")
    record.add_argument("--resolution", default="")
    record.add_argument("--effective-json", default="")
    record.add_argument("--log", action="append", default=[])
    record.add_argument("--stream", default="combined")
    record.add_argument("--diagnostic", default="")
    record.add_argument("--collection-issue", action="append", default=[])
    record.set_defaults(func=cmd_record)

    measure = sub.add_parser("measure-semgrep")
    measure.add_argument("--out", required=True)
    measure.add_argument("--results", required=True)
    measure.add_argument("--scan-root", required=True)
    measure.add_argument("--scanner-root", default="")
    measure.add_argument("--baseline-root", default="")
    measure.add_argument("--policy", default="")
    measure.add_argument("--mode", choices=("full", "changed-only"), required=True)
    measure.add_argument("--baseline-ref", default="")
    measure.set_defaults(func=cmd_measure_semgrep)

    final = sub.add_parser("finalize")
    final.add_argument("--out", required=True)
    final.add_argument(
        "--analysis-outcome",
        choices=("success", "failure", "cancelled", "unknown"),
        required=True,
    )
    final.add_argument("--analysis-exit-code", type=int)
    final.add_argument(
        "--collection-status",
        choices=("complete", "partial", "failed", "unknown"),
        required=True,
    )
    final.add_argument("--log", default="")
    final.add_argument("--stream", default="combined")
    final.add_argument("--diagnostic", default="")
    final.set_defaults(func=cmd_finalize)

    diagnostic = sub.add_parser("diagnostic")
    diagnostic.add_argument("--out", required=True)
    diagnostic.add_argument("--section", choices=("analysis", "collection"), required=True)
    diagnostic.add_argument("--stream", default="combined")
    diagnostic.add_argument("--source", required=True)
    diagnostic.add_argument("--log", required=True)
    diagnostic.set_defaults(func=cmd_diagnostic)

    summary = sub.add_parser("summary")
    summary.add_argument("--out", required=True)
    summary.set_defaults(func=cmd_summary)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        return args.func(args)
    except (OSError, ValueError) as exc:
        print(f"layer2 scope: {exc}", file=sys.stderr)  # noqa: T201 — CLI diagnostic
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
