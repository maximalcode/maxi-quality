"""Explicitly switch the selected Guardian integration between hosts."""

from __future__ import annotations

import contextlib
import importlib
import io
import json
import os
from pathlib import Path
import subprocess

import guardian_lifecycle as lifecycle
import guardian_pause as pause
import guardian_setup as setup

runtime = importlib.import_module("quality-runtime")


def _settings_name(host: str) -> str:
    if host == "claude":
        return ".claude/settings.json"
    if host == "codex":
        return ".codex/hooks.json"
    raise ValueError(f"unsupported Guardian host {host!r}")


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _owned_launcher(root: Path, state: dict, host: str) -> str:
    """Return the one launcher used by the selected host's owned hooks."""
    settings = setup.settings(root, _settings_name(host))
    records = state.get("owned", {}).get("hooks")
    if not isinstance(records, list) or not records:
        raise setup.Refused("selected Guardian has no usable owned hooks")
    launchers = set()
    for record in records:
        if not isinstance(record, dict):
            raise setup.Refused("selected Guardian hook ownership metadata is malformed")
        found = runtime._owned_command(
            settings, record.get("event"), record.get("name"),
            record.get("matcher"), host)
        if found is None or not lifecycle.hook_is_owned(found[0], record):
            raise setup.Refused(
                f"owned {record.get('event')} hook {record.get('name')} is missing or modified")
        launchers.add((found[1], found[2]))
    if len(launchers) != 1:
        raise setup.Refused("selected Guardian hooks do not share one pinned launcher")
    return next(iter(launchers))[0]


def _target_conflict(settings: dict, host: str) -> str | None:
    """Reject recognizable or ambiguous existing Guardian wiring."""
    if runtime._residual_guard_hooks(settings):
        return "target host already has Guardian hooks; reconcile them before switching"
    hooks = settings.get("hooks", {})
    if not isinstance(hooks, dict):
        return f"{_settings_name(host)} has a malformed hooks object"
    markers = ("quality-runtime", "agent-guard", "stop-gate", "sample-guard",
               "no-verify-guard", "codex-patch-guard")
    for groups in hooks.values():
        if not isinstance(groups, list):
            return f"{_settings_name(host)} has malformed hook groups"
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                return f"{_settings_name(host)} has malformed hook groups"
            for entry in group["hooks"]:
                command = entry.get("command") if isinstance(entry, dict) else None
                if isinstance(command, str) and any(marker in command for marker in markers):
                    return (f"{_settings_name(host)} contains an unclear Guardian-like hook; "
                            "reconcile it before switching")
    return None


def _validate_target_settings(root: Path, target: str, settings: dict,
                              lock: dict) -> None:
    """Validate generated target wiring without claiming host trust."""
    setup.validate_host_configuration(root, target)
    if target == "claude" and settings.get("disableAllHooks") is True:
        raise setup.Refused("target Claude settings disable all hooks")
    expected_samples = (root / "samples" / "expected").is_dir()
    for event, matcher, name, _timeout in runtime.host_specs(target, expected_samples):
        found = runtime._owned_command(settings, event, name, matcher, target)
        if found is None:
            raise setup.Refused(
                f"generated target is missing {event} hook {name} with matcher {matcher or '<none>'}")
    if lock.get("guard_enabled") is not True:
        raise setup.Refused("the shared runtime lock is not enabled for the selected Guardian")


def _skill_plan(root: Path, state: dict, target: str) -> tuple[dict[str, str], Path | None, str | None]:
    """Plan an owned skill-link move without taking over an unclear link."""
    source_link_data = state.get("skill_link")
    old_link = None
    source_target = None
    if source_link_data is not None:
        if not isinstance(source_link_data, dict) or not isinstance(source_link_data.get("path"), str):
            raise setup.Refused("selected Guardian skill ownership metadata is malformed")
        old_link = lifecycle.owned_skill_link(root, state)
        expected_old = root / source_link_data["path"]
        if old_link is None:
            raise setup.Refused("selected Guardian skill link is missing or modified; reconcile it before switching")
        source_target = str(old_link.resolve())
        if expected_old != old_link:
            raise setup.Refused("selected Guardian skill ownership path is inconsistent")

    target_path = root / lifecycle.skill_path_for_host(target)
    if target_path.exists() or target_path.is_symlink():
        raise setup.Refused(f"{target_path} already exists; refusing to take over the target skill")
    links = {}
    if source_target is not None:
        links[str(target_path.relative_to(root))] = source_target
    return links, old_link, source_target


def _snapshot(root: Path, names: set[str]) -> dict[str, tuple[str, bytes | str] | None]:
    saved = {}
    for name in names:
        path = root / name
        # A link itself may be the owned skill path we are moving.  Its parent
        # chain still must be ordinary project directories.
        for parent in path.parents:
            if parent == root:
                break
            if parent.is_symlink():
                raise setup.Refused(f"{path}: reconcile symbolic links before switching")
        if path.is_symlink():
            saved[name] = ("symlink", os.readlink(path))
        elif path.exists():
            saved[name] = ("file", path.read_bytes())
        else:
            saved[name] = None
    return saved


def _restore(root: Path, saved: dict[str, tuple[str, bytes | str] | None]) -> None:
    for name, value in saved.items():
        path = root / name
        if path.is_symlink() or path.exists():
            if path.is_dir() and not path.is_symlink():
                raise setup.Refused(f"cannot restore non-file path {path}")
            path.unlink()
        if value is None:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        kind, content = value
        if kind == "symlink":
            path.symlink_to(content)
        else:
            path.write_bytes(content)


