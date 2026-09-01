#!/usr/bin/env python3
"""Preview Layer 1 in a disposable copy. This command always exits zero.

The report, not the process status, says whether analysis completed. Toolchain
failures and unknown rule classifications must never look like a clean scan.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Never

BASELINE = Path(__file__).resolve().parent.parent
SKIP = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    "bin",
    "obj",
    "target",
    "dist",
    "build",
    "coverage",
}
LANGUAGES = ("typescript", "python", "dotnet", "rust", "java")


@dataclass
class Check:
    language: str
    tool: str
    project: str = "."
    status: str = "complete"
    detail: str = ""
    findings: list[tuple[str, str, int, int]] = field(default_factory=list)


class UnavailableError(Exception):
    """An analysis could not run to completion; never a finding."""


class Arguments(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        raise UnavailableError(message)


def run(command: list[str], cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(  # noqa: S603 -- fixed tool argv; the target is never shell-expanded
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise UnavailableError(str(exc)) from exc


def snapshot(source: Path, destination: Path) -> None:
    """Copy dependencies too; never let a symlink write back into the original."""
    shutil.copytree(
        source, destination, symlinks=True, ignore=lambda _directory, names: set(names) & SKIP
    )
    for directory, dirs, files in os.walk(destination, followlinks=False):
        for name in dirs + files:
            copied = Path(directory) / name
            if not copied.is_symlink():
                continue
            original = source / copied.relative_to(destination)
            resolved = original.resolve()
            if not resolved.is_relative_to(source):
                raise UnavailableError(
                    f"external symlink: {original.relative_to(source)}; "
                    "use a self-contained checkout"
                )
            copied.unlink()
            copied.symlink_to(
                os.path.relpath(destination / resolved.relative_to(source), copied.parent)
            )


def source_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for directory, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = sorted(
            d
            for d in dirs
            if d not in SKIP | {"node_modules"} and not (Path(directory) / d).is_symlink()
        )
        files.extend(Path(directory) / name for name in sorted(names))
    return files


def failure(result: subprocess.CompletedProcess[str]) -> str:
    return (result.stderr or result.stdout or f"tool exited {result.returncode}")[-2000:].strip()


def format_check(
    language: str,
    tool: str,
    project: str,
    files: list[Path],
    command: list[str],
    cwd: Path,
    timeout: int,
) -> Check:
    """Count changed files, never formatted lines, in the disposable copy only."""
    check = Check(language, tool, project)
    try:
        before = {file: file.read_bytes() for file in files}
        result = run(command, cwd, timeout)
        for file, content in before.items():
            if file.read_bytes() != content:
                check.findings.append(("format", str(file), 0, 0))
            # A later compiler must see the original source, even in the copy.
            file.write_bytes(content)
        if result.returncode:
            check.status, check.detail = "incomplete", failure(result)
    except (UnavailableError, OSError) as exc:
        check.status, check.detail = "unavailable", str(exc)
    return check


def python_checks(root: Path, files: list[Path], timeout: int) -> list[Check]:
    if not any(f.suffix in {".py", ".pyi"} for f in files):
        return []
    checks = []
    # Use the active environment: imports and stubs are part of the adopter's
    # toolchain. Explicit configs prevent a permissive project config winning.
    for tool, command in (
        (
            "ruff",
            [
                "ruff",
                "check",
                "--no-cache",
                "--output-format=json",
                "--config",
                str(BASELINE / "configs/python/ruff.toml"),
                ".",
            ],
        ),
        (
            "ruff-format",
            [
                "ruff",
                "format",
                "--check",
                "--no-cache",
                "--output-format=json",
                "--config",
                str(BASELINE / "configs/python/ruff.toml"),
                ".",
            ],
        ),
        (
            "mypy",
            [
                "mypy",
                "--config-file",
                str(BASELINE / "configs/python/mypy.ini"),
                "--output=json",
                "--no-incremental",
                ".",
            ],
        ),
    ):
        check = Check("python", tool)
        checks.append(check)
        try:
            result = run(command, root, timeout)
            records = (
                [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
                if tool == "mypy"
                else json.loads(result.stdout)
            )
            if not isinstance(records, list):
                raise UnavailableError("expected a diagnostic list")
            for item in records:
                if tool == "mypy":
                    if item["severity"] != "error":
                        continue
                    rule, path, line, col = (
                        item.get("code"),
                        item["file"],
                        item["line"],
                        item["column"],
                    )
                    if rule in {"import-not-found", "import-untyped", "syntax", None}:
                        check.status = "incomplete"
                        check.detail = (
                            "Missing imports/stubs or syntax errors; resolve these and rerun."
                        )
                else:
                    rule = "format" if tool == "ruff-format" else item.get("code")
                    path = item["filename"]
                    line, col = item["location"]["row"], item["location"]["column"]
                    if not rule or rule == "invalid-syntax":
                        check.status = "incomplete"
                        check.detail = "Syntax errors prevented full analysis."
                check.findings.append((rule or "unparsed", path, line, col))
            if result.returncode not in (0, 1) or (result.returncode and not records):
                check.status, check.detail = "incomplete", failure(result)
        except (UnavailableError, ValueError, KeyError, TypeError) as exc:
            check.status, check.detail = "unavailable", str(exc)
    return checks


def typescript_checks(root: Path, files: list[Path], timeout: int) -> list[Check]:
    if not any(
        f.name == "package.json" or f.suffix in {".ts", ".tsx", ".mts", ".cts"} for f in files
    ):
        return []
    try:
        if any(f.name in {"yarn.lock", "bun.lock", "bun.lockb"} for f in files):
            raise UnavailableError(
                "TypeScript supports npm and pnpm; yarn and bun are unsupported."
            )
        result = run(
            ["node", str(BASELINE / "scripts/preflight-typescript.mjs"), str(root)], root, timeout
        )
        if result.returncode:
            raise UnavailableError(failure(result))
        return [
            Check(
                "typescript",
                item["tool"],
                status=item["status"],
                detail=item["detail"],
                findings=[tuple(f) for f in item["findings"]],
            )
            for item in json.loads(result.stdout)
        ]
    except (UnavailableError, ValueError, KeyError, TypeError) as exc:
        return [Check("typescript", "typescript", status="unavailable", detail=str(exc))]


def rust_checks(root: Path, files: list[Path], timeout: int) -> list[Check]:
    manifests = [f for f in files if f.name == "Cargo.toml"]
    # Cargo's own metadata identifies workspace members; a nested manifest is
    # not assumed to belong to its nearest ancestor's workspace.
    checked = set()
    checks = []
    lint_tables = tomllib.loads((BASELINE / "configs/rust/lints.toml").read_text())["workspace"][
        "lints"
    ]
    flags = []
    for family, rules in lint_tables.items():
        for name, value in sorted(
            rules.items(),
            key=lambda item: item[1].get("priority", 0) if isinstance(item[1], dict) else 0,
        ):
            level = value["level"] if isinstance(value, dict) else value
            flags.extend(["--" + level, ("clippy::" if family == "clippy" else "") + name])
    for manifest in manifests:
        check = Check("rust", "clippy", str(manifest.parent.relative_to(root)))
        try:
            metadata = run(
                [
                    "cargo",
                    "metadata",
                    "--no-deps",
                    "--format-version=1",
                    "--manifest-path",
                    str(manifest),
                ],
                root,
                timeout,
            )
            if metadata.returncode:
                raise UnavailableError(failure(metadata))
            workspace = Path(json.loads(metadata.stdout)["workspace_root"])
            if workspace in checked:
                continue
            checked.add(workspace)
            check.project = str(workspace.relative_to(root))
            result = run(
                [
                    "cargo",
                    "clippy",
                    "--workspace",
                    "--all-targets",
                    "--locked",
                    "--message-format=json",
                    "--",
                    *flags,
                    "-D",
                    "warnings",
                ],
                workspace,
                timeout,
            )
            finished = False
            for line in result.stdout.splitlines():
                item = json.loads(line)
                if item.get("reason") == "build-finished":
                    finished = True
                if item.get("reason") != "compiler-message":
                    continue
                message = item["message"]
                code = (message.get("code") or {}).get("code")
                for span in message["spans"]:
                    if code and span["is_primary"] and message["level"] in {"error", "warning"}:
                        check.findings.append(
                            (
                                code,
                                str(workspace / span["file_name"]),
                                span["line_start"],
                                span["column_start"],
                            )
                        )
            if result.returncode or not finished:
                check.status = "incomplete"
                check.detail = "Compilation stopped; these are lower-bound counts. " + failure(
                    result
                )
            checks.append(
                format_check(
                    "rust",
                    "rustfmt",
                    check.project,
                    [f for f in files if f.suffix == ".rs"],
                    [
                        "cargo",
                        "fmt",
                        "--all",
                        "--",
                        "--config-path",
                        str(BASELINE / "configs/rust/rustfmt.toml"),
                    ],
                    workspace,
                    timeout,
                )
            )
        except (UnavailableError, ValueError, KeyError, TypeError) as exc:
            check.status, check.detail = "unavailable", str(exc)
        checks.append(check)
    return checks


def dotnet_checks(root: Path, files: list[Path], timeout: int) -> list[Check]:
    projects = [f for f in files if f.suffix == ".csproj"]
    checks = []
    reports = root / ".preflight-roslyn"
    if projects:
        reports.mkdir()
    for index, project in enumerate(projects):
        tree = ET.parse(project)  # noqa: S314 -- local build input, already trusted to execute
        node = tree.getroot()
        ns = node.tag.removesuffix("Project")
        packages = ET.SubElement(node, ns + "ItemGroup")
        ET.SubElement(
            packages, ns + "PackageReference", Remove="SonarAnalyzer.CSharp;Roslynator.Analyzers"
        )
        ET.SubElement(
            node, ns + "Import", Project=str(BASELINE / "configs/dotnet/Directory.Build.props")
        )
        group = ET.SubElement(node, ns + "PropertyGroup")
        ET.SubElement(group, ns + "ErrorLog").text = (
            str(reports / f"{index}-$(TargetFramework).sarif") + ",version=2.1"
        )
        tree.write(project, encoding="unicode")
        editor = project.parent / ".editorconfig"
        editor.write_text(
            (BASELINE / "configs/editorconfig").read_text()
            + "\n"
            + (BASELINE / "configs/dotnet/dotnet.editorconfig").read_text()
        )
    for project in projects:
        check = Check("dotnet", "roslyn", str(project.relative_to(root)))
        checks.append(check)
        try:
            # All projects have independent SARIF paths, including referenced
            # projects and target frameworks. Clear reports before each build.
            for sarif in reports.glob("*.sarif"):
                sarif.unlink()
            result = run(
                [
                    "dotnet",
                    "build",
                    str(project),
                    "--no-incremental",
                    "--nologo",
                ],
                project.parent,
                timeout,
            )
            if not list(reports.glob("*.sarif")):
                raise UnavailableError("No compiler SARIF report. " + failure(result))
            for sarif in reports.glob("*.sarif"):
                for analysis in json.loads(sarif.read_text())["runs"]:
                    for item in analysis.get("results", []):
                        if item.get("suppressions") or item.get("level") not in {
                            "error",
                            "warning",
                        }:
                            continue
                        location = item.get("locations", [{}])[0].get("physicalLocation", {})
                        region = location.get("region", {})
                        check.findings.append(
                            (
                                item["ruleId"],
                                location.get("artifactLocation", {}).get("uri", ""),
                                region.get("startLine", 0),
                                region.get("startColumn", 0),
                            )
                        )
            if result.returncode:
                check.status, check.detail = (
                    "incomplete",
                    "Build stopped; these are lower-bound counts. " + failure(result),
                )
            checks.append(
                format_check(
                    "dotnet",
                    "dotnet-format",
                    check.project,
                    [f for f in files if f.suffix == ".cs"],
                    ["dotnet", "format", "whitespace", str(project), "--no-restore"],
                    project.parent,
                    timeout,
                )
            )
        except (UnavailableError, OSError, ValueError, KeyError, TypeError, ET.ParseError) as exc:
            check.status, check.detail = "unavailable", str(exc)
    return checks


def java_checks(root: Path, files: list[Path], timeout: int) -> list[Check]:
    checks = []
    if any(f.name in {"build.gradle", "build.gradle.kts"} for f in files):
        checks.append(
            Check("java", "gradle", status="unavailable", detail="Java preflight is Maven-only.")
        )
    for pom in (f for f in files if f.name == "pom.xml"):
        check = Check("java", "javac", str(pom.relative_to(root)))
        checks.append(check)
        try:
            # Reuse the adoption merger and its conflict refusal. Guessing how
            # to merge an existing compiler plugin would report another build.
            prepared = run(
                [
                    sys.executable,
                    str(BASELINE / "scripts/pom-region.py"),
                    "apply",
                    "--pom",
                    str(pom),
                    "--fragment",
                    str(BASELINE / "configs/java/pom-lints.xml"),
                ],
                pom.parent,
                timeout,
            )
            if prepared.returncode:
                raise UnavailableError(
                    "Baseline needs a manual POM merge in a disposable checkout. "
                    + failure(prepared)
                )
            result = run(
                ["mvn", "-B", "--no-transfer-progress", "-Dstyle.color=never", "test-compile"],
                pom.parent,
                timeout,
            )
            log = re.sub(r"\x1b\[[0-9;]*m", "", result.stdout + result.stderr)
            for match in re.finditer(
                r"^\[(?:ERROR|WARNING)\]\s+(.+?\.java):\[(\d+),(\d+)\]\s+\[([\w.]+)\]",
                log,
                re.MULTILINE,
            ):
                check.findings.append((match[4], match[1], int(match[2]), int(match[3])))
            if result.returncode:
                check.status = "incomplete"
                check.detail = "Compilation stopped; these are lower-bound counts. " + failure(
                    result
                )
                if "warnings found and -Werror specified" in log:
                    check.detail = (
                        "javac warnings can stop Error Prone before it runs. " + check.detail
                    )
            checks.append(
                format_check(
                    "java",
                    "spotless",
                    check.project,
                    [f for f in files if f.suffix == ".java"],
                    ["mvn", "-B", "--no-transfer-progress", "spotless:apply"],
                    pom.parent,
                    timeout,
                )
            )
        except (UnavailableError, OSError, ValueError) as exc:
            check.status, check.detail = "unavailable", str(exc)
    return checks


def report(checks: list[Check], root: Path) -> dict[str, Any]:
    mapping = json.loads((BASELINE / "scripts/preflight-rules.json").read_text())
    languages: dict[str, Any] = {}
    seen = set()
    for check in checks:
        language = languages.setdefault(
            check.language,
            {"status": "complete", "checks": [], "counts": Counter(), "rules": Counter()},
        )
        if check.status != "complete":
            language["status"] = "incomplete"
        language["checks"].append(
            {
                "tool": check.tool,
                "project": check.project,
                "status": check.status,
                "detail": check.detail.replace(str(root), "<preview>"),
            }
        )
        for rule, path, line, column in check.findings:
            identity = (check.language, check.tool, rule, path, line, column)
            if identity in seen:
                continue
            seen.add(identity)
            key = check.tool + "/" + rule
            category = mapping.get(key, "unclassified")
            language["counts"][category] += 1
            language["rules"][(key, category)] += 1
    for language in languages.values():
        language["counts"] = {
            name: language["counts"][name] for name in ("bug-class", "stylistic", "unclassified")
        }
        language["rules"] = [
            {"rule": rule, "class": category, "count": count}
            for (rule, category), count in sorted(language["rules"].items())
        ]
    return {
        "schema": 1,
        "status": "complete"
        if languages and all(lang["status"] == "complete" for lang in languages.values())
        else "incomplete",
        "languages": languages,
        "note": "Counts are diagnostics, not confirmed bugs. Incomplete counts are lower bounds. "
        "Unclassified rules have no reviewed mapping. Formatting counts files. "
        "Optional dead-code checks and dependency audits are not measured.",
    }


def render(data: dict[str, Any]) -> str:
    lines = ["Layer 1 preflight — report only", "Status: " + data["status"], "", data["note"], ""]
    for name, language in data["languages"].items():
        counts = language["counts"]
        lines.append(
            f"{name}: {language['status']} — "
            + ", ".join(
                f"{counts[key]} {key}" for key in ("bug-class", "stylistic", "unclassified")
            )
        )
        for rule in language["rules"]:
            lines.append(f"  {rule['count']:6}  {rule['class']:12}  {rule['rule']}")
        for check in language["checks"]:
            lines.append(f"  {check['tool']} ({check['project']}): {check['status']}")
            if check["detail"]:
                # Indent each line: external tool output must not become an
                # Actions ::error:: annotation when this runs in a shell step.
                lines.extend("    " + line for line in check["detail"].splitlines())
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = Arguments(description=__doc__)
    parser.add_argument("target", type=Path)
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument(
        "--timeout", type=int, default=180, help="seconds per tool invocation (default: 180)"
    )
    args = parser.parse_args()
    if args.timeout <= 0:
        raise UnavailableError("--timeout must be positive")
    source = args.target.resolve(strict=True)
    if not source.is_dir():
        raise UnavailableError("target must be a directory")
    with tempfile.TemporaryDirectory(prefix="maxi-preflight-") as temporary:
        # macOS exposes the same temp tree through /var and /private/var.
        # Roslyn matches analyzer-config paths textually; use one spelling.
        root = (Path(temporary) / "repo").resolve()
        snapshot(source, root)
        files = source_files(root)
        checks = []
        for language, adapter in zip(
            LANGUAGES,
            (typescript_checks, python_checks, dotnet_checks, rust_checks, java_checks),
            strict=True,
        ):
            try:
                checks.extend(adapter(root, files, args.timeout))
            except (
                UnavailableError,
                OSError,
                ValueError,
                KeyError,
                TypeError,
                ET.ParseError,
            ) as exc:
                checks.append(Check(language, language, status="unavailable", detail=str(exc)))
        data = report(checks, root)
        if not checks:
            data["note"] = "No supported source/project files found; nothing was measured."
        print(json.dumps(data, indent=2) if args.format == "json" else render(data))


if __name__ == "__main__":
    try:
        main()
    except (Exception, KeyboardInterrupt) as error:  # the public command must never gate
        data = {
            "schema": 1,
            "status": "incomplete",
            "languages": {},
            "note": "Preflight unavailable: " + str(error),
        }
        with contextlib.suppress(OSError, KeyboardInterrupt):
            print(json.dumps(data) if "json" in sys.argv else render(data), flush=True)
    # Includes argparse --help. No tool, input, or analysis error is a gate.
    finally:
        try:
            sys.stdout.flush()
        except OSError:
            # Python otherwise changes an explicit exit(0) to 120 when its
            # shutdown flush encounters a closed pipe (for example `| head`).
            with open(os.devnull, "w") as sink:
                os.dup2(sink.fileno(), sys.stdout.fileno())
        sys.exit(0)
