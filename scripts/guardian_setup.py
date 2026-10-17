"""Preview and deliberately apply local gate and pinned Guardian setup."""

from __future__ import annotations

import contextlib
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import tomllib

runtime = importlib.import_module("quality-runtime")
migration = importlib.import_module("quality-runtime-migrate")
lifecycle = importlib.import_module("guardian_lifecycle")


class Refused(ValueError):
    """Configuration needs a deliberate correction before setup can proceed."""


def read_object(path: Path) -> dict:
    if not path.exists():
        return {}
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise Refused(f"{path} must contain an object")
    return value


def safe_path(root: Path, name: str) -> Path:
    path = root / name
    for part in (path, *path.parents):
        if part == root:
            break
        if part.is_symlink():
            raise Refused(f"{path}: reconcile symbolic links before setup")
    if path.exists() and not path.is_file():
        raise Refused(f"{path} must be a regular file")
    return path


def settings(root: Path, name: str) -> dict:
    value = read_object(safe_path(root, name))
    hooks = value.get("hooks", {})
    if not isinstance(hooks, dict):
        raise Refused(f"{name}: hooks must be an object")
    for groups in hooks.values():
        if not isinstance(groups, list):
            raise Refused(f"{name}: hook groups must be arrays")
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                raise Refused(f"{name}: malformed hook group")
            for entry in group["hooks"]:
                if not isinstance(entry, dict):
                    raise Refused(f"{name}: malformed hook entry")
    return value


def discover(root: Path, trusted_source: Path | None = None,
             allow_removed: bool = False) -> tuple[dict, dict | None, str, str | None, list[str]]:
    gate = read_object(safe_path(root, ".claude/agent-guard.json"))
    if (root / ".claude/agent-guard.json").exists() and (
            not isinstance(gate.get("gate_command"), str) or not gate["gate_command"].strip()):
        raise Refused("existing gate declaration has no non-empty gate_command")
    safe_path(root, runtime.LOCK_NAME)
    lock = runtime.read_lock(root, require_guard=False) if (root / runtime.LOCK_NAME).exists() else None
    hosts = []
    for host, name in (("claude", ".claude/settings.json"), ("codex", ".codex/hooks.json")):
        value = settings(root, name)
        if runtime._residual_guard_hooks(value):
            hosts.append(host)
    if len(hosts) > 1:
        raise Refused("multiple Guardian hosts are configured; reconcile the selected integration first")
    host = hosts[0] if hosts else None
    legacy = runtime._legacy_profile(root, None)
    if lock and legacy:
        raise Refused("conflicting versioned and legacy runtime configuration")
    if lock and lock["guard_enabled"] != bool(host) and not (allow_removed and not host):
        raise Refused("release lock and installed host hooks disagree")
    if host and not lock and not legacy:
        raise Refused("host hooks have no supported installation; repair the installation first")
    profile = legacy or ("versioned" if lock else "local")
    if legacy:
        if not host:
            raise Refused("legacy guard files have no supported host wiring")
        verifier = importlib.import_module("agent-settings")
        with contextlib.redirect_stderr(io.StringIO()) as errors:
            if verifier.verify(str(root / ".claude/settings.json"), str(root)):
                raise Refused(errors.getvalue().strip())
    if host and lock:
        trusted_launchers = (runtime.trusted_launcher_hashes(trusted_source)
                             if trusted_source is not None else None)
        report = runtime.diagnose(root, host=host, trusted_launchers=trusted_launchers)
        failures = [c["detail"] for c in report["checks"] if c["status"] == "fail"]
        if failures:
            raise Refused("; ".join(failures))
    found = []
    for name in ("Cargo.toml", "rust-toolchain.toml", ".cargo/config.toml", "rustfmt.toml", "deny.toml"):
        path = safe_path(root, name)
        if path.exists():
            tomllib.loads(path.read_text())
            found.append(name)
    return gate, lock, profile, host, found