def _diagnose_target(root: Path, target: str) -> dict:
    report = runtime.diagnose(root, host=target)
    failures = [item["detail"] for item in report.get("checks", [])
                if item.get("status") == "fail"]
    if failures:
        raise setup.Refused("new host validation failed: " + "; ".join(failures))
    return report


def _plan(args, runner) -> dict:
    root = Path(args.root).resolve()
    if runner.repo_root(str(root)) != str(root):
        raise setup.Refused("target must be a Git working tree root")
    state = lifecycle.read_state(root)
    if not state:
        raise setup.Refused("switch requires a recorded selected-host Guardian installation")
    source = state["selected_host"]
    target = args.host
    if source == target:
        return {"root": root, "state": state, "source": source, "target": target,
                "changes": {}, "links": {}, "remove_link": None, "owned": None,
                "lock": None, "gate": None, "target_settings": None,
                "outcome": "unchanged"}
    if state.get("lifecycle") == "paused":
        raise setup.Refused("Guardian is paused; resume it before switching hosts")
    if state.get("lifecycle") == "removed":
        raise setup.Refused("Guardian was removed; re-setup the selected host before switching")

    lock = pause._check_active(root, state, source)
    gate = setup.read_object(setup.safe_path(root, ".claude/agent-guard.json"))
    if not isinstance(gate.get("gate_command"), str) or not gate["gate_command"].strip():
        raise setup.Refused("the existing project gate is missing or empty")
    target_name = _settings_name(target)
    target_existing = setup.settings(root, target_name)
    conflict = _target_conflict(target_existing, target)
    if conflict:
        raise setup.Refused(conflict)
    launcher = _owned_launcher(root, state, source)
    with contextlib.redirect_stdout(io.StringIO()):
        proposed = setup.proposed_files(root, gate, lock, True, launcher,
                                        host=None, update=False, selected_host=target)
    target_bytes = proposed.get(target_name)
    target_settings = (json.loads(target_bytes) if target_bytes is not None
                       else target_existing)
    _validate_target_settings(root, target, target_settings, lock)
    links, old_link, source_target = _skill_plan(root, state, target)

    deactivation = pause.plan_deactivation(root, state)
    if deactivation["conflicts"]:
        raise setup.Refused("owned settings changed; reconcile them before switching")
    changes = {name: _json_bytes(value) for name, value in deactivation["settings"].items()}
    changes.update(proposed)
    expected_samples = (root / "samples" / "expected").is_dir()
    owned = lifecycle.owned_records(target_settings, target, expected_samples, runtime)
    target_skill_path = lifecycle.skill_path_for_host(target) if source_target else None
    state_bytes = lifecycle.state_bytes(
        target, lock["version"], lock["commit"], target_skill_path,
        source_target, owned, lifecycle="active")
    changes[lifecycle.STATE_NAME] = state_bytes
    report_changes = {}
    for name, content in changes.items():
        try:
            report_changes[name] = content.decode("utf-8")
        except UnicodeDecodeError:
            report_changes[name] = "<binary content>"
    report_changes.update({name: f"symlink -> {value}" for name, value in links.items()})
    remove_link = (str(old_link.relative_to(root)) if old_link is not None else None)
    return {"root": root, "state": state, "source": source, "target": target,
            "changes": changes, "report_changes": report_changes, "links": links,
            "remove_link": remove_link, "owned": deactivation["removed"],
            "lock": lock, "gate": gate, "target_settings": target_settings,
            "outcome": "preview"}


def _switch(args, runner) -> tuple[dict, int]:
    report = {"outcome": "refused", "from_host": None, "to_host": args.host,
              "changes": {}, "deactivated": {"hooks": [], "deny": []},
              "trust": "unverified", "error": None}
    try:
        runner.clear_git_environment()
        plan = _plan(args, runner)
        report.update(from_host=plan["source"], to_host=plan["target"],
                      host=plan["target"], outcome=plan["outcome"])
        if plan["outcome"] == "unchanged":
            return report, 0
        report["changes"] = plan["report_changes"]
        report["deactivated"] = plan["owned"]
        report["gate"] = plan["gate"]["gate_command"]
        report["release"] = {"version": plan["lock"]["version"],
                              "commit": plan["lock"]["commit"]}
        report["next_step"] = (
            "Review the selected host and owned changes. Apply explicitly; host trust and "
            "live enforcement remain unverified until reviewed in the selected host.")
        if not args.apply:
            return report, 0

        names = set(plan["changes"]) | set(plan["links"])
        if plan["remove_link"]:
            names.add(plan["remove_link"])
        saved = _snapshot(plan["root"], names)
        try:
            setup.activate(plan["root"], plan["changes"], plan["links"])
            if plan["remove_link"]:
                old_link = plan["root"] / plan["remove_link"]
                if not old_link.is_symlink():
                    raise setup.Refused("owned source skill link changed during switch")
                old_link.unlink()
            validation = _diagnose_target(plan["root"], plan["target"])
        except Exception:
            _restore(plan["root"], saved)
            raise
        report["validation"] = validation
        report["outcome"] = "switched"
        return report, 0
    except (OSError, ValueError, setup.Refused, runtime.RuntimeError_,
            subprocess.CalledProcessError) as exc:
        report["outcome"] = "refused"
        report["error"] = str(exc)
        return report, 3


def switch(args, runner) -> tuple[dict, int]:
    return _switch(args, runner)
