#!/usr/bin/env python3
"""Dispatch the versioned agent guard from an immutable local cache.

Consumers carry only a data lock and hook wiring.  This launcher is installed
outside consumer repositories; ``prepare`` is the only operation that writes
the cache.  Hook invocations never fetch or mutate it.

The cache deliberately has no ``current`` or ``latest`` pointer.  A repository
selects one complete release with ``.claude/quality-runtime.json`` and two
repositories may select different commits from the same cache.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SOURCE = "maximalcode/maxi-quality"
SCHEMA = 1
LOCK_NAME = ".claude/quality-runtime.json"
FORMAT = 1
SCRIPTS = (
    "guard.py",
    "stop-gate.py",
    "sample-guard.py",
    "no-verify-guard.py",
    "record-gate.py",
)
SCRIPT_SET = frozenset(SCRIPTS)
SHA = re.compile(r"^[0-9a-f]{40}$")
VERSION = re.compile(r"^v?[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$")


class RuntimeError_(Exception):
    """A user-fixable lock or cache problem."""


def cache_root(explicit: str | None = None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    configured = os.environ.get("MAXI_QUALITY_RUNTIME_CACHE")
    if configured:
        return Path(configured).expanduser().resolve()
    xdg = os.environ.get("XDG_CACHE_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".cache"
    return (base / "maxi-quality" / "runtime").resolve()


def _json(path: Path) -> object:
    try:
        with path.open(encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError) as exc:
        raise RuntimeError_(f"{path} is not readable JSON: {exc}") from exc


def read_lock(root: Path, *, require_guard: bool = True) -> dict[str, object]:
    path = root / LOCK_NAME
    value = _json(path)
    if not isinstance(value, dict):
        raise RuntimeError_(f"{path} must contain a JSON object")
    if set(value) != {"schema", "source", "version", "commit", "guard_enabled"}:
        raise RuntimeError_(
            f"{path} must contain exactly schema, source, version, commit and guard_enabled"
        )
    if type(value["schema"]) is not int or value["schema"] != SCHEMA or value["source"] != SOURCE:
        raise RuntimeError_(f"{path} has unsupported source {value['source']!r}")
    version = value["version"]
    if not isinstance(version, str) or not VERSION.fullmatch(version):
        raise RuntimeError_(f"{path} has an invalid release version")
    commit = value["commit"]
    if not isinstance(commit, str) or not SHA.fullmatch(commit) or commit != commit.lower():
        raise RuntimeError_(f"{path} must pin a lowercase full Git object id")
    if not isinstance(value["guard_enabled"], bool):
        raise RuntimeError_(f"{path} guard_enabled must be a boolean")
    if require_guard and value["guard_enabled"] is not True:
        raise RuntimeError_(f"{path} does not enable the guard")
    return value


def _manifest(path: Path, lock: dict[str, object]) -> dict[str, object]:
    value = _json(path)
    if not isinstance(value, dict):
        raise RuntimeError_(f"cache manifest {path} must be a JSON object")
    if set(value) != {"schema", "format", "source", "version", "commit", "files"}:
        raise RuntimeError_(f"cache manifest {path} has unexpected fields")
    if (type(value["schema"]) is not int or value["schema"] != SCHEMA
            or type(value["format"]) is not int or value["format"] != FORMAT
            or value["source"] != SOURCE):
        raise RuntimeError_(f"cache manifest {path} has the wrong format or source")
    if value["version"] != lock["version"] or value["commit"] != lock["commit"]:
        raise RuntimeError_(f"cache manifest {path} does not match the repository lock")
    files = value["files"]
    if not isinstance(files, dict) or set(files) != SCRIPT_SET:
        raise RuntimeError_(f"cache manifest {path} has the wrong script allowlist")
    for name, digest in files.items():
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise RuntimeError_(f"cache manifest {path} has an invalid digest for {name}")
    return value


def validate_cache(root: Path, lock: dict[str, object], explicit: str | None = None) -> Path:
    location = cache_root(explicit) / str(lock["commit"])
    if not location.is_dir():
        raise RuntimeError_(
            f"runtime cache is missing for {lock['version']} ({lock['commit']}) at {location}; "
            "run the explicit prepare step"
        )
    manifest = _manifest(location / "manifest.json", lock)
    for name in SCRIPTS:
        path = location / name
        if not path.is_file() or path.is_symlink():
            raise RuntimeError_(f"runtime cache entry {path} is missing or not a regular file")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != manifest["files"][name]:
            raise RuntimeError_(f"runtime cache entry {path} failed its content check")
    return location


def _git(source: Path, *args: str, input_bytes: bytes | None = None) -> bytes:
    try:
        return subprocess.run(
            ("git", "-C", str(source), *args),
            input=input_bytes,
            check=True,
            capture_output=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError_(f"could not read the pinned Git object: {exc}") from exc


def verify_source(source: Path) -> None:
    """Reject a configured origin that is not the public baseline repository."""
    try:
        remote = _git(source, "config", "--get", "remote.origin.url").decode().strip()
    except RuntimeError_:
        remote = ""
    if not remote:
        # A detached/local release fixture need not invent a remote. When an
        # origin is present, however, accepting another repository would make
        # the fixed lock source label a lie.
        return
    normalized = remote.lower().removesuffix(".git").rstrip("/")
    if normalized not in {
        "https://github.com/maximalcode/maxi-quality",
        "http://github.com/maximalcode/maxi-quality",
        "git@github.com:maximalcode/maxi-quality",
        "ssh://git@github.com/maximalcode/maxi-quality",
    }:
        raise RuntimeError_(f"source origin is not {SOURCE}: {remote}")


def prepare(source: Path, version: str, commit: str, explicit_cache: str | None,
            allow_untagged: bool = False) -> Path:
    if not VERSION.fullmatch(version):
        raise RuntimeError_("prepare requires a release version such as 1.2.0")
    if not SHA.fullmatch(commit) or commit != commit.lower():
        raise RuntimeError_("prepare requires a lowercase full Git object id")
    if not (source / ".git").exists() and not _git(source, "rev-parse", "--is-inside-work-tree"):
        raise RuntimeError_(f"source is not a Git worktree: {source}")
    verify_source(source)
    try:
        actual = _git(source, "rev-parse", f"{commit}^{{commit}}").decode().strip()
    except RuntimeError_:
        raise RuntimeError_(f"source does not contain commit {commit}")
    if actual != commit:
        raise RuntimeError_(f"Git resolved {commit} to {actual}; the lock must use the full object id")
    # If the source checkout has the release tag, bind the human version to
    # that exact object. Development fixtures may prepare an untagged commit;
    # the release-ref checker performs this same assertion before publishing.
    try:
        tagged = _git(source, "rev-parse", "--verify", f"refs/tags/{version}^{{commit}}").decode().strip()
    except RuntimeError_:
        tagged = ""
    if tagged and tagged != commit:
        raise RuntimeError_(f"release tag {version} resolves to {tagged}, not {commit}")
    if not tagged and not allow_untagged:
        raise RuntimeError_(
            f"source has no release tag {version}; use --allow-untagged-development "
            "only for a local fixture"
        )
    for name in SCRIPTS:
        _git(source, "cat-file", "-e", f"{commit}:scripts/agent-guard/{name}")

    destination = cache_root(explicit_cache) / commit
    lock = {"schema": SCHEMA, "source": SOURCE, "version": version, "commit": commit, "guard_enabled": True}
    if destination.exists():
        try:
            validate_cache(destination.parent.parent, lock, str(destination.parent))
            for name in SCRIPTS:
                cached = (destination / name).read_bytes()
                source_blob = _git(source, "show", f"{commit}:scripts/agent-guard/{name}")
                if cached != source_blob:
                    raise RuntimeError_(f"cached {name} does not match the pinned Git object")
            return destination
        except RuntimeError_:
            raise RuntimeError_(f"cache entry already exists but is invalid: {destination}")

    parent = destination.parent
    parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix=f".{commit}.", dir=parent))
    try:
        hashes: dict[str, str] = {}
        for name in SCRIPTS:
            content = _git(source, "show", f"{commit}:scripts/agent-guard/{name}")
            path = temp / name
            path.write_bytes(content)
            path.chmod(0o755)
            hashes[name] = hashlib.sha256(content).hexdigest()
        (temp / "manifest.json").write_text(
            json.dumps(
                {"schema": SCHEMA, "format": FORMAT, "source": SOURCE, "version": version,
                 "commit": commit, "files": hashes},
                indent=2, sort_keys=True,
            ) + "\n",
            encoding="utf-8",
        )
        try:
            os.replace(temp, destination)
        except FileExistsError:
            raise RuntimeError_(f"cache entry was concurrently installed: {destination}")
    except Exception:
        shutil.rmtree(temp, ignore_errors=True)
        raise
    return destination


def install_launcher(source: Path, commit: str, install_root: str | None) -> Path:
    """Install only the launcher executable, outside every consumer tree."""
    if not SHA.fullmatch(commit):
        raise RuntimeError_("install requires a lowercase full Git object id")
    verify_source(source)
    content = _git(source, "show", f"{commit}:scripts/quality-runtime.py")
    destination = (Path(install_root).expanduser() if install_root
                   else Path.home() / ".local" / "bin") / "quality-runtime"
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(content)
        os.chmod(temporary, 0o755)
        os.replace(temporary, destination)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return destination


def _missing_hook(name: str, message: str) -> int:
    """Keep a failed external install repairable and scoped to its hook."""
    if name == "stop-gate":
        json.dump({"decision": "block", "reason": f"quality-runtime: {message}"}, sys.stdout)
        sys.stdout.write("\n")
    elif name == "no-verify-guard":
        try:
            event = json.loads(sys.stdin.read() or "{}")
            command = event.get("tool_input", {}).get("command", "")
        except (ValueError, AttributeError):
            command = ""
        if isinstance(command, str) and re.search(r"\bgit\s+(?:[^;&|]+\s+)?(?:commit|push)\b", command):
            json.dump({"hookSpecificOutput": {
                "hookEventName": "PreToolUse", "permissionDecision": "deny",
                "permissionDecisionReason": f"quality-runtime is unavailable: {message}",
            }}, sys.stdout)
            sys.stdout.write("\n")
    else:
        print(f"quality-runtime: {message}", file=sys.stderr)
    return 3 if name == "record-gate" else 0


def dispatch(name: str, root: Path, explicit_cache: str | None, args: list[str]) -> int:
    script_name = name if name.endswith(".py") else name + ".py"
    if script_name not in SCRIPT_SET or script_name == "guard.py":
        raise RuntimeError_(f"unsupported guard {name!r}")
    try:
        lock = read_lock(root)
        location = validate_cache(root, lock, explicit_cache)
    except RuntimeError_ as exc:
        return _missing_hook(name, str(exc))
    script = location / script_name
    # cwd is the consumer root so git status, receipt and ledger are all scoped
    # to the project that invoked the hook, even though the code lives outside it.
    child_env = os.environ.copy()
    # stop-gate uses this to print a repair command that re-resolves the
    # consumer lock.  Without it, a cached script would tell the user to run
    # a cache-internal recorder directly, bypassing the lock on the next run.
    runtime_command = shlex.join((sys.executable, str(Path(sys.argv[0]).resolve())))
    child_env["MAXI_QUALITY_RUNTIME_COMMAND"] = runtime_command
    if explicit_cache:
        child_env["MAXI_QUALITY_RUNTIME_CACHE_ARG"] = (
            " --cache-root " + shlex.quote(str(cache_root(explicit_cache)))
        )
    return subprocess.run(
        (sys.executable, str(script), *args), cwd=root, env=child_env
    ).returncode


def _write_lock(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(value, fh, indent=2, sort_keys=False)
            fh.write("\n")
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def main(argv: list[str]) -> int:
    args = list(argv[1:])
    if not args:
        print("usage: quality-runtime.py prepare|status|<guard> [options]", file=sys.stderr)
        return 3
    command = args.pop(0)
    if command == "prepare":
        values: dict[str, str | None] = {"source": None, "version": None, "commit": None, "cache": None}
        allow_untagged = False
        i = 0
        while i < len(args):
            if args[i] == "--allow-untagged-development":
                allow_untagged = True; i += 1; continue
            if args[i] in ("--source", "--version", "--commit", "--cache-root") and i + 1 < len(args):
                key = {"--source": "source", "--version": "version", "--commit": "commit", "--cache-root": "cache"}[args[i]]
                values[key] = args[i + 1]; i += 2
            else:
                raise RuntimeError_(f"unknown prepare argument {args[i]!r}")
        if not all(values[k] for k in ("source", "version", "commit")):
            raise RuntimeError_("prepare requires --source, --version and --commit")
        location = prepare(Path(values["source"]).resolve(), values["version"], values["commit"], values["cache"], allow_untagged)
        print(location)
        return 0
    if command == "install":
        values: dict[str, str | None] = {"source": None, "commit": None, "install": None}
        i = 0
        while i < len(args):
            if args[i] in ("--source", "--commit", "--install-root") and i + 1 < len(args):
                key = {"--source": "source", "--commit": "commit", "--install-root": "install"}[args[i]]
                values[key] = args[i + 1]; i += 2
            else:
                raise RuntimeError_(f"unknown install argument {args[i]!r}")
        if not values["source"] or not values["commit"]:
            raise RuntimeError_("install requires --source and --commit")
        destination = install_launcher(Path(values["source"]).resolve(), values["commit"], values["install"])
        print(destination)
        return 0
    if command == "status":
        root: str | None = None; cache: str | None = None
        i = 0
        while i < len(args):
            if args[i] in ("--root", "--cache-root") and i + 1 < len(args):
                if args[i] == "--root": root = args[i + 1]
                else: cache = args[i + 1]
                i += 2
            else:
                raise RuntimeError_(f"unknown status argument {args[i]!r}")
        if not root:
            raise RuntimeError_("status requires --root")
        lock = read_lock(Path(root).resolve())
        location = validate_cache(Path(root).resolve(), lock, cache)
        print(f"ok {lock['version']} {lock['commit']} {location}")
        return 0

    root: str | None = None; cache: str | None = None; remaining: list[str] = []
    i = 0
    while i < len(args):
        if args[i] in ("--root", "--cache-root") and i + 1 < len(args):
            if args[i] == "--root": root = args[i + 1]
            else: cache = args[i + 1]
            i += 2
        else:
            remaining.append(args[i]); i += 1
    if not root:
        root = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    try:
        return dispatch(command, Path(root).resolve(), cache, remaining)
    except RuntimeError_ as exc:
        print(f"quality-runtime: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except RuntimeError_ as exc:
        print(f"quality-runtime: {exc}", file=sys.stderr)
        sys.exit(3)