def proposed_files(root: Path, gate: dict, lock: dict | None, enable: bool,
                   launcher: str, host: str | None = None,
                   update: bool = False, selected_host: str | None = None) -> dict[str, bytes]:
    names = [".claude/agent-guard.json"]
    if lock is not None:
        names.append(runtime.LOCK_NAME)
    migrate = enable or update
    operation_host = selected_host or host
    if migrate and operation_host == "codex":
        names.extend([".codex/hooks.json", "AGENTS.md", ".gitignore"])
    elif migrate and operation_host == "claude":
        names.extend([".claude/settings.json", ".gitignore"])
        instruction = migration.instruction_path(root)
        if instruction is not None:
            names.append(instruction.name)
    for name in names:
        safe_path(root, name)
    with tempfile.TemporaryDirectory(prefix="guardian-plan-") as directory:
        stage = Path(directory)
        for name in names:
            source = root / name
            if source.exists():
                target = stage / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.read_bytes())
        if (root / "samples/expected").is_dir():
            (stage / "samples/expected").mkdir(parents=True)
        existing_gate = read_object(stage / names[0])
        if gate != existing_gate:
            migration.write_json(stage / names[0], gate)
        if migrate:
            migration.migrate(stage, lock["version"], lock["commit"], launcher, False,
                              host=operation_host or "claude")
        elif lock is not None and lock != read_object(stage / runtime.LOCK_NAME):
            migration.write_json(stage / runtime.LOCK_NAME, lock)
        return {name: (stage / name).read_bytes() for name in names
                if (stage / name).is_file() and (not (root / name).exists()
                or (stage / name).read_bytes() != (root / name).read_bytes())}


def skill_link(root: Path, source: Path, host: str) -> tuple[str, str, bool]:
    """Plan a project-local link to the selected host's shared Guardian skill."""
    name = lifecycle.skill_path_for_host(host)
    target = source / "skills/guardian"
    if not target.is_dir() or not (target / "SKILL.md").is_file():
        raise Refused(f"trusted source has no shared Guardian skill at {target}")
    path = root / name
    for parent in (path.parent, *path.parent.parents):
        if parent == root.parent:
            break
        if parent == root:
            continue
        if parent.is_symlink():
            raise Refused(f"{parent}: reconcile symbolic links before setup")
    if path.is_symlink() and path.resolve() == target.resolve():
        return name, str(target), False
    if path.exists() or path.is_symlink():
        return name, str(target), False
    return name, str(target), True


def region_digest(path: Path, marker: str,
                  end_marker: str = "<!-- END maxi-quality agent-guard -->") -> str | None:
    if not path.exists() or not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    start = text.find(marker)
    if start < 0:
        return None
    opening_end = text.find("-->", start)
    end = text.find(end_marker, opening_end)
    if opening_end < 0 or end < 0:
        return None
    return hashlib.sha256(text[opening_end + 3:end].encode()).hexdigest()


def validate_payload(source: Path, lock: dict, guardian: bool) -> None:
    # Validate without touching the user's cache or target. No network access.
    with tempfile.TemporaryDirectory(prefix="guardian-payload-") as directory:
        payload = runtime.prepare(source, lock["version"], lock["commit"], directory)
        for path in payload.glob("*.py"):
            compile(path.read_bytes(), str(path), "exec")
        launcher = runtime._git(source, "show", f"{lock['commit']}:scripts/quality-runtime.py")
        compile(launcher, "quality-runtime.py", "exec")
        if guardian and not (payload / "codex-patch-guard.py").exists():
            raise Refused("requested payload predates native Codex hooks; select a compatible immutable release")


def validate_workflows(root: Path, lock: dict) -> None:
    paths = sorted({*(root / ".github/workflows").glob("*.yml"),
                    *(root / ".github/workflows").glob("*.yaml")})
    if not paths:
        return
    try:
        checker = importlib.import_module("check-quality-lock")
    except ImportError as exc:
        raise Refused("install PyYAML to validate the existing workflow pins before setup") from exc
    with tempfile.TemporaryDirectory(prefix="guardian-lock-") as directory:
        stage = Path(directory)
        migration.write_json(stage / runtime.LOCK_NAME, lock)
        for path in paths:
            target = stage / ".github/workflows" / path.name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(path.read_bytes())
        try:
            errors = checker.check(stage)
        except checker.yaml.YAMLError as exc:
            raise Refused(f"unreadable workflow configuration: {exc}") from exc
        if errors:
            raise Refused("reconcile workflow pins explicitly; setup never changes CI: " + "; ".join(errors))


def validate_host_configuration(root: Path, host: str) -> None:
    """Validate existing host-specific settings before enabling that adapter."""
    if host != "codex":
        return
    config = safe_path(root, ".codex/config.toml")
    if not config.exists():
        return
    parsed = tomllib.loads(config.read_text())
    features = parsed.get("features", {})
    if not isinstance(features, dict) or any(
            features.get(key) is False for key in ("hooks", "codex_hooks")):
        raise Refused("project configuration disables hooks; enable them deliberately before Guardian setup")
    if "hooks" in parsed:
        raise Refused("inline Codex hooks require reconciliation before Guardian setup")


