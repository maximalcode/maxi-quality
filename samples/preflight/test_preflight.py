"""Exercise the public preflight command against the existing sample contract.

Run with a language name, or `contract` for tool-independent failure cases.
The original fixtures and their expectation manifests are never edited.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

BASELINE = Path(__file__).resolve().parents[2]
COMMAND = [sys.executable, str(BASELINE / "scripts/preflight.py")]


def contents(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink()
    }


def preview(target: Path, *args: str, env: dict[str, str] | None = None) -> dict[str, Any]:
    before = contents(target)
    result = subprocess.run(  # noqa: S603 -- fixed public CLI, with fixture-only arguments
        [*COMMAND, str(target), "--format", "json", *args],
        capture_output=True,
        text=True,
        check=False,
        env=env,
        timeout=300,
    )
    assert result.returncode == 0, result.stderr
    assert contents(target) == before, "preflight changed the original tree"
    data: dict[str, Any] = json.loads(result.stdout)
    return data


def check_manifest(data: dict[str, Any], language: str, tool: str, manifest: str) -> None:
    expected = json.loads((BASELINE / f"samples/expected/{manifest}.json").read_text())
    counts = Counter(f["rule"] for f in expected["findings"])
    actual = {
        r["rule"].removeprefix(tool + "/"): r["count"]
        for r in data["languages"][language]["rules"]
        if r["rule"].startswith(tool + "/")
    }
    assert actual == dict(counts), (actual, counts, data)


def prepare(name: str, target: Path) -> None:
    shutil.copytree(
        BASELINE / "samples" / name,
        target,
        ignore=shutil.ignore_patterns(
            "bin",
            "obj",
            "target",
            "node_modules",
            "dist",
            "__pycache__",
            ".ruff_cache",
            ".mypy_cache",
        ),
    )
    if name.startswith("typescript"):
        # Replace only sample-harness wiring, which imports ../../configs.
        # Source bytes stay identical; explicit strict:false proves the preview
        # imposes the baseline on an unadopted project.
        (target / "tsconfig.json").write_text(
            json.dumps(
                {"compilerOptions": {"strict": False, "types": ["node"]}, "include": ["src"]}
            )
        )
        (target / "eslint.config.mjs").unlink(missing_ok=True)
        # README describes the test harness, not the clean source's formatter
        # contract. Project JSON is normalized after replacing harness wiring.
        (target / "README.md").unlink(missing_ok=True)
        format_harness(target, ["tsconfig.json", "package.json"])
        for dependency in ("@types/node", "undici-types"):
            shutil.copytree(
                BASELINE / "node_modules" / dependency, target / "node_modules" / dependency
            )
    if name.startswith("dotnet"):
        # The sample's props imports an ancestor outside this copied project.
        # A real adopter starts without that test-harness-only import.
        (target / "Directory.Build.props").unlink()


def format_harness(target: Path, names: list[str]) -> None:
    node = shutil.which("node")
    assert node is not None, "TypeScript fixtures need Node"
    subprocess.run(  # noqa: S603 -- pinned baseline formatter on generated harness files only
        [
            node,
            str(BASELINE / "node_modules/prettier/bin/prettier.cjs"),
            "--config",
            str(BASELINE / "configs/typescript/prettier.config.mjs"),
            "--write",
            *(str(target / name) for name in names),
        ],
        capture_output=True,
        check=True,
    )


def language_case(language: str, temporary: Path) -> None:
    name = language
    for suffix in ("", "-clean"):
        target = temporary / (name + suffix)
        prepare(name + suffix, target)
        data = preview(target)
        result = data["languages"][language]
        if suffix:
            assert result["status"] == "complete", data
            assert result["counts"] == {"bug-class": 0, "stylistic": 0, "unclassified": 0}, data
        else:
            for tool, manifest in {
                "python": [("ruff", "ruff"), ("mypy", "mypy")],
                "typescript": [("eslint", "eslint")],
                "dotnet": [("roslyn", "dotnet")],
                "rust": [("clippy", "clippy")],
                "java": [("javac", "java")],
            }[language]:
                check_manifest(data, language, tool, manifest)
            assert result["counts"]["bug-class"] > 0, data
            if language == "python":
                assert result["counts"] == {"bug-class": 13, "stylistic": 12, "unclassified": 0}, (
                    data
                )
    if language == "python":
        target = temporary / "permissive"
        target.mkdir()
        (target / "bad.py").write_text("def append(value, items=[]):\n    items.append(value)\n")
        (target / "ruff.toml").write_text("[lint]\nselect = []\n")
        data = preview(target)
        assert any(r["rule"] == "ruff/B006" for r in data["languages"]["python"]["rules"]), data


def inherited_typescript(temporary: Path) -> None:
    target = temporary / "browser"
    target.mkdir()
    (target / "app.ts").write_text("export const title: string = document.title;\n")
    (target / "tsconfig.base.json").write_text(
        json.dumps(
            {
                "compilerOptions": {
                    "module": "esnext",
                    "moduleResolution": "bundler",
                    "lib": ["es2023", "dom"],
                    "types": [],
                }
            }
        )
    )
    (target / "tsconfig.json").write_text(
        json.dumps({"extends": "./tsconfig.base.json", "include": ["app.ts"]})
    )
    format_harness(target, ["tsconfig.json", "tsconfig.base.json"])
    data = preview(target)
    assert data["languages"]["typescript"]["counts"] == {
        "bug-class": 0,
        "stylistic": 0,
        "unclassified": 0,
    }, data
    (target / "ignored.ts").write_text("export const value:number=1;\n")
    (target / ".prettierignore").write_text("ignored.ts\n")
    (target / "data.json").write_text('{"answer":42}')
    data = preview(target)
    formatting = [
        r for r in data["languages"]["typescript"]["rules"] if r["rule"] == "prettier/format"
    ]
    assert formatting == [{"rule": "prettier/format", "class": "stylistic", "count": 1}], data


def contract(temporary: Path) -> None:
    target = temporary / "project"
    target.mkdir()
    read_fd, write_fd = os.pipe()
    os.close(read_fd)
    with os.fdopen(write_fd, "w") as output:
        result = subprocess.run(  # noqa: S603 -- fixed public command against an empty fixture
            [*COMMAND, str(target)], stdout=output, stderr=subprocess.PIPE, check=False
        )
    assert result.returncode == 0, result.stderr
    for arguments in ([], ["--unknown"], ["--timeout", "0"], ["--timeout", "no"]):
        assert preview(target, *arguments)["status"] == "incomplete"
    missing = preview(temporary / "does-not-exist")
    assert missing["status"] == "incomplete"
    (target / "app.py").write_text("x = 1\n")
    tools = temporary / "tools"
    tools.mkdir()
    env = {**os.environ, "PATH": str(tools)}
    data = preview(target, env=env)
    assert data["status"] == "incomplete", data
    assert all(c["status"] == "unavailable" for c in data["languages"]["python"]["checks"]), data
    # A tool can fail or return malformed JSON, even with a successful exit.
    for body in ("print('not-json')", "raise SystemExit(2)"):
        executable = tools / "ruff"
        executable.write_text(f"#!{sys.executable}\n{body}\n")
        executable.chmod(0o755)
        assert preview(target, env=env)["status"] == "incomplete"
    # Unknown rule IDs are retained and never silently classified as style.
    executable.write_text(
        f"#!{sys.executable}\nimport json,sys\n"
        "print(json.dumps([] if 'format' in sys.argv else "
        "[{'code':'FUTURE999','filename':'app.py','location':{'row':1,'column':1}}]))\n"
    )
    data = preview(target, env=env)
    assert data["languages"]["python"]["counts"]["unclassified"] == 1, data
    executable.write_text(f"#!{sys.executable}\nimport time\ntime.sleep(30)\n")
    assert preview(target, "--timeout", "1", env=env)["status"] == "incomplete"
    external = temporary / "outside.py"
    external.write_text("untouched\n")
    (target / "link.py").symlink_to(external)
    data = preview(target)
    assert "external symlink" in data["note"], data
    assert external.read_text() == "untouched\n"


if __name__ == "__main__":
    mode = sys.argv[1]
    with tempfile.TemporaryDirectory(prefix="preflight-selftest-") as directory:
        temporary = Path(directory)
        if mode == "contract":
            contract(temporary)
        else:
            language_case(mode, temporary)
            if mode == "typescript":
                inherited_typescript(temporary)
    sys.stdout.write(f"OK: preflight {mode}\n")
