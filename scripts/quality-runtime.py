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

import ast
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


def _check(checks: list[dict[str, str]], ident: str, status: str, detail: str) -> None:
    """Append one stable, human-readable diagnosis result."""
    checks.append({"id": ident, "status": status, "detail": detail})


def _settings(path: Path) -> dict[str, object]:
    value = _json(path)
    if not isinstance(value, dict):
        raise RuntimeError_(f"{path} must contain a JSON object")
    return value


def _hook_entries(settings: dict[str, object], event: str) -> list[tuple[str | None, dict[str, object]]]:
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return []
    groups = hooks.get(event)
    if not isinstance(groups, list):
        return []
    found: list[tuple[str | None, dict[str, object]]] = []
    for group in groups:
        if not isinstance(group, dict):
            continue
        matcher = group.get("matcher")
        matcher = matcher if isinstance(matcher, str) else None
        entries = group.get("hooks")
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, dict):
                found.append((matcher, entry))
    return found


def _launcher_condition(launcher: str) -> list[str]:
    """Return the condition emitted by ``quality-runtime-migrate.py``."""
    if launcher == "$HOME/.local/bin/quality-runtime":
        return ["[", "-x", launcher, "]"]
    if "/" in launcher or launcher.startswith("."):
        return ["[", "-f", launcher, "]"]
    return ["command", "-v", launcher, ">", "/dev/null", "2", ">", "&", "1"]


def _fallback_is_generated(branch: list[str], name: str) -> bool:
    """Recognize the migration fallback without interpreting arbitrary shell."""
    if len(branch) != 4 or branch[:2] != ["python3", "-c"] or branch[3] != name:
        return False
    code = branch[2]
    try:
        ast.parse(code, mode="exec")
    except SyntaxError:
        return False
    return all(marker in code for marker in (
        "import json,re,sys",
        "n=sys.argv[1]",
        "quality-runtime launcher is unavailable; install it and prepare the pinned cache",
        "json.loads(sys.stdin.read() or '{}')",
        "json.dump(o,sys.stdout)",
    ))


def _invocation_branch(branch: list[str], name: str) -> tuple[str, bool] | None:
    """Parse one exact runtime invocation from a shell command branch."""
    if not branch:
        return None
    via_python = branch[0] == "python3"
    launcher_index = 1 if via_python else 0
    if len(branch) <= launcher_index:
        return None
    launcher = branch[launcher_index]
    action_index = launcher_index + 1
    if len(branch) != action_index + 3 or branch[action_index] != name:
        return None
    if branch[action_index + 1:action_index + 3] != ["--root", "${CLAUDE_PROJECT_DIR}"]:
        return None
    if via_python and not launcher.endswith("quality-runtime.py"):
        return None
    return launcher, via_python


def _runtime_invocation(command: str, name: str) -> tuple[str, bool] | None:
    """Extract a complete invocation emitted by ``quality-runtime-migrate.py``.

    The hook is a small, fixed shell program.  Requiring either its complete
    direct argv shape or its complete ``if/then/else/fi`` shape, and matching
    the launcher check to its true branch, prevents an inert condition, a
    prefix such as ``exit 0``, or a command merely mentioning ``then`` from
    being treated as a guard.
    """
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|")
        lexer.whitespace_split = True
        lexer.commenters = "#"
        tokens = list(lexer)
    except ValueError:
        return None
    if not tokens:
        return None
    # A hand-written hook may use the direct form.  It is safe to recognize
    # only the complete argv shape; wrappers and command substitutions remain
    # outside the supported grammar.
    if tokens[0] != "if":
        return _invocation_branch(tokens, name)
    try:
        condition_end = tokens.index(";")
        if tokens[condition_end + 1] != "then":
            return None
        then = condition_end + 1
        true_end = tokens.index(";", then + 1)
        tail = tokens[true_end + 1:]
        if tail == ["fi"]:
            else_start = false_end = None
        else:
            if not tail or tail[0] != "else":
                return None
            else_start = true_end + 1
            false_end = tokens.index(";", else_start + 1)
            if tokens[false_end + 1:] != ["fi"]:
                return None
    except (ValueError, IndexError):
        return None

    invocation = _invocation_branch(tokens[then + 1:true_end], name)
    if invocation is None:
        return None
    launcher, via_python = invocation
    if tokens[:condition_end] != ["if", *_launcher_condition(launcher)]:
        return None
    if (else_start is not None
            and not _fallback_is_generated(tokens[else_start + 1:false_end], name)):
        return None
    return launcher, via_python


def _owned_command(settings: dict[str, object], event: str, name: str,
                   matcher: str | None) -> tuple[dict[str, object], str, bool] | None:
    """Find a runtime entry only when its matcher and invocation agree."""
    for actual_matcher, entry in _hook_entries(settings, event):
        command = entry.get("command")
        if (actual_matcher != matcher or entry.get("type") != "command"
                or not isinstance(command, str)):
            continue
        invocation = _runtime_invocation(command, name)
        if invocation is None:
            continue
        launcher, via_python = invocation
        return entry, launcher, via_python
    return None


