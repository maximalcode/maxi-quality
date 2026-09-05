#!/usr/bin/env python3
"""Migrate a copied/shared agent guard to the versioned runtime.

The migration writes data and hook wiring only.  It intentionally does not
copy Python files into the target repository.  Existing consumer settings and
unrelated hooks are retained; entries previously written by this baseline are
replaced by the runtime commands so re-running the migration is a no-op.
"""

from __future__ import annotations

import json
import os
import re
import runpy
import sys
import tempfile
import hashlib
from pathlib import Path

# Import only the trusted sibling source. Runtime installation still copies
# one self-contained launcher; diagnosis never loads a candidate executable.
_runtime = runpy.run_path(str(Path(__file__).with_name("quality-runtime.py")))
launcher_command = _runtime["launcher_command"]
runtime_command = _runtime["runtime_command"]

SOURCE = "maximalcode/maxi-quality"
SCHEMA = 1
LOCK_NAME = ".claude/quality-runtime.json"
OWNED_MARKER = "/.claude/agent-guard/"
GUARDS = ("stop-gate", "sample-guard", "no-verify-guard")
SHA = re.compile(r"^[0-9a-f]{40}$")
VERSION = re.compile(r"^v?[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$")
BEGIN = "<!-- BEGIN maxi-quality agent-guard"
END = "<!-- END maxi-quality agent-guard -->"


class Refused(Exception):
    pass


