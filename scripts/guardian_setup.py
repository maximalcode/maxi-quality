"""Preview and deliberately apply local gate and pinned Guardian setup."""

from __future__ import annotations

import contextlib
import importlib
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import tomllib
import guardian_update

runtime = importlib.import_module("quality-runtime")
migration = importlib.import_module("quality-runtime-migrate")
lifecycle = importlib.import_module("guardian_lifecycle")


class Refused(ValueError):
    """Configuration needs a deliberate correction before setup can proceed."""


class UpdateInterrupted(Exception):
    """A catchable termination arrived while candidate verification was running."""


def snapshot_files(root: Path, names: set[str]) -> dict[str, tuple[str, bytes | str, int] | None]:
    """Capture exact file or symlink state for the short update transaction."""
    saved = {}
    for name in names:
        path = root / name
        for parent in path.parents:
            if parent == root:
                break
            if parent.is_symlink():
                raise Refused(f"{path}: reconcile symbolic links before setup")
        if path.is_symlink():
            saved[name] = ("symlink", os.readlink(path), 0)
        elif path.is_file():
            saved[name] = ("file", path.read_bytes(), path.stat().st_mode & 0o777)
        elif path.exists():
            raise Refused(f"{path}: update transaction can only replace files and links")
        else:
            saved[name] = None
    return saved


def restore_files(root: Path, saved: dict[str, tuple[str, bytes | str, int] | None]) -> None:
    """Restore snapshotted paths after failed candidate verification."""
    for name, entry in saved.items():
        path = root / name
        if path.is_symlink() or path.is_file():
            path.unlink()
        if entry is None:
            continue
        kind, value, mode = entry
        path.parent.mkdir(parents=True, exist_ok=True)
        if kind == "symlink":
            path.symlink_to(value)
        else:
            path.write_bytes(value)
            os.chmod(path, mode)


def rollback_update(root: Path, metadata: Path, pending: dict,
                    saved: dict[str, tuple[str, bytes | str, int] | None]) -> list[str]:
    """Restore unchanged candidate paths and leave a journal for user-edited paths."""
    conflicts = []
    for name, entry in pending.get("paths", {}).items():
        current = guardian_update.current_value(root, name)
        if not any(guardian_update.same_content(current, allowed)
                   for allowed in (entry.get("candidate"), entry.get("before"))):
            conflicts.append(name)
            continue
        guardian_update.restore_value(root, name, entry.get("before"))
    if conflicts:
        pending.pop("recovery_pid", None)
        pending["recovery_conflicts"] = conflicts
        guardian_update.write_pending(metadata, pending)
        return conflicts
    # The receipt is written by the failed check and is not part of the setup
    # candidate. Restore its pre-update bytes after the owned files are safe.
    receipt = saved.get(".claude/agent-guard-receipt.json")
    if receipt is not None:
        restore_files(root, {".claude/agent-guard-receipt.json": receipt})
    guardian_update.remove_pending(metadata)
    return []


def candidate_diagnosis(launcher: str, root: Path, host: str,
                        lock: dict) -> dict:
    """Prove the newly selected release is the active runtime before the gate."""
    result = subprocess.run([launcher, "diagnose", "--root", str(root), "--host", host,
                             "--json"], cwd=root, capture_output=True, text=True, check=False)
    try:
        diagnosis = json.loads(result.stdout)
    except (ValueError, TypeError) as exc:
        raise Refused("candidate launcher could not report its selected release: "
                      + (result.stderr.strip() or str(exc))) from exc
    release = diagnosis.get("release")
    if (result.returncode or not diagnosis.get("healthy") or not isinstance(release, dict)
            or release.get("version") != lock["version"]
            or release.get("commit") != lock["commit"]):
        raise Refused("candidate launcher diagnosis did not confirm the requested active pin: "
                      + (result.stderr.strip() or json.dumps(diagnosis, sort_keys=True)))
    return {"outcome": "succeeded", "version": release["version"],
            "commit": release["commit"], "host": host}


def changed_candidate_paths(root: Path, expected: dict[str, tuple[str, bytes | str]]) -> list[str]:
    """Name candidate files or links changed while the project gate ran."""
    changed = []
    for name, (kind, value) in expected.items():
        path = root / name
        if kind == "symlink":
            matches = path.is_symlink() and os.readlink(path) == value
        else:
            matches = path.is_file() and not path.is_symlink() and path.read_bytes() == value
        if not matches:
            changed.append(name)
    return changed