def activate(root: Path, changes: dict[str, bytes], links: dict[str, str] | None = None) -> None:
    links = links or {}
    originals = {name: (root / name).read_bytes() if (root / name).exists() else None for name in changes}
    created = []
    try:
        for name, content in changes.items():
            path = root / name
            if not path.parent.exists():
                path.parent.mkdir(parents=True)
                created.append(path.parent)
            fd, temporary = tempfile.mkstemp(prefix=".guardian-", dir=path.parent)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(content)
                if path.exists():
                    os.chmod(temporary, path.stat().st_mode & 0o777)
                os.replace(temporary, path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        for name, target in links.items():
            path = root / name
            if path.is_symlink() and path.resolve() == Path(target).resolve():
                continue
            if path.exists() or path.is_symlink():
                raise Refused(f"{path} already exists; preserving the existing skill")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.symlink_to(target, target_is_directory=True)
            created.append(path)
    except (OSError, Refused):
        for name, content in originals.items():
            path = root / name
            if content is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(content)
        for path in reversed(created):
            try:
                if path.is_symlink():
                    path.unlink()
                elif path.is_dir() and not any(path.iterdir()):
                    path.rmdir()
            except OSError:
                pass
        raise


def setup(args, runner) -> tuple[dict, int]:
    report = {"outcome": "refused", "changes": {}, "verification": "not_run",
              "host_trust": "unverified", "tests": "not_inferred", "error": None,
              "conflicts": []}
    try:
        runner.clear_git_environment()
        root = Path(args.root).resolve()
        if runner.repo_root(str(root)) != str(root):
            raise Refused("target must be a Git working tree root")
        source = Path(args.source).resolve()
        previous_state = lifecycle.read_state(root)
        prior_lifecycle = previous_state.get("lifecycle", "active")
        removed = prior_lifecycle == "removed"
        if prior_lifecycle == "paused":
            raise Refused("Guardian is paused; use the explicit resume operation first")
        if removed:
            if (args.guardian != previous_state["selected_host"]
                    or not args.version or not args.commit):
                raise Refused("Guardian was removed; re-setup requires explicit --guardian, --version and --commit")
            if lifecycle.has_guard_hooks(root, previous_state["selected_host"]) is not False:
                raise Refused("removed Guardian settings are still present or unreadable; reconcile them before re-setup")
        gate, old_lock, profile, host, found = discover(root, source, allow_removed=removed)
        if (args.guardian and previous_state
                and previous_state["selected_host"] != args.guardian):
            raise Refused("changing an existing host is outside setup; request an explicit switch")
        report.update(current_gate=gate.get("gate_command"), current_version=old_lock,
                      installation_profile=profile, host=host, quality_configuration=found)
        if args.gate is not None:
            if not args.gate.strip():
                raise Refused("--gate must be non-empty")
            gate["gate_command"] = args.gate
        report["selected_gate"] = gate.get("gate_command")
        report["suggestions"] = (["cargo fmt --check", "cargo clippy --offline", "cargo test --offline"]
                                 if "Cargo.toml" in found else [])
        report["suggestion_policy"] = "Suggestions require explicit --gate selection; no test execution is inferred."
        if not gate.get("gate_command"):
            raise Refused("no declared gate; preview the suggestions and select --gate explicitly")
        if bool(args.version) != bool(args.commit):
            raise Refused("select both --version and --commit")
        enable = args.guardian is not None and host is None
        if args.guardian and host and host != args.guardian:
            raise Refused("changing an existing host is outside setup; existing integration was preserved")
        if args.version and profile.startswith("legacy"):
            raise Refused("legacy installation retained: pinned updates require an explicit legacy migration first")
        lock = dict(old_lock) if old_lock else None
        if args.version:
            lock = {"schema": runtime.SCHEMA, "source": runtime.SOURCE,
                    "version": args.version, "commit": args.commit,
                    "guard_enabled": bool(host or enable)}
        if enable:
            if not lock:
                raise Refused("Guardian requires --version and --commit for an immutable release")
            lock["guard_enabled"] = True
        report["requested_version"] = lock
        report["host"] = args.guardian if enable else (args.guardian or host)
        if enable:
            validate_host_configuration(root, report["host"])
        changed_version = lock is not None and (lock != old_lock or enable)
        if lock:
            validate_workflows(root, lock)
        if changed_version:
            validate_payload(source, lock, report["host"] == "codex")
        launcher_dir = Path.home() / ".local/share/maxi-quality/launchers" / (lock["commit"] if lock else "unused")
        launcher = str(launcher_dir / "quality-runtime")
        update_installation = bool(changed_version and host and lock and lock.get("guard_enabled") is True)
        with contextlib.redirect_stdout(io.StringIO()):
            changes = proposed_files(root, gate, lock, enable, launcher, host,
                                     update_installation, report["host"])
        links: dict[str, str] = {}
        skill_owned = False
        if args.guardian and lock:
            skill_name, skill_target, create_link = skill_link(root, source, args.guardian)
            skill_path = root / skill_name
            if skill_path.exists() or skill_path.is_symlink():
                if not (skill_path.is_symlink() and skill_path.resolve() == Path(skill_target).resolve()):
                    report["conflicts"].append(skill_name)
                else:
                    previously_owned = lifecycle.owned_skill_link(root, previous_state)
                    skill_owned = previously_owned == skill_path
            elif create_link:
                links[skill_name] = skill_target
                skill_owned = True
            settings_name = ".codex/hooks.json" if args.guardian == "codex" else ".claude/settings.json"
            settings_bytes = changes.get(settings_name)
            settings_value = (json.loads(settings_bytes) if settings_bytes is not None else
                              settings(root, settings_name))
            expected_samples = (root / "samples/expected").is_dir()
            owned = lifecycle.owned_records(settings_value, args.guardian,
                                             expected_samples, runtime)
            instruction_name = "AGENTS.md" if args.guardian == "codex" else "CLAUDE.md"
            begin_marker = ("<!-- BEGIN maxi-quality codex-guard"
                            if args.guardian == "codex"
                            else "<!-- BEGIN maxi-quality agent-guard")
            end_marker = ("<!-- END maxi-quality codex-guard -->"
                          if args.guardian == "codex"
                          else "<!-- END maxi-quality agent-guard -->")
            instruction = changes.get(instruction_name)
            if instruction is None:
                candidate = migration.instruction_path(root)
                instruction_path = candidate if candidate else root / instruction_name
                owned["instruction_region"] = region_digest(
                    instruction_path, begin_marker, end_marker)
            else:
                with tempfile.NamedTemporaryFile() as temporary:
                    temporary.write(instruction)
                    temporary.flush()
                    owned["instruction_region"] = region_digest(
                        Path(temporary.name), begin_marker, end_marker)
            state = lifecycle.state_bytes(args.guardian, lock["version"], lock["commit"],
                                          skill_name if skill_owned else None,
                                          skill_target if skill_owned else None,
                                          owned)
            state_path = lifecycle.STATE_NAME
            safe_path(root, state_path)
            if not (root / state_path).exists() or (root / state_path).read_bytes() != state:
                changes[state_path] = state
        report["changes"] = {name: content.decode() for name, content in changes.items()}
        report["changes"].update({name: f"symlink -> {target}" for name, target in links.items()})
        report["commands"] = [gate["gate_command"]]
        report["trust_prerequisite"] = ("Review and trust the exact definitions in Codex /hooks; live enforcement remains unverified."
                                         if report["host"] == "codex" else
                                         "Review the project hook settings in Claude Code; live enforcement remains unverified."
                                         if enable and report["host"] == "claude" else "No new host setup.")
        report["next_step"] = (
            "Check prerequisites remain unverified; preview never executes checks. After "
            "applying any intended changes, use guardian.py run with the project root and "
            "--base to execute the whole selected gate. If it fails, retain the output and inspect "
            f"the prerequisite evidence: {runner.RECOVERY_GUIDE}")
        report["outcome"] = "preview"
        if not args.apply:
            return report, 0
        if changed_version:
            runtime.prepare(source, lock["version"], lock["commit"], None)
        if changed_version and lock and lock.get("guard_enabled") is True:
            runtime.install_launcher(source, lock["commit"], str(launcher_dir))
        activate(root, changes, links)
        report["outcome"] = "applied" if changes else "unchanged"
        if changed_version:
            # Record the selected compound shell command through step 1.
            observation, rc = runner.run(args)
            report["verification"] = observation
            report["next_step"] = observation["next_step"]
            if rc:
                report["outcome"] = "applied_checks_failed"
            return report, rc
        return report, 0
    except (OSError, ValueError, SyntaxError, runtime.RuntimeError_, migration.Refused,
            subprocess.CalledProcessError) as exc:
        report["error"] = str(exc)
        return report, 3
