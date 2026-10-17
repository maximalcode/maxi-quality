"""Pause and resume the selected native Guardian integration."""

from __future__ import annotations

import copy
import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import guardian_lifecycle as lifecycle
import guardian_setup as setup

runtime = importlib.import_module("quality-runtime")


def _settings_name(host: str) -> str:
    if host == "claude":
        return ".claude/settings.json"
    if host == "codex":
        return ".codex/hooks.json"
    raise ValueError(f"unsupported Guardian host {host!r}")


def _setting(root: Path, name: str) -> dict:
    try:
        return setup.settings(root, name)
    except (OSError, ValueError) as exc:
        raise setup.Refused(str(exc)) from exc


def _candidate(entry: object, host: str, name: str) -> bool:
    if not isinstance(entry, dict) or entry.get("type") != "command":
        return False
    command = entry.get("command")
    if not isinstance(command, str):
        return False
    return (runtime._runtime_invocation(command, name, host) is not None
            or f"/.claude/agent-guard/{name}.py" in command)


def plan_deactivation(root: Path, state: dict) -> dict:
    """Plan exact owned hook/deny removal without writing any project files.

    Returns ``{"settings": {relative_path: planned_object}, "removed":
    {"hooks": [...], "deny": [...]}, "conflicts": [...]}``. Removed hook
    records retain their original group and entry positions for a later resume.
    Callers must refuse the plan when conflicts is non-empty.
    """
    root = Path(root).resolve()
    host = state.get("selected_host")
    owned = state.get("owned")
    if host not in ("claude", "codex") or not isinstance(owned, dict):
        return {"settings": {}, "removed": {"hooks": [], "deny": []},
                "conflicts": ["Guardian ownership metadata is malformed"]}
    name = _settings_name(host)
    try:
        setup.safe_path(root, name)
        settings = _setting(root, name)
    except (OSError, setup.Refused) as exc:
        return {"settings": {}, "removed": {"hooks": [], "deny": []},
                "conflicts": [str(exc)]}
    records = owned.get("hooks")
    if not isinstance(records, list):
        return {"settings": {}, "removed": {"hooks": [], "deny": []},
                "conflicts": ["Guardian hook ownership metadata is malformed"]}
    planned = copy.deepcopy(settings)
    removed_hooks = []
    conflicts = []
    hooks = planned.get("hooks", {})
    if not isinstance(hooks, dict):
        hooks = {}
    for record in records:
        if (not isinstance(record, dict) or not isinstance(record.get("event"), str)
                or not isinstance(record.get("name"), str)
                or not isinstance(record.get("sha256"), str)):
            conflicts.append("Guardian hook ownership metadata is malformed")
            continue
        event = record["event"]
        matcher = record.get("matcher")
        groups = hooks.get(event, [])
        matches = []
        candidates = []
        if isinstance(groups, list):
            for group_index, group in enumerate(groups):
                if not isinstance(group, dict) or group.get("matcher") != matcher:
                    continue
                entries = group.get("hooks", [])
                if not isinstance(entries, list):
                    continue
                for entry_index, entry in enumerate(entries):
                    if lifecycle.hook_is_owned(entry, record):
                        matches.append((group_index, group, entry_index, entry))
                    elif _candidate(entry, host, record["name"]):
                        candidates.append((group_index, group, entry_index, entry))
        if len(matches) == 1 and not candidates:
            group_index, group, entry_index, entry = matches[0]
            removed_hooks.append({"event": event, "matcher": matcher,
                                  "group_index": group_index,
                                  "entry_index": entry_index,
                                  "entry": copy.deepcopy(entry)})
            del group["hooks"][entry_index]
        elif not matches:
            conflicts.append(f"owned {event} hook {record['name']} is missing or modified")
        else:
            conflicts.append(f"owned {event} hook {record['name']} is ambiguous or modified")

    removed_deny = []
    deny_records = owned.get("deny", [])
    if not isinstance(deny_records, list):
        conflicts.append("Guardian deny ownership metadata is malformed")
        deny_records = []
    if host == "claude" and deny_records:
        permissions = planned.get("permissions", {})
        if not isinstance(permissions, dict):
            conflicts.append("Claude permissions settings are malformed")
        else:
            deny = permissions.get("deny", [])
            if not isinstance(deny, list) or any(not isinstance(rule, str) for rule in deny):
                conflicts.append("Claude permissions.deny must be an array of strings")
            else:
                for rule in deny_records:
                    if not isinstance(rule, str):
                        conflicts.append("Guardian deny ownership metadata is malformed")
                        continue
                    if rule not in deny:
                        conflicts.append(f"owned deny rule is missing or modified: {rule}")
                        continue
                    deny.remove(rule)
                    removed_deny.append(rule)
                if not deny:
                    permissions.pop("deny", None)
                if not permissions:
                    planned.pop("permissions", None)

    changed = bool(removed_hooks or removed_deny)
    return {"settings": {name: planned} if changed else {},
            "removed": {"hooks": removed_hooks, "deny": removed_deny},
            "conflicts": conflicts}