def verify_candidate(root: Path, args, metadata: Path, pending: dict) -> tuple[dict, int, bool]:
    """Run the selected project's real gate through the normal public runner."""
    runner_argv = [os.sys.executable, str(Path(__file__).with_name("guardian.py")), "run",
                   str(root), "--base", args.base, "--json"]
    if args.task:
        runner_argv.extend(["--task", args.task])
    wait_for_journal = (
        "import json, os, sys, time\n"
        "journal, owner = sys.argv[1], int(sys.argv[2])\n"
        "while True:\n"
        "    try:\n"
        "        with open(journal, encoding='utf-8') as stream: record = json.load(stream)\n"
        "    except (OSError, ValueError): record = {}\n"
        "    if record.get('checker_pid') == os.getpid(): break\n"
        "    try: os.kill(owner, 0)\n"
        "    except ProcessLookupError: raise SystemExit(125)\n"
        "    time.sleep(0.02)\n"
        "os.execv(sys.argv[3], sys.argv[3:])\n"
    )
    argv = [os.sys.executable, "-c", wait_for_journal,
            str(guardian_update.pending_path(metadata)), str(os.getpid()), *runner_argv]
    env = os.environ.copy()
    env["GUARDIAN_UPDATE_PARENT_PID"] = str(os.getpid())
    process = subprocess.Popen(argv, cwd=root, env=env, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True, start_new_session=True)
    pending["checker_pid"] = process.pid
    guardian_update.write_pending(metadata, pending)
    interrupted = False

    def stop_checker(_signum, _frame):
        nonlocal interrupted
        interrupted = True
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass

    previous = {number: signal.getsignal(number) for number in (signal.SIGINT, signal.SIGTERM)}
    try:
        signal.signal(signal.SIGINT, stop_checker)
        signal.signal(signal.SIGTERM, stop_checker)
        stdout, stderr = process.communicate()
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)
    try:
        observation = json.loads(stdout)
    except (TypeError, ValueError):
        observation = {"outcome": "incomplete", "execution": {"outcome": "not_run",
                         "exit_code": None}, "error": stderr.strip() or
                         "candidate verification returned no JSON"}
    return observation, process.returncode or 0, interrupted


CLAUDE_BEGIN = "<!-- BEGIN maxi-quality agent-guard"
CLAUDE_END = "<!-- END maxi-quality agent-guard -->"


def _seed_claude_region(path: Path) -> None:
    """Seed a missing Claude region without importing a consumer fragment."""
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    # Complete and partial regions are left for migration's ownership checks:
    # existing checksum mismatches and malformed regions must remain conflicts.
    if CLAUDE_BEGIN in text or CLAUDE_END in text:
        return
    separator = "" if not text or text.endswith("\n\n") else "\n"
    if text and not text.endswith("\n"):
        separator = "\n\n"
    seed = (
        f"{CLAUDE_BEGIN} -->\n"
        "Run the project gate before finishing changed work:\n\n"
        "```bash\n"
        "python3 .claude/agent-guard/record-gate.py --gate\n"
        "```\n"
        f"{CLAUDE_END}\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + separator + seed, encoding="utf-8")


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
             allow_removed: bool = False, preferred_host: str | None = None
             ) -> tuple[dict, dict | None, str, str | None, list[str], list[str]]:
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
    other_guard_hosts = []
    if len(hosts) > 1:
        if preferred_host not in hosts:
            raise Refused("multiple Guardian hosts are configured; reconcile the selected integration first")
        host = preferred_host
        other_guard_hosts = [candidate for candidate in hosts if candidate != host]
    else:
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
    return gate, lock, profile, host, found, other_guard_hosts


