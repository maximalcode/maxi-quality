"""Small persisted ownership contract shared by Guardian lifecycle commands."""

from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path

STATE_NAME = ".claude/guardian-state.json"
SCHEMA = 1
INSTRUCTION_MARKERS = {
    "claude": ("<!-- BEGIN maxi-quality agent-guard", "<!-- END maxi-quality agent-guard -->"),
    "codex": ("<!-- BEGIN maxi-quality codex-guard", "<!-- END maxi-quality codex-guard -->"),
}


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


def instruction_path(root: Path, host: str, *, create: bool = False) -> Path | None:
    """Select the host's instruction file, optionally choosing its new-file path."""
    if host == "codex":
        path = root / "AGENTS.md"
        return path if create or path.exists() or path.is_symlink() else None
    if host != "claude":
        raise ValueError(f"unsupported Guardian host {host!r}")
    claude = root / "CLAUDE.md"
    agents = root / "AGENTS.md"
    if claude.exists() or claude.is_symlink():
        return claude
    if agents.exists() or agents.is_symlink():
        text = agents.read_text(encoding="utf-8") if agents.is_file() else ""
        claude_begin = INSTRUCTION_MARKERS["claude"][0]
        codex_begin = INSTRUCTION_MARKERS["codex"][0]
        if codex_begin in text and claude_begin not in text:
            return claude if create else None
        return agents
    return claude if create else None


def instruction_region(path: Path, host: str, content: bytes | None = None) -> dict | None:
    """Record the path and exact body hash for one complete managed region."""
    begin, end = INSTRUCTION_MARKERS[host]
    if content is None and not path.is_file():
        return None
    text = content.decode("utf-8") if content is not None else path.read_text(encoding="utf-8")
    first = text.find(begin)
    starts = [] if first < 0 else [first]
    if first >= 0 and text.find(begin, first + len(begin)) >= 0:
        starts.append(text.find(begin, first + len(begin)))
    ends = text.count(end)
    if not starts and not ends:
        return None
    if len(starts) != 1 or ends != 1:
        raise ValueError(f"{path.name} has an ambiguous Guardian instruction region")
    start = starts[0]
    opening_end = text.find("-->", start)
    end_start = text.find(end, opening_end + 3)
    if opening_end < 0 or end_start < 0:
        raise ValueError(f"{path.name} has an incomplete Guardian instruction region")
    return {"path": path.name,
            "sha256": hashlib.sha256(text[opening_end + 3:end_start].encode("utf-8")).hexdigest()}


def verify_instruction_region(root: Path, host: str, record: object) -> None:
    """Refuse to refresh ownership when the previously recorded region changed."""
    if record is None:
        return
    if isinstance(record, dict):
        name, expected = record.get("path"), record.get("sha256")
    elif isinstance(record, str):
        path = instruction_path(root, host, create=True)
        assert path is not None
        name, expected = path.name, record
    else:
        raise ValueError("Guardian instruction region ownership is malformed")
    allowed = ("CLAUDE.md", "AGENTS.md") if host == "claude" else ("AGENTS.md",)
    if name not in allowed or not isinstance(expected, str):
        raise ValueError("Guardian instruction region ownership is malformed")
    current = instruction_region(root / name, host)
    if current is None or current["path"] != name or current["sha256"] != expected:
        raise ValueError(f"{name} Guardian instruction region was changed; preserving it")


def instruction_separator(text: str) -> str:
    """Return the exact boundary inserted when a new region is appended."""
    return "" if not text or text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")


