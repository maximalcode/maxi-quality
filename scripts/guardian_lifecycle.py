"""Small persisted ownership contract shared by Guardian lifecycle commands."""

from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path

STATE_NAME = ".claude/guardian-state.json"
SCHEMA = 1


def canonical_digest(value: object) -> str:
    """Hash one exact JSON value so later operations can preserve user edits."""
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def state_path(root: Path) -> Path:
    return root / STATE_NAME


def read_state(root: Path) -> dict:
    """Read selected-host metadata without changing the project."""
    path = state_path(root)
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"{path} is not readable Guardian state: {exc}") from exc
    if (not isinstance(value, dict) or value.get("schema") != SCHEMA
            or value.get("selected_host") not in ("claude", "codex")
            or not isinstance(value.get("release"), dict)
            or not isinstance(value.get("owned"), dict)
            or value.get("lifecycle", "active") not in ("active", "paused", "removed")):
        raise ValueError(f"{path} has an unsupported Guardian state shape")
    if value["selected_host"] == "codex" and value.get("skill_link"):
        expected = skill_path_for_host("codex")
        if value["skill_link"].get("path") != expected:
            raise ValueError(f"{path} names a skill link outside the Codex-owned path")
    if value["selected_host"] == "claude" and value.get("skill_link"):
        expected = skill_path_for_host("claude")
        if value["skill_link"].get("path") != expected:
            raise ValueError(f"{path} names a skill link outside the Claude-owned path")
    return value


def selected_host(root: Path, fallback: str = "claude") -> str:
    """Return the recorded host, or detect one older native integration."""
    state = read_state(root)
    if state:
        return state["selected_host"]
    detected = []
    runtime = importlib.import_module("quality-runtime")
    for host, name in (("claude", ".claude/settings.json"),
                       ("codex", ".codex/hooks.json")):
        path = root / name
        if not path.exists():
            continue
        try:
            settings = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(settings, dict) and runtime._residual_guard_hooks(settings):
            detected.append(host)
    return detected[0] if len(detected) == 1 else fallback


def selection_source(root: Path) -> str:
    """Describe whether host selection was saved, detected, or defaulted."""
    if state_path(root).exists():
        return "guardian-state"
    host = selected_host(root)
    if host != "claude":
        return "detected-integration"
    return "legacy-default"


def skill_path_for_host(host: str) -> str:
    """Return the only project-local Guardian skill path this host owns."""
    if host == "claude":
        return ".claude/skills/guardian"
    if host == "codex":
        return ".agents/skills/guardian"
    raise ValueError(f"unsupported Guardian host {host!r}")


def owned_skill_link(root: Path, state: dict) -> Path | None:
    """Return a skill link only when the state names its fixed host path."""
    host = state.get("selected_host")
    link = state.get("skill_link")
    if not isinstance(link, dict) or link.get("path") != skill_path_for_host(host):
        return None
    path = root / link["path"]
    target = link.get("target")
    if not isinstance(target, str) or not path.is_symlink():
        return None
    try:
        resolved_target = path.resolve(strict=True)
        expected_target = Path(target).resolve(strict=True)
    except OSError:
        return None
    if (resolved_target != expected_target or resolved_target.name != "guardian"
            or resolved_target.parent.name != "skills"
            or not (resolved_target.parents[1] / "scripts/guardian.py").is_file()):
        return None
    return path


def has_guard_hooks(root: Path, host: str) -> bool | None:
    """Read the fixed host settings path and detect any remaining guard wiring."""
    name = ".codex/hooks.json" if host == "codex" else ".claude/settings.json"
    path = root / name
    if not path.exists():
        return False
    try:
        settings = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(settings, dict):
        return None
    runtime = importlib.import_module("quality-runtime")
    return bool(runtime._residual_guard_hooks(settings))


def state_bytes(host: str, version: str, commit: str, skill_path: str | None,
                skill_target: str | None, owned: dict, lifecycle: str = "active") -> bytes:
    """Serialize the lifecycle contract with its exact settings ownership."""
    value = {
        "schema": SCHEMA,
        "selected_host": host,
        "lifecycle": lifecycle,
        "release": {"version": version, "commit": commit},
        "skill_link": ({"path": skill_path, "target": skill_target}
                       if skill_path and skill_target else None),
        "owned": owned,
    }
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def status_overlay(root: Path, diagnosis: dict, queried_host: str | None = None) -> dict:
    """Apply explicitly recorded lifecycle state to read-only host diagnosis."""
    state = read_state(root)
    lifecycle = state.get("lifecycle", "active") if state else "not_installed"
    result = dict(diagnosis)
    result["selected_host"] = state.get("selected_host") if state else None
    result["lifecycle"] = lifecycle
    if state and queried_host and queried_host != state.get("selected_host"):
        result["lifecycle"] = "other-host"
        result["selected_lifecycle"] = lifecycle
        return result
    if lifecycle == "paused":
        result["selected_lifecycle"] = "paused"
        pinned = state.get("release")
        release = diagnosis.get("release")
        release_matches = (isinstance(pinned, dict) and isinstance(release, dict)
                           and pinned.get("version") == release.get("version")
                           and pinned.get("commit") == release.get("commit"))
        remaining = has_guard_hooks(root, state["selected_host"])
        if release_matches and remaining is False:
            result["status"] = "paused"
            result["healthy"] = False
            result["live_enforcement"] = "inactive"
        else:
            result["lifecycle"] = "broken"
    elif lifecycle == "removed":
        if has_guard_hooks(root, state["selected_host"]) is False:
            result["status"] = "not-installed"
            result["healthy"] = False
            result["live_enforcement"] = "inactive"
        else:
            result["lifecycle"] = "conflict"
    return result


def owned_records(settings: dict, host: str, expected_samples: bool,
                  runtime) -> dict:
    """Capture exact managed hook entries and deny values from planned settings."""
    hooks = []
    for event, matcher, name, _timeout in runtime.host_specs(host, expected_samples):
        found = runtime._owned_command(settings, event, name, matcher, host)
        if found is not None:
            hooks.append({"event": event, "matcher": matcher,
                          "name": name, "sha256": canonical_digest(found[0])})
    deny = settings.get("permissions", {}).get("deny", []) if host == "claude" else []
    owned_deny = [rule for rule in deny if isinstance(rule, str) and (
        rule == "Edit(/.claude/agent-guard-receipt.json)"
        or (expected_samples and rule == "Edit(/samples/expected/**)"))]
    return {"hooks": hooks, "deny": owned_deny, "instruction_region": None}


def hook_is_owned(entry: dict, record: dict) -> bool:
    """Match a hook only while its complete managed value is unchanged."""
    return canonical_digest(entry) == record.get("sha256")
