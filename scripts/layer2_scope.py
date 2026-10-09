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
import json
import os
import pathlib
import sys
import tempfile
from typing import Any


TOOLS = ("semgrep", "gitleaks", "osv", "licenses", "sbom")
MEASUREMENTS = ("examined", "unparsed", "policy_excluded")
UNIT = {
    "examined": "source_file",
    "unparsed": "source_file",
    "policy_excluded": "source_file",
}


def now() -> str:
    return (
        dt.datetime.now(dt.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def unknown_measurement(
    reason: str = "not instrumented in Layer 2 scope collection",
) -> dict[str, Any]:
    return {
        "status": "unknown",
        "count": None,
        "unit": "source_file",
        "method": "scanner-native evidence; counter instrumentation pending",
        "reason": reason,
    }


def tool_record(name: str, *, requested: bool, reason: str) -> dict[str, Any]:
    state = "unknown" if requested else "not_applicable"
    # Applicability belongs to state. Outcome is reserved for what happened
    # when an invocation was considered: success, failure, cancellation, or
    # unknown when it did not run or its result cannot be established.
    outcome = "unknown"
    measurements = {key: unknown_measurement() for key in MEASUREMENTS}
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
    record.add_argument("--log", action="append", default=[])
    record.add_argument("--stream", default="combined")
    record.add_argument("--diagnostic", default="")
    record.add_argument("--collection-issue", action="append", default=[])
    record.set_defaults(func=cmd_record)

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