def remove_instruction_region(root: Path, host: str, record: object,
                              content: bytes | None = None
                              ) -> tuple[dict[str, bytes], list[str]]:
    """Remove one unchanged owned region while preserving all surrounding text."""
    if record is None:
        return {}, []
    begin, end = INSTRUCTION_MARKERS[host]
    if isinstance(record, dict):
        name, expected = record.get("path"), record.get("sha256")
    elif isinstance(record, str):
        # Older state stored only a digest. Infer a path only when exactly one
        # allowed instruction file contains the matching complete region.
        expected = record
        candidates = [root / name for name in (("CLAUDE.md", "AGENTS.md")
                      if host == "claude" else ("AGENTS.md",))]
        matching = []
        for candidate in candidates:
            if candidate.is_symlink():
                continue
            try:
                parsed = instruction_region(candidate, host)
            except (OSError, UnicodeError, ValueError):
                continue
            if parsed and parsed["sha256"] == expected:
                matching.append(candidate.name)
        if len(matching) != 1:
            return {}, ["Guardian instruction region ownership is ambiguous; preserving it"]
        name = matching[0]
    else:
        return {}, ["Guardian instruction region ownership is malformed; preserving it"]
    allowed = ("CLAUDE.md", "AGENTS.md") if host == "claude" else ("AGENTS.md",)
    if name not in allowed or not isinstance(expected, str):
        return {}, ["Guardian instruction region ownership is malformed; preserving it"]
    path = root / name
    if content is None and not path.exists():
        return {}, []
    if path.is_symlink():
        return {}, [f"{name} is a symbolic link; preserving it as an ownership conflict"]
    try:
        text = content.decode("utf-8") if content is not None else path.read_text(encoding="utf-8")
        first = text.find(begin)
        starts = [] if first < 0 else [first]
        if first >= 0 and text.find(begin, first + len(begin)) >= 0:
            starts.append(text.find(begin, first + len(begin)))
        if not starts and end not in text:
            return {}, []
        if len(starts) != 1 or text.count(end) != 1:
            return {}, [f"{name} has an ambiguous Guardian instruction region; preserving it"]
        start = starts[0]
        opening_end = text.find("-->", start)
        end_start = text.find(end, opening_end + 3)
        if opening_end < 0 or end_start < 0:
            return {}, [f"{name} has an incomplete Guardian instruction region; preserving it"]
        body = text[opening_end + 3:end_start]
        actual = hashlib.sha256(body.encode("utf-8")).hexdigest()
        if actual != expected:
            return {}, [f"{name} Guardian instruction region was changed; preserving it"]
        end_after = end_start + len(end)
        if text[end_after:end_after + 2] == "\r\n":
            end_after += 2
        elif text[end_after:end_after + 1] == "\n":
            end_after += 1
        updated = text[:start] + text[end_after:]
        separator = record.get("separator") if isinstance(record, dict) else None
        if isinstance(separator, str) and separator and updated[:start].endswith(separator):
            updated = updated[:start - len(separator)] + updated[start:]
        return ({name: updated.encode("utf-8")} if updated != text else {}), []
    except (OSError, UnicodeError) as exc:
        return {}, [f"{name} Guardian instruction region could not be read; preserving it: {exc}"]


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
        pause = importlib.import_module("guardian_pause")
        preflight = pause.resume_plan(root, state, state["selected_host"])
        if preflight["error"] is None and diagnosis.get("healthy") is True:
            result["status"] = "paused"
            result["healthy"] = False
            result["live_enforcement"] = "inactive"
        else:
            result["lifecycle"] = "broken"
            result["status"] = "broken"
            result["healthy"] = False
            if preflight["error"]:
                result.setdefault("checks", []).append({
                    "id": "resume-preflight", "status": "fail",
                    "detail": preflight["error"]})
    elif lifecycle == "removed":
        if has_guard_hooks(root, state["selected_host"]) is False:
            result["status"] = "not-installed"
            result["healthy"] = False
            result["live_enforcement"] = "inactive"
        else:
            result["lifecycle"] = "conflict"
    return result


def owned_records(settings: dict, host: str, expected_samples: bool,
                  runtime, instruction: dict | None = None) -> dict:
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
    return {"hooks": hooks, "deny": owned_deny, "instruction_region": instruction}


def hook_is_owned(entry: dict, record: dict) -> bool:
    """Match a hook only while its complete managed value is unchanged."""
    return canonical_digest(entry) == record.get("sha256")
