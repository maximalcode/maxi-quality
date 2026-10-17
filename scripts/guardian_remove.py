"""Safely remove only the selected host's recorded Guardian integration."""

from __future__ import annotations

import copy
import hashlib
import importlib
import json
from pathlib import Path
import subprocess

import guardian_lifecycle as lifecycle
import guardian_pause as pause
import guardian_setup as setup

runtime = importlib.import_module("quality-runtime")


def _instruction_name(host: str) -> tuple[str, str, str]:
    if host == "claude":
        return ("CLAUDE.md", "<!-- BEGIN maxi-quality agent-guard",
                "<!-- END maxi-quality agent-guard -->")
    if host == "codex":
        return ("AGENTS.md", "<!-- BEGIN maxi-quality codex-guard",
                "<!-- END maxi-quality codex-guard -->")
    raise setup.Refused(f"unsupported Guardian host {host!r}")


def _plan_instruction(root: Path, host: str, expected_digest: str | None) -> tuple[dict[str, bytes], list[str]]:
    """Plan removal of one unchanged marker-delimited region, preserving its surroundings."""
    name, begin, end = _instruction_name(host)
    path = setup.safe_path(root, name)
    if not path.exists():
        return {}, []
    text = path.read_text(encoding="utf-8")
    begin_count = text.count(begin)
    end_count = text.count(end)
    if not begin_count and not end_count:
        return {}, []
    if begin_count != 1 or end_count != 1:
        return {}, [f"{name} has an ambiguous Guardian instruction region"]
    start = text.find(begin)
    opening_end = text.find("-->", start)
    end_start = text.find(end, opening_end + 3)
    if opening_end < 0 or end_start < 0:
        return {}, [f"{name} has an incomplete Guardian instruction region"]
    body = text[opening_end + 3:end_start]
    actual_digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    if not expected_digest or actual_digest != expected_digest:
        return {}, [f"{name} Guardian instruction region was changed; preserving it"]
    end_after = end_start + len(end)
    if text[end_after:end_after + 2] == "\r\n":
        end_after += 2
    elif text[end_after:end_after + 1] == "\n":
        end_after += 1
    updated = text[:start] + text[end_after:]
    if updated == text:
        return {}, []
    return {name: updated.encode("utf-8")}, []


def _plan_skill_link(root: Path, state: dict) -> tuple[list[str], list[str]]:
    link_record = state.get("skill_link")
    if link_record is None:
        return [], []
    path = lifecycle.owned_skill_link(root, state)
    if path is not None:
        return [str(path.relative_to(root))], []
    relative = lifecycle.skill_path_for_host(state.get("selected_host"))
    candidate = root / relative
    if candidate.exists() or candidate.is_symlink():
        return [], [f"{relative} is no longer the exact recorded Guardian skill link; preserving it"]
    # A link removed by the user is already absent and needs no repair.
    return [], []


def _prune_empty_owned_hook_groups(settings: dict, removed: list[dict]) -> None:
    """Drop only empty wrappers made empty by the exact planned hook removals."""
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return
    groups_by_event: dict[str, set[int]] = {}
    for record in removed:
        if isinstance(record, dict) and isinstance(record.get("event"), str):
            groups_by_event.setdefault(record["event"], set()).add(record.get("group_index"))
    for event, indexes in groups_by_event.items():
        groups = hooks.get(event)
        if not isinstance(groups, list):
            continue
        for index in sorted((i for i in indexes if isinstance(i, int)), reverse=True):
            if index >= len(groups):
                continue
            group = groups[index]
            if (isinstance(group, dict) and group.get("hooks") == []
                    and set(group).issubset({"matcher", "hooks"})):
                del groups[index]
        if not groups:
            hooks.pop(event, None)
    if not hooks:
        settings.pop("hooks", None)