def proposed_files(root: Path, gate: dict, lock: dict | None, enable: bool,
                   launcher: str, host: str | None = None,
                   update: bool = False, selected_host: str | None = None,
                   create_instruction: bool = False) -> dict[str, bytes]:
    names = [".claude/agent-guard.json"]
    if lock is not None:
        names.append(runtime.LOCK_NAME)
    migrate = enable or update
    operation_host = selected_host or host
    instruction_name = None
    if migrate and operation_host == "codex":
        names.extend([".codex/hooks.json", "AGENTS.md", ".gitignore"])
        instruction_name = "AGENTS.md"
    elif migrate and operation_host == "claude":
        names.extend([".claude/settings.json", ".gitignore"])
        instruction_path = lifecycle.instruction_path(
            root, operation_host, create=create_instruction)
        instruction_name = instruction_path.name if instruction_path else None
        if instruction_name is not None:
            names.append(instruction_name)
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
            if operation_host == "claude" and instruction_name is not None:
                _seed_claude_region(stage / instruction_name)
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
    if host == "claude":
        if settings(root, ".claude/settings.json").get("disableAllHooks") is True:
            raise Refused("Claude settings disable all hooks; enable them deliberately before Guardian setup")
        return
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
        metadata = Path(runner.git("rev-parse", "--absolute-git-dir", cwd=str(root)).strip())
        pending_update = guardian_update.read_pending(metadata)
        if pending_update:
            report["pending_update"] = {
                "status": "recovery_conflict" if pending_update.get("recovery_conflicts") else "incomplete",
                "host": pending_update.get("host"),
                "current_version": pending_update.get("current_version"),
                "requested_version": pending_update.get("requested_version"),
                "conflicts": pending_update.get("recovery_conflicts", []),
                "recovery": "explicit setup --apply restores the prior setup when candidate files are unchanged",
            }
            if not args.apply:
                report["outcome"] = "update_pending"
                report["error"] = "an earlier Guardian update did not finish; no update evidence is verified"
                report["next_step"] = "Review the pending candidate, then run setup --apply to recover the prior selection."
                return report, 3
            try:
                guardian_update.recover(root, metadata, pending_update)
            except guardian_update.PendingUpdateError as exc:
                report["outcome"] = "update_recovery_refused"
                report["error"] = str(exc)
                return report, 3
            report["outcome"] = "update_recovered"
            report["pending_update"]["status"] = "recovered"
            return report, 0
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
        preferred_host = (previous_state.get("selected_host") if previous_state else args.guardian)
        gate, old_lock, profile, host, found, other_guard_hosts = discover(
            root, source, allow_removed=removed, preferred_host=preferred_host)
        if previous_state and not removed:
            lifecycle.verify_instruction_region(
                root, previous_state["selected_host"],
                previous_state.get("owned", {}).get("instruction_region"))
        if (args.guardian and previous_state
                and previous_state["selected_host"] != args.guardian):
            raise Refused("changing an existing host is outside setup; request an explicit switch")
        report.update(current_gate=gate.get("gate_command"), current_version=old_lock,
                      installation_profile=profile, host=host, quality_configuration=found,
                      other_integrations=other_guard_hosts)
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
        guardian_host = args.guardian
        if guardian_host is None and previous_state:
            guardian_host = previous_state.get("selected_host")
        if guardian_host and lock and (args.guardian is not None or args.version is not None):
            skill_name, skill_target, create_link = skill_link(root, source, guardian_host)
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
            settings_name = ".codex/hooks.json" if guardian_host == "codex" else ".claude/settings.json"
            settings_bytes = changes.get(settings_name)
            settings_value = (json.loads(settings_bytes) if settings_bytes is not None else
                              settings(root, settings_name))
            expected_samples = (root / "samples/expected").is_dir()
            instruction_path = lifecycle.instruction_path(
                root, guardian_host, create=guardian_host == "codex")
            instruction = (changes.get(str(instruction_path.relative_to(root)))
                           if instruction_path else None)
            instruction_record = (lifecycle.instruction_region(
                instruction_path, guardian_host, instruction) if instruction_path else None)
            if instruction_record:
                previous_region = previous_state.get("owned", {}).get("instruction_region")
                if (isinstance(previous_region, dict)
                        and previous_region.get("path") == instruction_record["path"]):
                    if isinstance(previous_region.get("separator"), str):
                        instruction_record["separator"] = previous_region["separator"]
                else:
                    old_text = (instruction_path.read_text(encoding="utf-8")
                                if instruction_path.is_file() else "")
                    marker = lifecycle.INSTRUCTION_MARKERS[guardian_host][0]
                    if marker not in old_text:
                        instruction_record["separator"] = lifecycle.instruction_separator(old_text)
            owned = lifecycle.owned_records(settings_value, guardian_host,
                                             expected_samples, runtime, instruction_record)
            state = lifecycle.state_bytes(guardian_host, lock["version"], lock["commit"],
                                          skill_name if skill_owned else None,
                                          skill_target if skill_owned else None,
                                          owned)
            state_path = lifecycle.STATE_NAME
            safe_path(root, state_path)
            if not (root / state_path).exists() or (root / state_path).read_bytes() != state:
                changes[state_path] = state
        report["changes"] = {name: content.decode() for name, content in changes.items()}
        report["changes"].update({name: f"symlink -> {target}" for name, target in links.items()})
        if changed_version and other_guard_hosts:
            report["integration_conflicts"] = [
                f"{other} shares the project runtime pin; updating {report['host']} would change its active version"
                for other in other_guard_hosts]
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
        if changed_version and other_guard_hosts:
            report["outcome"] = "refused"
            report["error"] = "; ".join(report["integration_conflicts"])
            return report, 3
        if changed_version:
            runtime.prepare(source, lock["version"], lock["commit"], None)
        if changed_version and lock and lock.get("guard_enabled") is True:
            runtime.install_launcher(source, lock["commit"], str(launcher_dir))
        if changed_version:
            transaction_names = set(changes) | set(links) | {".claude/agent-guard-receipt.json"}
            originals = snapshot_files(root, transaction_names)
            durable_names = set(changes) | set(links)
            durable_originals = snapshot_files(root, durable_names)
            candidate_values = {name: ("file", content) for name, content in changes.items()}
            candidate_values.update({name: ("symlink", target) for name, target in links.items()})
            gate_name = ".claude/agent-guard.json"
            durable_names.add(gate_name)
            durable_originals.setdefault(gate_name, snapshot_files(root, {gate_name})[gate_name])
            if gate_name not in candidate_values and (root / gate_name).is_file():
                candidate_values[gate_name] = ("file", (root / gate_name).read_bytes())
            pending = {
                "schema": 1, "setup_pid": os.getpid(), "checker_pid": None,
                "host": report["host"], "current_version": old_lock,
                "requested_version": lock,
                "paths": guardian_update.encode_snapshot(durable_originals, candidate_values),
            }
            guardian_update.write_pending(metadata, pending)
            try:
                activate(root, changes, links)
                candidate = (candidate_diagnosis(launcher, root, report["host"], lock)
                             if lock.get("guard_enabled") is True else None)
                observation, rc, interrupted = verify_candidate(root, args, metadata, pending)
                if candidate:
                    observation["candidate"] = {"version": candidate["version"],
                                                 "commit": candidate["commit"],
                                                 "host": candidate["host"]}
                    observation["candidate_diagnosis"] = candidate
                if rc == 0:
                    expected = {name: value for name, value in candidate_values.items()
                                if value is not None}
                    changed = changed_candidate_paths(root, expected)
                    post_candidate_error = None
                    if changed:
                        post_candidate_error = "candidate files changed during project verification: " + ", ".join(changed)
                    elif candidate:
                        try:
                            candidate_diagnosis(launcher, root, report["host"], lock)
                        except (OSError, ValueError, Refused, subprocess.CalledProcessError) as exc:
                            post_candidate_error = "requested runtime pin was not active after project verification: " + str(exc)
                    if post_candidate_error:
                        rc = 3
                        observation["outcome"] = "incomplete"
                        observation["error"] = post_candidate_error
                        report["verification"] = observation
                report["verification"] = observation
                report["next_step"] = observation.get("next_step")
                if interrupted:
                    report["outcome"] = "update_interrupted"
                    report["error"] = "candidate verification was interrupted"
                    report["verification"]["outcome"] = "interrupted"
                    conflicts = rollback_update(root, metadata, pending, originals)
                    if conflicts:
                        report["outcome"] = "update_rollback_pending"
                        report["error"] += "; rollback preserved changed project files and remains pending: " + ", ".join(conflicts)
                        report["pending_recovery"] = {"status": "conflict", "paths": conflicts}
                    else:
                        report["error"] += "; the prior selection was restored"
                    report["verification"]["error"] = report["error"]
                    return report, 3
                if rc:
                    report["outcome"] = ("update_checks_failed" if observation.get("execution", {}).get("outcome") == "failed"
                                          else "update_checks_incomplete")
                    report["error"] = observation.get("error") or "candidate project verification did not pass"
                    conflicts = rollback_update(root, metadata, pending, originals)
                    if conflicts:
                        report["outcome"] = "update_rollback_pending"
                        report["error"] += "; rollback preserved changed project files and remains pending: " + ", ".join(conflicts)
                        report["pending_recovery"] = {"status": "conflict", "paths": conflicts}
                    return report, rc
                report["outcome"] = "applied" if changes else "unchanged"
                guardian_update.remove_pending(metadata)
                return report, 0
            except BaseException:
                rollback_update(root, metadata, pending, originals)
                raise
        activate(root, changes, links)
        report["outcome"] = "applied" if changes else "unchanged"
        return report, 0
    except (OSError, ValueError, SyntaxError, runtime.RuntimeError_, migration.Refused,
            subprocess.CalledProcessError) as exc:
        report["error"] = str(exc)
        return report, 3