def _launcher_identity(path: Path) -> bool:
    """Check the installed launcher identity from source, without executing it."""
    try:
        content = path.read_bytes()
        source = content.decode("utf-8")
        tree = ast.parse(source, filename=str(path), mode="exec")
    except (OSError, UnicodeDecodeError, SyntaxError):
        return False
    source_value = None
    definitions: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            definitions.add(node.name)
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "SOURCE":
                    try:
                        source_value = ast.literal_eval(node.value)
                    except (ValueError, TypeError):
                        source_value = None
    return (source_value == SOURCE
            and {"diagnose", "dispatch", "main", "validate_cache"} <= definitions)


def _launcher_ok(launcher: str, via_python: bool, root: Path) -> tuple[bool, str]:
    """Check an extracted external launcher without running it."""
    if launcher == "$HOME/.local/bin/quality-runtime":
        path = Path.home() / ".local" / "bin" / "quality-runtime"
        return ((path.is_file() and os.access(path, os.X_OK)
                 and _launcher_identity(path)), str(path))
    path = Path(launcher).expanduser()
    if not path.is_absolute():
        path = root / path
    if via_python:
        return (path.is_file() and _launcher_identity(path), str(path))
    if "/" in launcher or launcher.startswith("."):
        return ((path.is_file() and os.access(path, os.X_OK)
                 and _launcher_identity(path)), str(path))
    resolved = shutil.which(launcher)
    if resolved:
        resolved_path = Path(resolved)
        return _launcher_identity(resolved_path), resolved
    return False, f"the hook launcher is not available: {launcher}"


def _legacy_profile(root: Path, settings: dict[str, object] | None) -> str | None:
    directory = root / ".claude" / "agent-guard"
    if not directory.is_dir() or directory.is_symlink():
        return None
    if (directory / "shim.py").is_file():
        return "legacy-shared"
    if any((directory / name).is_file() for name in SCRIPTS):
        return "legacy-copied"
    return None