def _lock_change(root: Path, host: str) -> tuple[dict[str, bytes], list[str], list[str]]:
    """Disable only selected-host runtime enforcement while retaining its lock."""
    name = runtime.LOCK_NAME
    path = setup.safe_path(root, name)
    if not path.exists():
        return {}, [], []
    try:
        lock = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {}, [], [f"{name} is unreadable; preserving it: {exc}"]
    if not isinstance(lock, dict) or not isinstance(lock.get("guard_enabled"), bool):
        return {}, [], [f"{name} has an unsupported shape; preserving it"]
    other_host = "codex" if host == "claude" else "claude"
    other_hooks = lifecycle.has_guard_hooks(root, other_host)
    if other_hooks is None:
        lock_enabled = True
        retained = [f"{other_host} settings are unreadable; shared runtime remains enabled"]
    else:
        lock_enabled = other_hooks
        retained = []
    if lock["guard_enabled"] == lock_enabled:
        return {}, retained, []
    lock["guard_enabled"] = lock_enabled
    content = (json.dumps(lock, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    return {name: content}, retained, []


def _state_bytes(state: dict) -> bytes:
    removed = copy.deepcopy(state)
    removed["lifecycle"] = "removed"
    return (json.dumps(removed, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def remove(args, runner) -> tuple[dict, int]:
    report = {"outcome": "refused", "host": None, "changes": {}, "remove": [],
              "conflicts": [], "retained": [], "error": None}
    try:
        runner.clear_git_environment()
        root = Path(args.root).resolve()
        if runner.repo_root(str(root)) != str(root):
            raise setup.Refused("target must be a Git working tree root")
        state = lifecycle.read_state(root)
        if not state:
            raise setup.Refused("Guardian has no recorded selected-host installation to remove safely")
        host = args.host or state["selected_host"]
        report["host"] = host
        if host != state["selected_host"]:
            raise setup.Refused("remove applies only to the recorded selected host")

        lifecycle_state = state.get("lifecycle", "active")
        changes: dict[str, bytes] = {}
        conflicts: list[str] = []
        retained = [".claude/agent-guard.json (project gate)",
                    ".claude/agent-guard-receipt.json and check history",
                    "pinned runtime files and shared runtime cache"]

        if lifecycle_state == "active":
            deactivation = pause.plan_deactivation(root, state)
            conflicts.extend(deactivation["conflicts"])
            if not conflicts:
                settings_name = pause._settings_name(host)
                planned_settings = deactivation["settings"].get(
                    settings_name, pause._setting(root, settings_name))
                _prune_empty_owned_hook_groups(
                    planned_settings, deactivation["removed"]["hooks"])
                if runtime._residual_guard_hooks(planned_settings):
                    conflicts.append("additional or ambiguous Guardian hooks remain; preserving settings")
                else:
                    for name, value in deactivation["settings"].items():
                        changes[name] = (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode()
        elif lifecycle_state in ("paused", "removed"):
            # Pause has already removed the recorded hook/deny entries. Do not
            # treat their expected absence as a deactivation conflict; any
            # reintroduced Guardian wiring is ambiguous and must be reconciled.
            remaining = lifecycle.has_guard_hooks(root, host)
            if remaining is not False:
                conflicts.append("Guardian hooks are present or unreadable after deactivation; preserving settings")
        else:
            conflicts.append(f"unsupported Guardian lifecycle state: {lifecycle_state}")

        instruction_changes, instruction_conflicts = _plan_instruction(
            root, host, state.get("owned", {}).get("instruction_region"))
        conflicts.extend(instruction_conflicts)
        link_removals, link_conflicts = _plan_skill_link(root, state)
        conflicts.extend(link_conflicts)

        lock_changes, lock_retained, lock_conflicts = _lock_change(root, host)
        conflicts.extend(lock_conflicts)
        retained.extend(lock_retained)
        if conflicts:
            report["conflicts"] = conflicts
            raise setup.Refused("owned Guardian content changed or is ambiguous; reconcile it before removal")

        changes.update(instruction_changes)
        changes.update(lock_changes)
        state_content = _state_bytes(state)
        state_name = lifecycle.STATE_NAME
        setup.safe_path(root, state_name)
        if not (root / state_name).exists() or (root / state_name).read_bytes() != state_content:
            changes[state_name] = state_content

        report.update(outcome="preview",
                      changes={name: content.decode("utf-8") for name, content in changes.items()},
                      remove=link_removals,
                      retained=retained)
        if not args.apply:
            return report, 0

        removed_links = []
        try:
            for relative in link_removals:
                path = root / relative
                # Revalidate immediately before unlinking the exact recorded link.
                if lifecycle.owned_skill_link(root, state) != path:
                    raise setup.Refused(f"{relative} changed before removal; preserving it")
                path.unlink()
                removed_links.append((path, state["skill_link"]["target"]))
            setup.activate(root, changes)
        except (OSError, setup.Refused):
            # Keep a failed apply retryable if a later filesystem write fails.
            for path, target in reversed(removed_links):
                if not path.exists() and not path.is_symlink():
                    path.symlink_to(target, target_is_directory=True)
            raise
        report["outcome"] = "removed" if changes or link_removals else "unchanged"
        return report, 0
    except (OSError, ValueError, setup.Refused, subprocess.CalledProcessError) as exc:
        report["outcome"] = "refused"
        report["error"] = str(exc)
        return report, 3