def _state_bytes(state: dict) -> bytes:
    return (json.dumps(state, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _read_lock(root: Path, require_guard: bool) -> dict:
    try:
        return runtime.read_lock(root, require_guard=require_guard)
    except runtime.RuntimeError_ as exc:
        raise setup.Refused(str(exc)) from exc


def _validate_pin(state: dict, lock: dict) -> None:
    release = state.get("release", {})
    if (lock.get("version") != release.get("version")
            or lock.get("commit") != release.get("commit")):
        raise setup.Refused("the runtime lock no longer matches the recorded fixed Guardian version")


def _launcher_available(launcher: str, via_python: bool, root: Path) -> bool:
    """Check the hook's pinned launcher path without inferring host trust."""
    if launcher == "$HOME/.local/bin/quality-runtime":
        path = Path.home() / ".local/bin/quality-runtime"
    elif via_python or "/" in launcher or launcher.startswith("."):
        path = Path(launcher)
        if not path.is_absolute():
            path = root / path
    else:
        search_path = os.pathsep.join(
            str(Path(part) if Path(part).is_absolute() else root / part)
            for part in os.environ.get("PATH", os.defpath).split(os.pathsep)
        )
        resolved = shutil.which(launcher, path=search_path)
        if resolved is None:
            return False
        path = Path(resolved)
    return path.is_file() and (via_python or os.access(path, os.X_OK))


def _check_active(root: Path, state: dict, host: str) -> dict:
    if state.get("lifecycle", "active") != "active":
        raise setup.Refused(f"Guardian is {state.get('lifecycle')}; use the matching lifecycle operation")
    lock = _read_lock(root, require_guard=True)
    _validate_pin(state, lock)
    report = runtime.diagnose(root, host=host)
    failures = [item["detail"] for item in report.get("checks", [])
                if item.get("status") == "fail"]
    if failures:
        raise setup.Refused("Guardian setup is broken; repair before pausing: " + "; ".join(failures))
    return lock


def _pause(args, runner) -> tuple[dict, int]:
    report = {"outcome": "refused", "host": None, "changes": {},
              "conflicts": [], "trust": "unverified", "error": None}
    try:
        runner.clear_git_environment()
        root = Path(args.root).resolve()
        if runner.repo_root(str(root)) != str(root):
            raise setup.Refused("target must be a Git working tree root")
        state = lifecycle.read_state(root)
        if not state:
            raise setup.Refused("Guardian has no recorded selected-host installation")
        host = args.host or state["selected_host"]
        report["host"] = host
        if host != state["selected_host"]:
            raise setup.Refused("pause applies only to the recorded selected host")
        if state.get("lifecycle") == "paused":
            report.update(outcome="unchanged", lifecycle="paused", changes={})
            return report, 0
        lock = _check_active(root, state, host)
        plan = plan_deactivation(root, state)
        report["conflicts"] = plan["conflicts"]
        if report["conflicts"]:
            raise setup.Refused("owned settings changed; reconcile them before pausing")
        other_host = "codex" if host == "claude" else "claude"
        # The release lock is shared by both adapters. Disabling it is correct
        # only when the other host has no Guardian hooks; unknown settings must
        # not be interpreted as permission to disable their runtime.
        other_hooks = lifecycle.has_guard_hooks(root, other_host)
        changed_lock = dict(lock, guard_enabled=other_hooks is not False)
        changes = {name: (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode()
                   for name, value in plan["settings"].items()}
        changes[runtime.LOCK_NAME] = (json.dumps(changed_lock, indent=2) + "\n").encode()
        paused_state = copy.deepcopy(state)
        paused_state["lifecycle"] = "paused"
        paused_state["owned"]["paused_restore"] = plan["removed"]
        paused_state["owned"]["paused_lock"] = changed_lock
        changes[lifecycle.STATE_NAME] = _state_bytes(paused_state)
        for name in changes:
            setup.safe_path(root, name)
        report.update(outcome="preview", lifecycle="paused",
                      changes={name: content.decode() for name, content in changes.items()},
                      removed=plan["removed"],
                      commands=[json.loads((root / ".claude/agent-guard.json").read_text())
                                .get("gate_command")])
        if not args.apply:
            return report, 0
        setup.activate(root, changes)
        report["outcome"] = "paused"
        return report, 0
    except (OSError, ValueError, setup.Refused, subprocess.CalledProcessError) as exc:
        report["outcome"] = "refused"
        report["error"] = str(exc)
        return report, 3


def _restore_settings(root: Path, state: dict) -> tuple[dict[str, bytes], list[str]]:
    host = state["selected_host"]
    name = _settings_name(host)
    setup.safe_path(root, name)
    current = _setting(root, name)
    planned = copy.deepcopy(current)
    restore = state.get("owned", {}).get("paused_restore")
    conflicts = []
    if not isinstance(restore, dict) or not isinstance(restore.get("hooks"), list) or not isinstance(restore.get("deny"), list):
        return {}, ["paused Guardian restoration data is missing or malformed"]
    records = state.get("owned", {}).get("hooks", [])
    if not isinstance(records, list):
        return {}, ["Guardian hook ownership metadata is malformed"]
    hooks = planned.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        return {}, ["host hooks settings are malformed"]
    for saved in restore["hooks"]:
        if not isinstance(saved, dict) or not isinstance(saved.get("entry"), dict):
            conflicts.append("paused Guardian hook restoration data is malformed")
            continue
        event, matcher, entry = saved.get("event"), saved.get("matcher"), saved["entry"]
        if not isinstance(event, str):
            conflicts.append("paused Guardian hook restoration data is malformed")
            continue
        matching_records = [record for record in records if isinstance(record, dict)
                            and record.get("event") == event
                            and record.get("matcher") == matcher
                            and lifecycle.hook_is_owned(entry, record)]
        if len(matching_records) != 1:
            conflicts.append(f"saved {event} hook no longer matches its ownership record")
            continue
        groups = hooks.setdefault(event, [])
        if not isinstance(groups, list):
            conflicts.append(f"{event} hooks settings are malformed")
            continue
        existing_exact = False
        modified = False
        for group in groups:
            if not isinstance(group, dict) or group.get("matcher") != matcher:
                continue
            entries = group.get("hooks", [])
            if not isinstance(entries, list):
                modified = True
                continue
            for candidate in entries:
                if candidate == entry:
                    existing_exact = True
                elif any(_candidate(candidate, host, record.get("name", ""))
                         for record in state.get("owned", {}).get("hooks", [])
                         if isinstance(record, dict)):
                    modified = True
        if existing_exact:
            continue
        if modified:
            conflicts.append(f"{event} hook changed while Guardian was paused")
            continue
        group_index = saved.get("group_index", len(groups))
        entry_index = saved.get("entry_index", 0)
        if type(group_index) is not int or type(entry_index) is not int:
            conflicts.append("paused Guardian hook position is malformed")
            continue
        if group_index < 0 or entry_index < 0:
            conflicts.append("paused Guardian hook position is malformed")
            continue
        if group_index < len(groups) and isinstance(groups[group_index], dict) and groups[group_index].get("matcher") == matcher:
            group = groups[group_index]
        else:
            matching = next((group for group in groups if isinstance(group, dict)
                             and group.get("matcher") == matcher), None)
            if matching is None:
                group = {"matcher": matcher, "hooks": []}
                groups.insert(min(group_index, len(groups)), group)
            else:
                group = matching
        entries = group.setdefault("hooks", [])
        if not isinstance(entries, list):
            conflicts.append(f"{event} hook group is malformed")
            continue
        entries.insert(min(entry_index, len(entries)), copy.deepcopy(entry))

    if host == "claude" and restore["deny"]:
        if restore["deny"] != state.get("owned", {}).get("deny", []):
            conflicts.append("saved deny rules no longer match their ownership record")
        permissions = planned.setdefault("permissions", {})
        if not isinstance(permissions, dict):
            conflicts.append("Claude permissions settings are malformed")
        else:
            deny = permissions.setdefault("deny", [])
            if not isinstance(deny, list) or any(not isinstance(rule, str) for rule in deny):
                conflicts.append("Claude permissions.deny must be an array of strings")
            else:
                for rule in restore["deny"]:
                    if not isinstance(rule, str):
                        conflicts.append("paused Guardian deny restoration data is malformed")
                    elif rule not in deny:
                        deny.append(rule)
    if conflicts:
        return {}, conflicts
    return {name: (json.dumps(planned, indent=2, ensure_ascii=False) + "\n").encode()}, []


def _resume(args, runner) -> tuple[dict, int]:
    report = {"outcome": "refused", "host": None, "changes": {},
              "conflicts": [], "trust": "unverified", "error": None}
    try:
        runner.clear_git_environment()
        root = Path(args.root).resolve()
        if runner.repo_root(str(root)) != str(root):
            raise setup.Refused("target must be a Git working tree root")
        state = lifecycle.read_state(root)
        if not state:
            raise setup.Refused("Guardian has no recorded selected-host installation")
        host = args.host or state["selected_host"]
        report["host"] = host
        if host != state["selected_host"]:
            raise setup.Refused("resume applies only to the recorded selected host")
        if state.get("lifecycle") == "active":
            report.update(outcome="unchanged", lifecycle="active", changes={})
            return report, 0
        if state.get("lifecycle") != "paused":
            raise setup.Refused("Guardian is not paused; use setup or the matching lifecycle operation")
        lock = _read_lock(root, require_guard=False)
        _validate_pin(state, lock)
        if lock != state.get("owned", {}).get("paused_lock"):
            raise setup.Refused("paused runtime lock was changed; reconcile it before resuming")
        try:
            runtime.validate_cache(root, lock)
        except runtime.RuntimeError_ as exc:
            raise setup.Refused(str(exc)) from exc
        gate = setup.read_object(setup.safe_path(root, ".claude/agent-guard.json"))
        if (not isinstance(gate.get("gate_command"), str)
                or not gate["gate_command"].strip()):
            raise setup.Refused("the project gate or pinned installation changed while paused")
        setup.validate_host_configuration(root, host)
        settings_changes, conflicts = _restore_settings(root, state)
        report["conflicts"] = conflicts
        if conflicts:
            raise setup.Refused("host settings changed while paused; reconcile before resuming")
        # Check that every restored runtime command still names a usable pinned launcher.
        restored = _setting(root, _settings_name(host))
        restored.update(json.loads(settings_changes[_settings_name(host)]))
        for record in state["owned"].get("hooks", []):
            found = runtime._owned_command(restored, record["event"], record["name"],
                                           record.get("matcher"), host)
            if found is None or not lifecycle.hook_is_owned(found[0], record):
                raise setup.Refused(f"pinned {record['name']} hook could not be validated for resume")
            if not _launcher_available(found[1], found[2], root):
                raise setup.Refused("the hook launcher is unavailable; install its pinned launcher before resuming")
        enabled_lock = dict(lock, guard_enabled=True)
        changes = dict(settings_changes)
        changes[runtime.LOCK_NAME] = (json.dumps(enabled_lock, indent=2) + "\n").encode()
        active_state = copy.deepcopy(state)
        active_state["lifecycle"] = "active"
        active_state["owned"].pop("paused_restore", None)
        active_state["owned"].pop("paused_lock", None)
        changes[lifecycle.STATE_NAME] = _state_bytes(active_state)
        for name in changes:
            setup.safe_path(root, name)
        report.update(outcome="preview", lifecycle="active",
                      changes={name: content.decode() for name, content in changes.items()},
                      trust="unverified")
        if not args.apply:
            return report, 0
        setup.activate(root, changes)
        report["outcome"] = "resumed"
        return report, 0
    except (OSError, ValueError, setup.Refused, subprocess.CalledProcessError) as exc:
        report["outcome"] = "refused"
        report["error"] = str(exc)
        return report, 3


def pause(args, runner) -> tuple[dict, int]:
    return _pause(args, runner)


def resume(args, runner) -> tuple[dict, int]:
    return _resume(args, runner)