def diagnose(root: Path, explicit_cache: str | None = None) -> dict[str, object]:
    """Read-only diagnosis of one Adopter checkout's guard installation.

    This deliberately compares only entries owned by the baseline.  Other
    hooks and permission rules are a consumer's policy and remain untouched.
    No gate, hook, cache writer, network operation, or subprocess is called.
    """
    root = root.resolve()
    checks: list[dict[str, str]] = []
    lock_path = root / LOCK_NAME
    settings_path = root / ".claude" / "settings.json"
    lock_exists = lock_path.is_file()
    settings: dict[str, object] | None = None
    try:
        settings = _settings(settings_path)
    except RuntimeError_ as exc:
        _check(checks, "settings-json", "fail", str(exc))

    if not lock_exists:
        profile = _legacy_profile(root, settings)
        if profile:
            return {
                "schema": 1, "status": profile, "healthy": False,
                "installation_profile": profile, "release": None,
                "configured_gate": None, "checks": checks,
                "live_enforcement": "unverified", "host_settings": "unverified",
                "migration": "python3 scripts/quality-runtime-migrate.py --target <checkout> --version V --commit SHA",
            }
        _check(checks, "release-lock", "fail",
               f"{lock_path} is missing; this checkout has no versioned runtime lock")
        report = {
            "schema": 1, "status": "unavailable", "healthy": False,
            "installation_profile": "unconfigured", "release": None,
            "configured_gate": None, "checks": checks,
            "live_enforcement": "unverified", "host_settings": "unverified",
            "migration": "install and prepare the versioned runtime, then run diagnose again",
        }
        return report

    try:
        lock = read_lock(root, require_guard=False)
    except RuntimeError_ as exc:
        _check(checks, "release-lock", "fail", str(exc))
        return {
            "schema": 1, "status": "broken", "healthy": False,
            "installation_profile": "invalid-lock", "release": None,
            "configured_gate": None, "checks": checks,
            "live_enforcement": "unverified", "host_settings": "unverified",
            "migration": "repair .claude/quality-runtime.json with a pinned release",
        }

    release = {"source": lock["source"], "version": lock["version"], "commit": lock["commit"]}
    if lock["guard_enabled"] is not True:
        _check(checks, "guard-enabled", "skip", "agent guard is explicitly disabled for this profile")
        _check(checks, "release-lock", "pass", f"pinned {lock['version']} ({lock['commit']})")
        return {
            "schema": 1, "status": "not-enabled", "healthy": True,
            "installation_profile": "disabled", "release": release,
            "configured_gate": None, "checks": checks,
            "live_enforcement": "unverified", "host_settings": "unverified",
            "migration": "enable the guard by migrating without --guard-disabled",
        }

    _check(checks, "release-lock", "pass", f"pinned {lock['version']} ({lock['commit']})")
    try:
        location = validate_cache(root, lock, explicit_cache)
    except RuntimeError_ as exc:
        _check(checks, "runtime-cache", "fail", str(exc))
        location = None
    else:
        _check(checks, "runtime-cache", "pass", f"validated immutable cache at {location}")

    if settings is not None and settings.get("disableAllHooks") is True:
        _check(checks, "hooks-enabled", "fail",
               "project settings disable all hooks; the agent guard cannot enforce its decisions")
    else:
        _check(checks, "hooks-enabled", "pass", "project settings leave hooks enabled")

    expected_samples = (root / "samples" / "expected").is_dir()
    profile = "versioned-with-samples" if expected_samples else "versioned-without-samples"
    gate_value: str | None = None
    gate_path = root / ".claude" / "agent-guard.json"
    try:
        gate_data = _json(gate_path)
        if isinstance(gate_data, dict) and isinstance(gate_data.get("gate_command"), str) and gate_data["gate_command"].strip():
            gate_value = gate_data["gate_command"]
            _check(checks, "configured-gate", "pass", f"declared gate: {gate_value}")
        else:
            _check(checks, "configured-gate", "fail", f"{gate_path} has no non-empty gate_command")
    except RuntimeError_ as exc:
        _check(checks, "configured-gate", "fail", str(exc))

    required = [("hook-no-verify", "PreToolUse", "Bash", "no-verify-guard"),
                ("hook-stop-gate", "Stop", None, "stop-gate")]
    if expected_samples:
        required.insert(0, ("hook-sample-guard", "PreToolUse", "Edit|Write|MultiEdit", "sample-guard"))
    for ident, event, matcher, name in required:
        owned = _owned_command(settings or {}, event, name, matcher)
        if owned is None:
            _check(checks, ident, "fail",
                   f"required {event} hook for {name} with matcher {matcher or '<none>'} is missing or changed")
            continue
        entry, launcher, via_python = owned
        _check(checks, ident, "pass", f"{event} {matcher or '<none>'} runs {name}")
        if entry.get("async") is True:
            _check(checks, "hook-execution-mode", "fail",
                   f"{event} {matcher or '<none>'} hook is asynchronous and cannot enforce guard decisions")
        launcher_good, launcher_detail = _launcher_ok(launcher, via_python, root)
        if not launcher_good:
            _check(checks, "launcher", "fail", f"launcher is unavailable: {launcher_detail}")

    # A samples profile is the only one that owns this rule.  Absence is an
    # intentional profile choice, not a wiring failure.
    if expected_samples:
        _check(checks, "sample-protection", "pass", "samples/expected is protected by the owned sample hook and deny rule")
    else:
        _check(checks, "sample-protection", "skip", "profile has no samples/expected; sample protection is not applicable")

    deny = ((settings or {}).get("permissions") or {}) if isinstance((settings or {}).get("permissions"), dict) else {}
    deny_rules = deny.get("deny", []) if isinstance(deny, dict) else []
    baseline_deny = ["Edit(/.claude/agent-guard-receipt.json)"]
    if expected_samples:
        baseline_deny.append("Edit(/samples/expected/**)")
    for rule in baseline_deny:
        if isinstance(deny_rules, list) and rule in deny_rules:
            _check(checks, "deny-" + re.sub(r"[^a-z]+", "-", rule.lower()).strip("-"), "pass", f"owned deny rule present: {rule}")
        else:
            _check(checks, "deny-rules", "fail", f"required deny rule is missing: {rule}")

    failed = [c for c in checks if c["status"] == "fail"]
    return {
        "schema": 1, "status": "broken" if failed else "ok", "healthy": not failed,
        "installation_profile": profile, "release": release,
        "configured_gate": gate_value, "checks": checks,
        "live_enforcement": "unverified", "host_settings": "unverified",
        "migration": "python3 scripts/quality-runtime-migrate.py --target <checkout> --version V --commit SHA",
    }


def print_diagnosis(report: dict[str, object], as_json: bool) -> int:
    if as_json:
        print(json.dumps(report, indent=2, sort_keys=True) + "\n", end="")
    else:
        print(f"quality-runtime: {report['status']} ({report['installation_profile']})")
        release = report.get("release")
        if isinstance(release, dict):
            print(f"release: {release['version']} @ {release['commit']}")
        print(f"configured gate: {report.get('configured_gate') or 'not declared'}")
        print(f"live enforcement: {report['live_enforcement']}")
        print(f"host settings: {report['host_settings']}")
        for check in report["checks"]:
            print(f"{check['status']}: {check['id']}: {check['detail']}")
        if report.get("migration"):
            print(f"migration: {report['migration']}")
    return 0 if report["healthy"] or str(report["status"]).startswith("legacy-") else 1


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

    if command == "diagnose":
        root: str | None = None
        cache: str | None = None
        as_json = False
        i = 0
        while i < len(args):
            if args[i] in ("--root", "--cache-root") and i + 1 < len(args):
                if args[i] == "--root":
                    root = args[i + 1]
                else:
                    cache = args[i + 1]
                i += 2
            elif args[i] in ("--json", "--format=json"):
                as_json = True
                i += 1
            else:
                raise RuntimeError_(f"unknown diagnose argument {args[i]!r}")
        root_path = Path(root or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()).resolve()
        report = diagnose(root_path, cache)
        return print_diagnosis(report, as_json)

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