def load(path: Path) -> dict:
    if not path.exists() or not path.read_text(encoding="utf-8").strip():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Refused(f"{path} is not readable JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise Refused(f"{path} must contain a JSON object")
    return value


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            # Keep the lock's schema/source/version/commit order stable for
            # release automation that replaces the pinned commit in place.
            json.dump(value, fh, indent=2, sort_keys=False)
            fh.write("\n")
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def hook_entry(command: str, timeout: int) -> dict:
    return {"type": "command", "command": command, "timeout": timeout}


def remove_owned(settings: dict) -> None:
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return
    for groups in hooks.values():
        if not isinstance(groups, list):
            continue
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                continue
            group["hooks"] = [
                entry for entry in group["hooks"]
                if not (
                    isinstance(entry, dict)
                    and isinstance(entry.get("command"), str)
                    and (OWNED_MARKER in entry["command"]
                         or ("--root \"${CLAUDE_PROJECT_DIR}\"" in entry["command"]
                             and any(f" {name} " in entry["command"]
                                     for name in GUARDS)))
                )
            ]
        groups[:] = [group for group in groups if group.get("hooks")]


def append_runtime(settings: dict, commands: dict[str, str]) -> None:
    hooks = settings.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise Refused(".claude/settings.json has a non-object hooks key")
    specs = [("PreToolUse", "Bash", "no-verify-guard", 15), ("Stop", None, "stop-gate", 60)]
    if "sample-guard" in commands:
        specs.insert(0, ("PreToolUse", "Edit|Write|MultiEdit", "sample-guard", 15))
    for event, matcher, name, timeout in specs:
        command = commands[name]
        groups = hooks.setdefault(event, [])
        if not isinstance(groups, list):
            raise Refused(f".claude/settings.json hooks.{event} must be an array")
        matching = None
        for group in groups:
            if isinstance(group, dict) and group.get("matcher") == matcher:
                matching = group
                break
        if matching is None:
            matching = {"hooks": []}
            if matcher is not None:
                matching["matcher"] = matcher
            groups.append(matching)
        entries = matching.setdefault("hooks", [])
        if not isinstance(entries, list):
            raise Refused(f".claude/settings.json hooks.{event} entry is malformed")
        if not any(isinstance(e, dict) and e.get("command") == command for e in entries):
            entries.append(hook_entry(command, timeout))


def append_runtime_permissions(settings: dict, samples: bool) -> None:
    """Install the two owned deny rules while retaining consumer policy."""
    permissions = settings.setdefault("permissions", {})
    if not isinstance(permissions, dict):
        raise Refused(".claude/settings.json has a non-object permissions key")
    deny = permissions.setdefault("deny", [])
    if not isinstance(deny, list) or any(not isinstance(rule, str) for rule in deny):
        raise Refused(".claude/settings.json permissions.deny must be an array of strings")
    wanted = ["Edit(/.claude/agent-guard-receipt.json)"]
    if samples:
        wanted.append("Edit(/samples/expected/**)")
    for rule in wanted:
        if rule not in deny:
            deny.append(rule)


def remove_legacy_files(target: Path) -> None:
    directory = target / ".claude" / "agent-guard"
    if directory.is_symlink():
        raise Refused(f"{directory} is a symlink; refusing to remove files outside the target")
    if not directory.is_dir():
        return
    # These are exactly the files adopt.sh installs. Preserve anything else a
    # consumer may have placed in the directory.
    for name in (
        "guard.py", "stop-gate.py", "sample-guard.py", "no-verify-guard.py",
        "record-gate.py", "shim.py",
    ):
        path = directory / name
        if path.is_file() or path.is_symlink():
            path.unlink()
    try:
        directory.rmdir()
    except OSError:
        pass


def instruction_path(target: Path) -> Path | None:
    for name in ("CLAUDE.md", "AGENTS.md"):
        path = target / name
        if path.exists() or path.is_symlink():
            return path
    return None


def update_instruction(target: Path, launcher: str) -> None:
    """Refresh only the checksum owned agent region in CLAUDE/AGENTS.md."""
    path = instruction_path(target)
    if path is None:
        return
    real = path.resolve()
    if target not in real.parents and real != target:
        raise Refused(f"{path} resolves outside the target; refusing instruction update")
    text = real.read_text(encoding="utf-8")
    start = text.find(BEGIN)
    end = text.find(END)
    if start < 0 or end < start:
        raise Refused(f"{path} has no complete maxi-quality agent region")
    opening_end = text.find("-->", start)
    if opening_end < 0 or opening_end > end:
        raise Refused(f"{path} has a malformed agent region")
    opening = text[start:opening_end + 3]
    body = text[opening_end + 3:end]
    recorded = re.search(r"sha256:([0-9a-f]{8,64})", opening)
    if recorded and hashlib.sha256(body.encode()).hexdigest()[:16] != recorded.group(1):
        raise Refused(f"{path} agent region was edited; refusing to overwrite it")
    record = launcher_command(launcher) + ' record-gate --root "${CLAUDE_PROJECT_DIR}" --gate'
    # Both copied and shared historical profiles used one of these commands.
    # Replace those lines only; prose outside the owned marker is untouched.
    body = re.sub(r"(?m)^([ \t]*(?:python3 )?\.claude/agent-guard/(?:shim\.py )?record-gate(?:\.py)?(?: --gate)?)[ \t]*$", record, body)
    # A versioned tree has no local shim, so remove the old shared-only prose
    # while retaining the surrounding instructions and user's text.
    body = re.sub(r"\n?<!-- maxi-quality:if-shared -->.*?<!-- /maxi-quality:if-shared -->\n?", "\n", body, flags=re.S)
    digest = hashlib.sha256(body.encode()).hexdigest()[:16]
    new_opening = BEGIN + " sha256:" + digest + " -->"
    new = text[:start] + new_opening + body + text[end:]
    if new != text:
        write_text_preserving_link(real, new)


def validate_instruction(target: Path) -> None:
    """Check ownership before any lock/settings/file migration is written."""
    path = instruction_path(target)
    if path is None:
        return
    real = path.resolve()
    if target not in real.parents and real != target:
        raise Refused(f"{path} resolves outside the target; refusing instruction update")
    text = real.read_text(encoding="utf-8")
    start = text.find(BEGIN)
    end = text.find(END)
    if start < 0 or end < start:
        raise Refused(f"{path} has no complete maxi-quality agent region")
    opening_end = text.find("-->", start)
    if opening_end < 0 or opening_end > end:
        raise Refused(f"{path} has a malformed agent region")
    recorded = re.search(r"sha256:([0-9a-f]{8,64})", text[start:opening_end + 3])
    body = text[opening_end + 3:end]
    if recorded and hashlib.sha256(body.encode()).hexdigest()[:16] != recorded.group(1):
        raise Refused(f"{path} agent region was edited; refusing to overwrite it")


def write_text_preserving_link(path: Path, text: str) -> None:
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def resolved_file(path: Path, target: Path) -> Path:
    """Follow an in-tree file symlink without permitting an outside write."""
    real = path.resolve()
    if target not in real.parents:
        raise Refused(f"{path} resolves outside the target; refusing to replace it")
    return real


def ignore_runtime_state(path: Path) -> None:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    entries = (
        ".claude/agent-guard-receipt.json",
        ".claude/agent-guard-receipt.json.tmp",
        ".claude/agent-guard-ledger.jsonl",
    )
    missing = [entry for entry in entries if entry not in text.splitlines()]
    if missing:
        if text and not text.endswith("\n"):
            text += "\n"
        write_text_preserving_link(path, text + "\n".join(missing) + "\n")


def migrate(target: Path, version: str, commit: str, launcher: str, dry_run: bool,
            guard_enabled: bool = True) -> None:
    target = target.resolve()
    if not target.is_dir():
        raise Refused(f"target is not a directory: {target}")
    if not version or not commit:
        raise Refused("version and commit are required")
    if not VERSION.fullmatch(version):
        raise Refused("version must look like v1.2.0")
    if not SHA.fullmatch(commit):
        raise Refused("commit must be a lowercase full Git object id")
    settings_path = target / ".claude" / "settings.json"
    lock_path = resolved_file(target / LOCK_NAME, target)
    settings_path = resolved_file(settings_path, target)
    ignore_path = resolved_file(target / ".gitignore", target)
    settings = load(settings_path)
    lock = {
        "schema": SCHEMA,
        "source": SOURCE,
        "version": version,
        "commit": commit,
        "guard_enabled": guard_enabled,
    }
    root = '"${CLAUDE_PROJECT_DIR}"'
    commands = {
        name: runtime_command(launcher, name, root)
        for name in GUARDS
        if name != "sample-guard" or (target / "samples" / "expected").is_dir()
    }
    expected_samples = (target / "samples" / "expected").is_dir()
    if guard_enabled:
        validate_instruction(target)
        if (target / ".claude" / "agent-guard").is_symlink():
            raise Refused(f"{target / '.claude' / 'agent-guard'} is a symlink; refusing to remove files outside the target")
        remove_owned(settings)
        append_runtime(settings, commands)
        append_runtime_permissions(settings, expected_samples)
    if dry_run:
        print(json.dumps({"lock": lock, "settings": settings}, indent=2, sort_keys=False))
        return
    write_json(lock_path, lock)
    if guard_enabled:
        write_json(settings_path, settings)
        ignore_runtime_state(ignore_path)
        remove_legacy_files(target)
        update_instruction(target, launcher)
    print(f"migrated {target} to {version} ({commit})")


def main(argv: list[str]) -> int:
    args = list(argv[1:])
    values: dict[str, str | None] = {"target": None, "version": None, "commit": None, "launcher": "quality-runtime"}
    dry_run = False
    guard_enabled = True
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--dry-run":
            dry_run = True; i += 1; continue
        if arg == "--guard-disabled":
            guard_enabled = False; i += 1; continue
        if arg in ("--target", "--version", "--commit", "--launcher") and i + 1 < len(args):
            values[{"--target": "target", "--version": "version", "--commit": "commit", "--launcher": "launcher"}[arg]] = args[i + 1]
            i += 2; continue
        raise Refused(f"unknown argument {arg!r}")
    values["target"] = values["target"] or os.getcwd()
    if not values["version"] or not values["commit"]:
        raise Refused("usage: quality-runtime-migrate.py --version V --commit SHA [--target DIR]")
    migrate(Path(values["target"]), values["version"], values["commit"], values["launcher"] or "quality-runtime", dry_run, guard_enabled)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except Refused as exc:
        print(f"quality-runtime-migrate: {exc}", file=sys.stderr)
        sys.exit(3)
